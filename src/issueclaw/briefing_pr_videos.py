"""Attach published briefing videos to source PRs with recoverable comment receipts."""

import hashlib
import json
import re
import subprocess

from issueclaw import briefing_trace as trace
from issueclaw import learning_videos

# What GitHub turns an uploaded video into: a reference that renders as a player.
EMBED = "https://github.com/user-attachments/assets/"

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


def find_comment(api, endpoint, actor, marker):
    """Our earlier comment for this video, found by author and marker, if any."""
    return next(
        (
            c
            for c in api(endpoint, paginate=True)
            if c.get("user", {}).get("login") == actor and marker in c.get("body", "")
        ),
        None,
    )


def gh_comment(repo, number, body, video, cwd):
    """Post a PR comment with the video uploaded and embedded as a native player.

    `gh` (2.99+) uploads each --attach file and rewrites the body's reference to it,
    here `![…](./learnings/<n>/video.mp4)`, to the uploaded asset. It prints the
    comment URL; a non-zero exit may still leave a comment behind.
    """
    result = subprocess.run(
        ["gh", "pr", "comment", number, "-R", repo, "--body-file", "-"]
        + ["--attach", video],
        input=body,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        timeout=600,
    )
    return result.stdout.strip().splitlines()[-1]


def comment_body(marker, lesson, video, links):
    kind = (
        "Review walkthrough" if lesson.get("kind") == "review" else "Engineering lesson"
    )
    head = (
        f"\n\nReviewed commit: `{lesson['head_sha']}`. Review guidance, not an approval."
        if lesson.get("kind") == "review"
        else ""
    )
    return (
        f"{marker}\n### {kind}: {lesson['title']}\n\n{lesson['rule']}{head}\n\n"
        f"{video}\n\n" + "\n".join(f"- {line}" for line in links)
    )


def attach(out, repos, state, run_url, api=github_api, comment=gh_comment):
    """Only published clips go to configured source repos; API reads recover retries.

    The GitHub author plus content-hash marker identifies an accepted write even if
    its response was lost. Never rely on a local receipt alone or another user's marker.
    The video is embedded as a native player when `gh` can upload it; otherwise the
    comment links the hosted copy (or the Slack post) and the run reports the gap.
    """
    receipts = []
    failures = []
    hosted_path = out / "hosted-media.json"
    hosted = json.loads(hosted_path.read_text()) if hosted_path.exists() else {}
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

                    media = hosted.get("lessons", {}).get(str(lesson["n"]), {})
                    links = []
                    if media.get("page"):
                        links.append(
                            f"[Review page]({media['page']}): the video, its filmstrip and QA stills."
                        )
                    links += [
                        f"[Slack post]({link}) (team Slack access required).",
                        f"[Run and review artifacts]({run_url}): candidate selection, evidence, "
                        "questions, storyboard, pacing, source and QA, kept for 90 days.",
                    ]
                    prior = find_comment(api, endpoint, actor, marker)
                    embedded = prior is not None and EMBED in prior.get("body", "")
                    if prior is None:
                        video = f"./{lesson['dir']}/video.mp4"
                        try:
                            url = comment(
                                repo,
                                number,
                                comment_body(
                                    marker, lesson, f"![video]({video})", links
                                ),
                                video,
                                out,
                            )
                            prior = {"html_url": url}
                            embedded = True
                        except (OSError, subprocess.SubprocessError) as error:
                            # Link the video instead; keep a comment gh did manage to embed.
                            receipt["embed_error"] = str(error)[:300]
                            watch = media.get("video") or link
                            body = comment_body(
                                marker, lesson, f"[▶ Watch the video]({watch})", links
                            )
                            prior = find_comment(api, endpoint, actor, marker)
                            embedded = prior is not None and EMBED in prior["body"]
                            if prior is None:
                                prior = api(endpoint, "POST", {"body": body})
                            elif not embedded:
                                prior = api(
                                    f"repos/{repo}/issues/comments/{prior['id']}",
                                    "PATCH",
                                    {"body": body},
                                )
                            if not embedded:
                                failures.append(
                                    f"{repo}#{number}: video linked, not embedded"
                                )
                    receipt.update(
                        status="attached",
                        embedded=embedded,
                        comment_url=prior["html_url"],
                    )
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
