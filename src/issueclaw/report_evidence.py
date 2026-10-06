"""Read-only GitHub evidence for reports; company scope belongs in caller config."""

import argparse
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from issueclaw.pr_waiting import classify_waiting


def gh_json(*args):
    try:
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True, check=True, timeout=180
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "GitHub request failed").strip()[:1500]
        raise RuntimeError(f"GitHub evidence request failed: {detail}") from exc
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


def compact_discussions(repo, number):
    """Page comments/reviews together; fetch inline threads only if reviews exist.

    Published inline comments belong to a review. A PR with no reviews cannot have
    published inline review comments; private pending drafts are not report evidence.
    """
    owner, name = repo.split("/")
    query = """query($owner:String!, $name:String!, $number:Int!,
        $commentsCursor:String, $reviewsCursor:String,
        $commentsEnabled:Boolean!, $reviewsEnabled:Boolean!) {
      repository(owner:$owner,name:$name) { pullRequest(number:$number) {
        comments(first:100,after:$commentsCursor) @include(if:$commentsEnabled) {
          nodes { databaseId body createdAt updatedAt url author { login __typename ... on User { name } } }
          pageInfo { hasNextPage endCursor }
        }
        reviews(first:100,after:$reviewsCursor) @include(if:$reviewsEnabled) {
          totalCount
          nodes { databaseId body submittedAt state url commit { oid } author { login __typename ... on User { name } } }
          pageInfo { hasNextPage endCursor }
        }
      } }
    }"""
    results = {"comments": [], "reviews": []}
    enabled = {"comments": True, "reviews": True}
    cursors = {}
    review_count = 0
    while any(enabled.values()):
        args = [
            "api",
            "graphql",
            "-f",
            "query=" + query,
            "-f",
            "owner=" + owner,
            "-f",
            "name=" + name,
            "-F",
            "number=" + str(number),
        ]
        for key in enabled:
            args += ["-F", key + "Enabled=" + str(enabled[key]).lower()]
            if cursors.get(key):
                args += ["-f", key + "Cursor=" + cursors[key]]
        data = gh_json(*args)
        if data.get("errors"):
            raise ValueError(f"Incomplete discussion query for {repo}#{number}")
        pr = data["data"]["repository"]["pullRequest"]
        if pr is None:
            raise ValueError(f"Missing discussion source {repo}#{number}")
        for key in enabled:
            if not enabled[key]:
                continue
            connection = pr[key]
            if key == "reviews":
                review_count = connection["totalCount"]
            for node in connection["nodes"]:
                results[key].append(
                    {
                        "id": node["databaseId"],
                        "body": node["body"],
                        "created_at": node.get("createdAt"),
                        "updated_at": node.get("updatedAt"),
                        "submitted_at": node.get("submittedAt"),
                        "html_url": node["url"],
                        "user": node.get("author"),
                        "state": node.get("state"),
                        "commit_id": (node.get("commit") or {}).get("oid"),
                    }
                )
            enabled[key] = connection["pageInfo"]["hasNextPage"]
            cursors[key] = connection["pageInfo"].get("endCursor")
    inline = []
    if review_count:
        thread_query = """query($owner:String!,$name:String!,$number:Int!,$cursor:String) {
          repository(owner:$owner,name:$name) { pullRequest(number:$number) {
            reviewThreads(first:20,after:$cursor) {
              nodes { id comments(first:20) {
                nodes { databaseId body createdAt updatedAt url path line
                        replyTo { databaseId } author { login __typename ... on User { name } } }
                pageInfo { hasNextPage endCursor }
              } }
              pageInfo { hasNextPage endCursor }
            }
          } }
        }"""
        cursor = None
        while True:
            args = [
                "api",
                "graphql",
                "-f",
                "query=" + thread_query,
                "-f",
                "owner=" + owner,
                "-f",
                "name=" + name,
                "-F",
                "number=" + str(number),
            ]
            if cursor:
                args += ["-f", "cursor=" + cursor]
            data = gh_json(*args)
            if data.get("errors"):
                raise ValueError(f"Incomplete inline query for {repo}#{number}")
            threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]
            for thread in threads["nodes"]:
                comments = thread["comments"]
                while True:
                    for node in comments["nodes"]:
                        inline.append(
                            {
                                "id": node["databaseId"],
                                "body": node["body"],
                                "created_at": node["createdAt"],
                                "updated_at": node["updatedAt"],
                                "html_url": node["url"],
                                "user": node.get("author"),
                                "path": node.get("path"),
                                "line": node.get("line"),
                                "in_reply_to_id": (node.get("replyTo") or {}).get(
                                    "databaseId"
                                ),
                            }
                        )
                    if not comments["pageInfo"]["hasNextPage"]:
                        break
                    query = """query($id:ID!,$cursor:String!) {
                      node(id:$id) { ... on PullRequestReviewThread { comments(first:100,after:$cursor) {
                        nodes { databaseId body createdAt updatedAt url path line replyTo { databaseId } author { login __typename ... on User { name } } }
                        pageInfo { hasNextPage endCursor }
                      } } }
                    }"""
                    more = gh_json(
                        "api",
                        "graphql",
                        "-f",
                        "query=" + query,
                        "-f",
                        "id=" + thread["id"],
                        "-f",
                        "cursor=" + comments["pageInfo"]["endCursor"],
                    )
                    if more.get("errors"):
                        raise ValueError(
                            f"Incomplete inline pagination for {repo}#{number}"
                        )
                    comments = more["data"]["node"]["comments"]
            if not threads["pageInfo"]["hasNextPage"]:
                break
            cursor = threads["pageInfo"]["endCursor"]
    results["review_comments"] = inline
    return results


def current_activity(repo, pr):
    """Page current commits and human handoffs separately from dated learning.

    Commit dates are not a complete push log; force-push events retain their real
    timestamp. Current discussions are collected before filtering the merge window.
    """
    query = """query($owner:String!,$name:String!,$number:Int!,
        $commitsCursor:String,$eventsCursor:String,
        $commitsEnabled:Boolean!,$eventsEnabled:Boolean!) {
      repository(owner:$owner,name:$name) { pullRequest(number:$number) {
        state headRefOid
        commits(first:100,after:$commitsCursor) @include(if:$commitsEnabled) {
          nodes { commit { oid committedDate url
            author { user { login } } committer { user { login } } } }
          pageInfo { hasNextPage endCursor }
        }
        timelineItems(first:100,after:$eventsCursor,itemTypes:[REVIEW_REQUESTED_EVENT,
          REVIEW_REQUEST_REMOVED_EVENT,HEAD_REF_FORCE_PUSHED_EVENT,
          READY_FOR_REVIEW_EVENT,CONVERT_TO_DRAFT_EVENT,REOPENED_EVENT])
          @include(if:$eventsEnabled) {
          nodes { __typename
            ... on ReviewRequestedEvent { createdAt actor { login __typename } }
            ... on ReviewRequestRemovedEvent { createdAt actor { login __typename } }
            ... on HeadRefForcePushedEvent { createdAt actor { login __typename } }
            ... on ReadyForReviewEvent { createdAt actor { login __typename } }
            ... on ConvertToDraftEvent { createdAt actor { login __typename } }
            ... on ReopenedEvent { createdAt actor { login __typename } }
          }
          pageInfo { hasNextPage endCursor }
        }
      } }
    }"""
    owner, name = repo.split("/")
    events, enabled, cursors = [], {"commits": True, "events": True}, {}
    while any(enabled.values()):
        args = [
            "api",
            "graphql",
            "-f",
            "query=" + query,
            "-f",
            "owner=" + owner,
            "-f",
            "name=" + name,
            "-F",
            "number=" + str(pr["number"]),
        ]
        for key in enabled:
            args += ["-F", key + "Enabled=" + str(enabled[key]).lower()]
            if cursors.get(key):
                args += ["-f", key + "Cursor=" + cursors[key]]
        data = gh_json(*args)
        if data.get("errors"):
            raise ValueError(f"Incomplete current activity for {repo}#{pr['number']}")
        current = data["data"]["repository"]["pullRequest"]
        if (
            not current
            or current["state"] != "OPEN"
            or current["headRefOid"] != pr["headRefOid"]
        ):
            raise ValueError(
                f"PR {pr['number']} changed during activity collection; retry"
            )
        for key in enabled:
            if not enabled[key]:
                continue
            connection = current["commits" if key == "commits" else "timelineItems"]
            for node in connection["nodes"]:
                if key == "commits":
                    commit = node["commit"]
                    events.append(
                        {
                            "kind": "commit",
                            "at": commit["committedDate"],
                            "url": commit["url"],
                            "sha": commit["oid"],
                            "identity_complete": bool(
                                (commit.get("author", {}).get("user") or {}).get(
                                    "login"
                                )
                            ),
                            "actors": [
                                (commit.get(role, {}).get("user") or {}).get("login")
                                for role in ("author", "committer")
                            ],
                        }
                    )
                else:
                    events.append(
                        {
                            "kind": node["__typename"],
                            "at": node["createdAt"],
                            "url": pr["url"],
                            "actors": [(node.get("actor") or {}).get("login")],
                            "automated": (node.get("actor") or {}).get("__typename")
                            == "Bot",
                        }
                    )
            enabled[key] = connection["pageInfo"]["hasNextPage"]
            cursors[key] = connection["pageInfo"].get("endCursor")
    for channel, kind in (
        ("comments", "comment"),
        ("reviews", "review"),
        ("review_comments", "inline_comment"),
    ):
        for event in pr["discussion_snapshot"][channel]:
            events.append(
                {
                    "kind": kind,
                    "at": event.get("submitted_at")
                    or event.get("updated_at")
                    or event.get("created_at"),
                    "url": event.get("html_url"),
                    "state": event.get("state"),
                    "actors": [(event.get("user") or {}).get("login")],
                    "automated": (event.get("user") or {}).get("type") == "Bot"
                    or (event.get("user") or {}).get("__typename") == "Bot",
                }
            )
    events.sort(key=lambda event: event.get("at") or "")
    return {
        "complete": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "head_sha": pr["headRefOid"],
        "events": events,
        "limitations": [
            "Commit timestamps are not a complete push log; deleted comments and removed commits are unavailable.",
            "Issue-comment reviews require reading their bodies; formal reviews alone may not capture the team's review process.",
        ],
    }


def event_evidence(repo, number, start, end, *, compact=False, include_current=False):
    """Retain all discussion channels; never backdate post-cutoff comment text."""
    result = {}
    bundled = compact_discussions(repo, number) if compact else None
    if bundled is not None:
        result["review_snapshot"] = bundled["reviews"]
    current = {}
    for key, endpoint, timestamps in (
        ("comments", f"issues/{number}/comments", ("created_at", "updated_at")),
        ("reviews", f"pulls/{number}/reviews", ("submitted_at",)),
        ("review_comments", f"pulls/{number}/comments", ("created_at", "updated_at")),
    ):
        pages = (
            [bundled[key]]
            if bundled is not None
            else gh_json(
                "api", "--paginate", "--slurp", f"repos/{repo}/{endpoint}?per_page=100"
            )
        )
        if include_current:
            current[key] = [event for page in pages for event in page]
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
    if include_current:
        result["discussion_snapshot"] = current
    return result


def collect(config, start, end, out_dir, *, include_open=False, compact=False):
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
    if include_open:
        fields += ",reviewRequests,reviewDecision,headRefOid"
    people = {
        login.casefold(): name for login, name in config.get("people", {}).items()
    }
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

            if include_open:
                # Carry-over work must survive even when it has no recent update.
                rows = gh_json(
                    "pr",
                    "list",
                    "-R",
                    repo,
                    "--state",
                    "open",
                    "--limit",
                    "1000",
                    "--json",
                    fields,
                )
                if len(rows) >= 1000:
                    raise ValueError(
                        "open query reached 1000 PRs; inventory incomplete"
                    )
                by_number.update((row["number"], row) for row in rows)

            def enrich(pr):
                pr = dict(pr)
                pr.update(
                    event_evidence(
                        repo,
                        pr["number"],
                        start,
                        end,
                        compact=compact,
                        include_current=include_open and pr["state"] == "OPEN",
                    )
                )
                bucket = classify(pr, start, end)
                if include_open and pr["state"] == "OPEN":
                    bucket = "draft" if pr["isDraft"] else "open"
                    # Fetch rollups one PR at a time: adding them to a 100-row
                    # GraphQL search can exceed GitHub response/resource limits.
                    snapshot = gh_json(
                        "pr",
                        "view",
                        str(pr["number"]),
                        "-R",
                        repo,
                        "--json",
                        "headRefOid,statusCheckRollup",
                    )
                    if snapshot["headRefOid"] != pr["headRefOid"]:
                        raise ValueError(
                            f"PR {pr['number']} head changed during collection; retry"
                        )
                    pr["statusCheckRollup"] = snapshot["statusCheckRollup"]
                    pr["activity_snapshot"] = current_activity(repo, pr)
                    pr["waiting"] = classify_waiting(
                        pr, instant(pr["activity_snapshot"]["as_of"]), people
                    )
                    pr["requested_reviewers"] = [
                        people.get(
                            (r.get("login") or "").casefold(),
                            r.get("login")
                            or r.get("name")
                            or r.get("slug")
                            or "unknown",
                        )
                        for r in pr.get("reviewRequests", [])
                    ]
                if bucket is None:
                    return None
                login = (pr.get("author") or {}).get("login", "unknown")
                pr["person"] = people.get(login.casefold(), login)
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
