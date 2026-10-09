"""Attach published briefing videos to source PRs with recoverable comment receipts."""

import hashlib
import json
import re
import subprocess

from issueclaw import briefing_trace as trace
from issueclaw import learning_videos

PR_URL = re.compile(
    r"https://github\.com/([\w.-]+/[\w.-]+)/pull/([1-9]\d*)(?:[/?#].*)?$"
)


def github_api(endpoint, method="GET", data=None, paginate=False):
    args = ["gh", "api", endpoint, "--method", method]
    if paginate:
        args += ["--paginate", "--slurp"]
    if data is not None:
        args += ["--input", "-"]
    result = subprocess.run(
        args,
        input=json.dumps(data) if data else None,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    value = json.loads(result.stdout)
    return [item for page in value for item in page] if paginate else value


def attach(out, repos, state, run_url, api=github_api):
    """Only published clips go to configured source repos; API reads recover retries.

    The GitHub author plus content-hash marker identifies an accepted write even if
    its response was lost. Never rely on a local receipt alone or another user's marker.
    """
    receipts = []
    failures = []
    try:
        cutoff = json.loads((out / "delivery.json").read_text())["cutoff"]
        if state.get("last_cutoff") != cutoff or state.get("pending"):
            raise RuntimeError(
                "PR video attachment requires the completed matching cutoff"
            )
        videos = state.get("lesson_videos", {})
        if videos.get("cutoff") != cutoff:
            raise RuntimeError("Uploaded videos do not match this cutoff")
        actor = api("user")["login"]
        for lesson in learning_videos.lessons_of(out):
            if not lesson["video"]:
                continue
            link = videos["files"].get(str(lesson["n"]), {}).get("permalink")
            if not link:
                failures.append(f"Video {lesson['n']} was not uploaded")
                receipts.append({"n": lesson["n"], "status": "not_uploaded"})
                continue
            targets = set()
            for url in lesson["sources"]:
                match = PR_URL.fullmatch(url)
                if match:
                    targets.add((match[1], match[2]))
            if lesson.get("kind") == "review":
                repo, number = lesson["pr"].rsplit("#", 1)
                targets = {(repo, number)}
            if not targets:
                failures.append(f"Video {lesson['n']} has no source PR")
            digest = hashlib.sha256(
                (out / lesson["dir"] / "video.mp4").read_bytes()
            ).hexdigest()
            for repo, number in sorted(targets):
                receipt = {
                    "n": lesson["n"],
                    "pr": f"{repo}#{number}",
                    "video": link,
                    "sha256": digest,
                }
                receipts.append(receipt)
                try:
                    if repo not in repos or not number.isdigit():
                        raise RuntimeError(
                            "Source PR is outside configured repositories"
                        )
                    pr = api(f"repos/{repo}/pulls/{number}")
                    if lesson.get("kind") == "review" and (
                        pr["state"] != "open"
                        or pr["draft"]
                        or pr["head"]["sha"] != lesson["head_sha"]
                    ):
                        raise RuntimeError(
                            "Review head/state changed; regenerate before attaching"
                        )
                    marker = f"<!-- issueclaw-video:{digest}:{repo}#{number} -->"
                    endpoint = f"repos/{repo}/issues/{number}/comments"
                    prior = next(
                        (
                            c
                            for c in api(endpoint, paginate=True)
                            if c.get("user", {}).get("login") == actor
                            and marker in c.get("body", "")
                        ),
                        None,
                    )
                    if prior is None:
                        kind = (
                            "Review walkthrough"
                            if lesson.get("kind") == "review"
                            else "Engineering lesson"
                        )
                        head = (
                            f"\n\nReviewed commit: `{lesson['head_sha']}`. Review guidance, not an approval."
                            if lesson.get("kind") == "review"
                            else ""
                        )
                        body = (
                            f"{marker}\n### {kind}: {lesson['title']}\n\n{lesson['rule']}"
                            f"{head}\n\n[Watch video]({link}) (team Slack access required).\n\n"
                            f"[Run and review artifacts]({run_url}): candidate selection, evidence, questions, "
                            "storyboard, pacing, source and QA. Generation artifacts are retained for 90 days."
                        )
                        prior = api(endpoint, "POST", {"body": body})
                    receipt.update(status="attached", comment_url=prior["html_url"])
                except (
                    OSError,
                    ValueError,
                    KeyError,
                    RuntimeError,
                    subprocess.SubprocessError,
                ) as error:
                    receipt.update(status="failed", error=str(error)[:500])
                    failures.append(f"{repo}#{number}: {type(error).__name__}")
        if failures:
            raise RuntimeError("PR video attachment incomplete: " + "; ".join(failures))
    finally:
        trace.write_json(out / "pr-video-delivery.json", receipts)
