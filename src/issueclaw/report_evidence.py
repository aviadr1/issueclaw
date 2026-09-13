"""Read-only GitHub evidence for reports; company scope belongs in caller config."""

import argparse
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


def gh_json(*args):
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True, timeout=180
    )
    return json.loads(result.stdout)


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def classify(pr, start, end):
    """Use an exclusive cutoff, and distinguish merged code from deployed work."""
    merged = pr.get("mergedAt")
    if merged and start <= instant(merged) < end:
        return "merged"
    updated = instant(pr["updatedAt"])
    if not start <= updated < end:
        # Event timestamps, not mutable latest metadata, establish activity.
        if any(pr.get(key) for key in ("comments", "reviews", "review_comments")) or (
            pr.get("createdAt") and start <= instant(pr["createdAt"]) < end
        ):
            return "activity"
        return None
    if pr["state"] == "OPEN":
        return "draft" if pr["isDraft"] else "open"
    return "follow_up" if merged else "closed_unmerged"


def event_evidence(repo, number, start, end):
    """Retain all discussion channels; never backdate post-cutoff comment text."""
    result = {}
    for key, endpoint, timestamps in (
        ("comments", f"issues/{number}/comments", ("created_at", "updated_at")),
        ("reviews", f"pulls/{number}/reviews", ("submitted_at",)),
        ("review_comments", f"pulls/{number}/comments", ("created_at", "updated_at")),
    ):
        pages = gh_json(
            "api", "--paginate", "--slurp", f"repos/{repo}/{endpoint}?per_page=100"
        )
        result[key] = []
        for page in pages:
            for event in page:
                if not any(
                    event.get(t) and start <= instant(event[t]) < end
                    for t in timestamps
                ):
                    continue
                evidence = {
                    k: event.get(k)
                    for k in (
                        "id",
                        "body",
                        "created_at",
                        "updated_at",
                        "submitted_at",
                        "html_url",
                        "user",
                        "state",
                        "path",
                        "line",
                        "in_reply_to_id",
                    )
                }
                edited_after = (
                    event.get("updated_at") and instant(event["updated_at"]) >= end
                )
                evidence["body_available_at_cutoff"] = (
                    not bool(edited_after) if key != "reviews" else None
                )
                if edited_after:
                    evidence["body"] = None
                result[key].append(evidence)
    return result


def collect(config, start, end, out_dir):
    """Never suppress ticket-linked, CI, release, or bot PRs before synthesis.

    The separate merge query retains work merged in-window but updated later.
    A saturated query fails explicitly instead of returning a plausible partial report.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "start": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "repositories": [],
        "errors": [],
        "complete": False,
        "metadata_as_of": datetime.now(timezone.utc).isoformat(),
        "limitations": [
            "PR metadata and review bodies are current snapshots, not historical state.",
            "Deleted events and overwritten historical text cannot be reconstructed.",
            "Activity covers creation, latest update, merge and retained discussion; it is not a complete push/state-change event log.",
        ],
    }
    fields = "number,title,body,author,url,headRefName,baseRefName,state,isDraft,createdAt,updatedAt,mergedAt"
    for repo in config["repos"]:
        try:
            by_number = {}
            for field in ("merged", "updated"):
                rows = gh_json(
                    "pr",
                    "list",
                    "-R",
                    repo,
                    "--state",
                    "all",
                    "--limit",
                    "1000",
                    "--search",
                    # Latest updatedAt can move arbitrarily beyond the cutoff.
                    f"updated:>={start.date()}"
                    if field == "updated"
                    else f"merged:{start.date()}..{end.date()}",
                    "--json",
                    fields,
                )
                if len(rows) >= 1000:
                    raise ValueError(
                        f"{field} query reached 1000 PRs; narrow the window"
                    )
                by_number.update((row["number"], row) for row in rows)

            def enrich(pr):
                pr = dict(pr)
                pr.update(event_evidence(repo, pr["number"], start, end))
                bucket = classify(pr, start, end)
                if bucket is None:
                    return None
                login = (pr.get("author") or {}).get("login", "unknown")
                pr["person"] = config.get("people", {}).get(login, login)
                pr["repo"] = repo
                pr["bucket"] = bucket
                blob = "\n".join(
                    pr.get(key) or "" for key in ("title", "headRefName", "body")
                )
                pr["ticket_mentions"] = sorted(
                    set(re.findall(r"\b[A-Z][A-Z0-9]*-\d+\b", blob))
                )
                return pr

            with ThreadPoolExecutor(max_workers=8) as executor:
                evidence = [
                    pr
                    for pr in executor.map(
                        enrich,
                        sorted(by_number.values(), key=lambda row: row["number"]),
                    )
                    if pr is not None
                ]
            filename = repo.replace("/", "--") + ".json"
            (out_dir / filename).write_text(json.dumps(evidence, indent=2) + "\n")
            manifest["repositories"].append(
                {
                    "repo": repo,
                    "file": filename,
                    "count": len(evidence),
                    "counts": {
                        bucket: sum(pr["bucket"] == bucket for pr in evidence)
                        for bucket in (
                            "merged",
                            "open",
                            "draft",
                            "follow_up",
                            "closed_unmerged",
                            "activity",
                        )
                    },
                }
            )
            inventory = [
                {
                    key: pr[key]
                    for key in (
                        "repo",
                        "number",
                        "title",
                        "person",
                        "url",
                        "bucket",
                        "baseRefName",
                        "mergedAt",
                        "updatedAt",
                        "ticket_mentions",
                    )
                }
                for pr in evidence
            ]
            (out_dir / (repo.replace("/", "--") + "--inventory.json")).write_text(
                json.dumps(inventory, indent=2) + "\n"
            )
        except (subprocess.SubprocessError, ValueError, KeyError, OSError) as exc:
            manifest["errors"].append({"repo": repo, "error": str(exc)})
    manifest["complete"] = not manifest["errors"]
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--start", required=True, help="Inclusive ISO-8601 UTC timestamp"
    )
    parser.add_argument("--end", required=True, help="Exclusive ISO-8601 UTC cutoff")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    start, end = instant(args.start), instant(args.end)
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        parser.error("start and end must be timezone-aware, with start before end")
    config = json.loads(args.config.read_text())
    repos = config.get("repos", [])
    if (
        not repos
        or len(repos) != len(set(repos))
        or any(not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) for repo in repos)
    ):
        parser.error("config requires unique owner/repository names")
    manifest = collect(
        config,
        start.astimezone(timezone.utc),
        end.astimezone(timezone.utc),
        args.out_dir,
    )
    print(json.dumps(manifest, indent=2))
    if not manifest["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
