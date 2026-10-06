"""Daily learning briefings: collect evidence, then publish a resumable Slack thread.

Company scope and schedule belong in the calling knowledge repository. State lives
on a separate Git branch; collection and generation never edit the Linear mirror.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import yaml

from issueclaw import report_evidence as report
from issueclaw import slack_canvas


def previous_cutoff(end, weekdays):
    start = end - timedelta(days=1)
    while start.weekday() not in weekdays:
        start -= timedelta(days=1)
    return start


def window(now, zone, hour, weekdays=None):
    weekdays = set(range(7) if weekdays is None else weekdays)
    if not weekdays or not weekdays <= set(range(7)):
        raise ValueError("weekdays must contain weekday numbers from 0 to 6")
    local = now.astimezone(ZoneInfo(zone))
    end = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if local < end:
        end -= timedelta(days=1)
    while end.weekday() not in weekdays:
        end -= timedelta(days=1)
    return previous_cutoff(end, weekdays).astimezone(timezone.utc), end.astimezone(
        timezone.utc
    )


class StateStore:
    def __init__(self, repo, branch, channel):
        self.repo, self.branch = repo, branch
        self.path = f"briefings/{channel}.json"
        self.sha = None

    def api(self, endpoint, method="GET", data=None):
        env = dict(os.environ)
        env["GH_TOKEN"] = os.environ["GITHUB_TOKEN"]
        args = ["gh", "api", endpoint, "--method", method]
        if data is not None:
            args += ["--input", "-"]
        result = subprocess.run(
            args,
            input=json.dumps(data) if data else None,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        if result.returncode:
            # Only a verified missing resource is an empty initial checkpoint.
            if method == "GET" and "(HTTP 404)" in result.stderr:
                return None
            raise RuntimeError(f"Checkpoint API failed: {method} {endpoint}")
        return json.loads(result.stdout)

    def read(self):
        data = self.api(f"repos/{self.repo}/contents/{self.path}?ref={self.branch}")
        if data is None:
            return {"messages": {}, "last_cutoff": None}
        self.sha = data["sha"]
        return json.loads(base64.b64decode(data["content"]))

    def save(self, state):
        if self.api(f"repos/{self.repo}/git/ref/heads/{self.branch}") is None:
            repo = self.api(f"repos/{self.repo}")
            if repo is None:
                raise RuntimeError("Caller repository is unavailable")
            ref = self.api(f"repos/{self.repo}/git/ref/heads/{repo['default_branch']}")
            if ref is None:
                raise RuntimeError("Default branch is unavailable")
            self.api(
                f"repos/{self.repo}/git/refs",
                "POST",
                {"ref": f"refs/heads/{self.branch}", "sha": ref["object"]["sha"]},
            )
        payload = {
            "message": "Record daily briefing delivery",
            "branch": self.branch,
            "content": base64.b64encode(
                (json.dumps(state, indent=2) + "\n").encode()
            ).decode(),
        }
        if self.sha:
            payload["sha"] = self.sha
        result = self.api(f"repos/{self.repo}/contents/{self.path}", "PUT", payload)
        if result is None:
            raise RuntimeError("Checkpoint write returned no content")
        self.sha = result["content"]["sha"]


class SlackRejected(RuntimeError):
    """Slack explicitly rejected a message without accepting it."""


class Slack:
    def __init__(self, channel, token):
        self.channel = channel
        self.client = httpx.Client(
            base_url="https://slack.com/api/",
            timeout=60,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.history = None

    def api(self, method, payload):
        response = None
        for attempt in range(4):
            response = self.client.post(method, json=payload)
            if response.status_code != 429:
                break
            if attempt == 3:
                raise SlackRejected("Slack rate limit: retry the prepared thread later")
            time.sleep(min(float(response.headers.get("Retry-After", "2")), 30))
        if response is None:
            raise RuntimeError("Slack request was not attempted")
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise SlackRejected(f"Slack {method}: {data.get('error', 'unknown error')}")
        return data

    def find(self, key):
        if self.history is None:
            self.history = []
            cursor = None
            while True:
                payload = {
                    "channel": self.channel,
                    "limit": 100,
                    "oldest": str(
                        (datetime.now(timezone.utc) - timedelta(days=60)).timestamp()
                    ),
                    "include_all_metadata": True,
                }
                if cursor:
                    payload["cursor"] = cursor
                data = self.api("conversations.history", payload)
                self.history.extend(data["messages"])
                cursor = data.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
        for message in self.history:
            if message.get("metadata", {}).get("event_payload", {}).get("key") == key:
                return message
        # Replies are absent from conversations.history: search the tagged parent.
        cutoff = key.split("/", 1)[0]
        parent = next(
            (
                m
                for m in self.history
                if m.get("metadata", {}).get("event_payload", {}).get("key")
                == cutoff + "/01-toplevel.md"
            ),
            None,
        )
        if parent:
            cursor = None
            while True:
                payload = {
                    "channel": self.channel,
                    "ts": parent["ts"],
                    "limit": 100,
                    "include_all_metadata": True,
                }
                if cursor:
                    payload["cursor"] = cursor
                data = self.api("conversations.replies", payload)
                for message in data["messages"]:
                    if (
                        message.get("metadata", {}).get("event_payload", {}).get("key")
                        == key
                    ):
                        return message
                cursor = data.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
        return None

    def post(self, text, key, thread):
        text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"<\2|\1>", text)
        text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
        payload = {
            "channel": self.channel,
            "text": text,
            "unfurl_links": False,
            "unfurl_media": False,
            "reply_broadcast": False,
            "metadata": {
                "event_type": "daily_learning_briefing",
                "event_payload": {"key": key},
            },
            "client_msg_id": str(uuid.uuid5(uuid.NAMESPACE_URL, key)),
        }
        if thread:
            payload["thread_ts"] = thread
        message = self.api("chat.postMessage", payload)
        self.history = None
        return message["ts"]


def publish(messages, state, cutoff, slack, save, *, canvas_invitation=None):
    """Checkpoint every message; only a completely posted thread advances time."""
    if state.get("last_cutoff") and report.instant(
        state["last_cutoff"]
    ) >= report.instant(cutoff):
        return
    # Completed cutoffs are guarded by last_cutoff; only the pending thread needs
    # receipts. Bound the state file instead of accumulating daily inventories.
    ledger = {
        key: receipt
        for key, receipt in state.setdefault("messages", {}).items()
        if key.startswith(cutoff + "/")
    }
    state["messages"] = ledger
    thread = None
    for name, text in messages:
        key = cutoff + "/" + name
        if key in ledger and "ts" not in ledger[key]:
            # A request may have reached Slack before the job died. Never blindly
            # resend an uncertain message, even if recovery lacks history scopes.
            recovered = slack.find(key)
            if not recovered:
                raise RuntimeError(
                    "Uncertain Slack delivery: inspect thread before clearing checkpoint intent"
                )
            ledger[key] = {"ts": recovered["ts"]}
            save(state)
        if key not in ledger:
            ledger[key] = {"intent": True}
            save(state)
            try:
                ts = slack.post(text, key, thread)
            except SlackRejected:
                del ledger[key]
                save(state)
                raise
            ledger[key] = {"ts": ts}
            save(state)
        if thread is None:
            thread = ledger[key]["ts"]
    state.pop("pending", None)
    state["last_cutoff"] = cutoff
    if canvas_invitation is not None:
        state["last_canvas_invitation"] = canvas_invitation
    save(state)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")


def read_ticket(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    pieces = text.split("---", 2)
    data = yaml.safe_load(pieces[1]) or {}
    return {"path": str(path), "metadata": data, "body": pieces[2]}


def prepare(config, mirror, out, state, now, cutoff=None):
    out.mkdir(parents=True, exist_ok=True)
    if state.get("pending"):
        pending = state["pending"]
        env = dict(os.environ, GH_TOKEN=os.environ["GITHUB_TOKEN"])
        subprocess.run(
            [
                "gh",
                "run",
                "download",
                pending["run_id"],
                "-R",
                os.environ["GITHUB_REPOSITORY"],
                "-n",
                "daily-learning-briefing",
                "-D",
                str(out),
            ],
            env=env,
            check=True,
            timeout=180,
            capture_output=True,
        )
        info = json.loads((out / "window.json").read_text())
        info["resume"] = True
        write_json(out / "window.json", info)
        return
    start, end = window(now, config["timezone"], config["hour"], config.get("weekdays"))
    if cutoff:
        end = report.instant(cutoff).astimezone(timezone.utc)
        start = (
            previous_cutoff(
                end.astimezone(ZoneInfo(config["timezone"])),
                config.get("weekdays", range(7)),
            )
        ).astimezone(timezone.utc)
    if state.get("last_cutoff"):
        previous = report.instant(state["last_cutoff"])
        if previous >= end:
            write_json(
                out / "window.json",
                {"already_posted": True, "end_exclusive": end.isoformat()},
            )
            return
        start = min(start, previous)
    history_start = min(start, end - timedelta(days=30))
    manifest = report.collect(
        config, history_start, end, out / "evidence", include_open=True, compact=True
    )
    if not manifest["complete"]:
        raise RuntimeError("Incomplete GitHub evidence; publication is blocked")
    tickets = set()
    inventory = []
    reading_index = []
    review_records = []
    records = out / "pr-records"
    records.mkdir(exist_ok=True)
    for source in manifest["repositories"]:
        rows = json.loads((out / "evidence" / source["file"]).read_text())
        for row in rows:
            review_records.append(row)
            merged = row.get("mergedAt")
            in_window = bool(merged and start <= report.instant(merged) < end)
            active = row["state"] == "OPEN"
            record_file = f"{row['repo'].replace('/', '--')}--{row['number']}.json"
            write_json(records / record_file, row)
            reading_index.append(
                {
                    "pr": f"{row['repo']}#{row['number']}",
                    "file": "pr-records/" + record_file,
                    "daily_merged": in_window,
                    "current_open": active,
                    "review_events": len(row.get("reviews", [])),
                    "inline_review_comments": len(row.get("review_comments", [])),
                }
            )
            if in_window or active:
                tickets.update(row["ticket_mentions"])
                entry = {
                    k: row.get(k)
                    for k in (
                        "repo",
                        "number",
                        "title",
                        "url",
                        "person",
                        "requested_reviewers",
                        "reviewDecision",
                        "headRefOid",
                        "baseRefName",
                        "mergedAt",
                        "waiting",
                    )
                }
                entry["state"] = (
                    "merged" if in_window else ("draft" if row["isDraft"] else "open")
                )
                inventory.append(entry)
    ticket_rows = []
    active_states = {
        "In Progress",
        "Code Review",
        "To QA",
        "Product Verification",
        "To Fix",
        "Blocked",
    }
    changed_paths = set(
        subprocess.check_output(
            [
                "git",
                "log",
                "--since=" + start.isoformat(),
                "--until=" + end.isoformat(),
                "--name-only",
                "--format=",
                "--",
                "linear/",
            ],
            cwd=mirror,
            text=True,
        ).splitlines()
    )
    scope_terms = re.compile(
        "|".join(re.escape(r.split("/")[-1]) for r in config["repos"]), re.I
    )
    for path in sorted((mirror / "linear" / "teams").glob("*/issues/*.md")):
        ticket = read_ticket(path)
        if ticket is None:
            continue
        meta = ticket["metadata"]
        changed = path.relative_to(mirror).as_posix() in changed_paths
        relevant = path.parent.parent.name in config.get("teams", []) or bool(
            scope_terms.search(ticket["body"])
        )
        if (
            meta.get("identifier") in tickets
            or (changed and relevant)
            or (
                path.parent.parent.name in config.get("teams", [])
                and meta.get("status") in active_states
            )
        ):
            ticket_rows.append(ticket)
    related_files = []
    terms = re.compile(
        "|".join(re.escape(r.split("/")[-1]) for r in config["repos"])
        + r"|backend|realtime|shopify|factcheck",
        re.I,
    )
    for folder in (mirror / "linear" / "projects", mirror / "linear" / "documents"):
        for path in sorted(folder.rglob("*.md")):
            ticket = read_ticket(path)
            if (
                ticket
                and "report" not in path.name
                and terms.search(path.read_text(encoding="utf-8"))
            ):
                changed = subprocess.run(
                    [
                        "git",
                        "log",
                        "-1",
                        "--since=" + history_start.isoformat(),
                        "--until=" + end.isoformat(),
                        "--format=%cI",
                        "--",
                        str(path),
                    ],
                    cwd=mirror,
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
                if changed:
                    related_files.append(ticket)
    ci = []
    for repo in config["repos"]:
        owner, name = repo.split("/")
        query = """query($owner:String!,$name:String!,$cursor:String) {
          repository(owner:$owner,name:$name) { defaultBranchRef { name target { ... on Commit {
            oid checkSuites(first:100,after:$cursor) {
              nodes { conclusion status workflowRun { databaseId url createdAt workflow { name } } }
              pageInfo { hasNextPage endCursor }
            }
          } } } }
        }"""
        latest, cursor, head = {}, None, None
        while True:
            args = [
                "api",
                "graphql",
                "-f",
                "query=" + query,
                "-f",
                "owner=" + owner,
                "-f",
                "name=" + name,
            ]
            if cursor:
                args += ["-f", "cursor=" + cursor]
            data = report.gh_json(*args)
            if data.get("errors"):
                raise RuntimeError(f"Incomplete default-branch CI for {repo}")
            branch = data["data"]["repository"]["defaultBranchRef"]
            target = branch["target"]
            if head and head != target["oid"]:
                raise RuntimeError(
                    f"Default branch changed during CI collection for {repo}; retry"
                )
            head = target["oid"]
            suites = target["checkSuites"]
            for suite in suites["nodes"]:
                run = suite.get("workflowRun")
                if run:
                    latest[run["databaseId"]] = {
                        "name": run["workflow"]["name"],
                        "head_sha": head,
                        "head_branch": branch["name"],
                        "created_at": run["createdAt"],
                        "status": suite["status"],
                        "conclusion": suite["conclusion"],
                        "html_url": run["url"],
                    }
            if not suites["pageInfo"]["hasNextPage"]:
                break
            cursor = suites["pageInfo"]["endCursor"]
        ci.append(
            {
                "repo": repo,
                "default_branch": branch["name"],
                "head_sha": head,
                "latest_head_runs": list(latest.values()),
            }
        )
    freshness = subprocess.check_output(
        ["git", "log", "-1", "--format=%H %cI"], cwd=mirror, text=True
    ).strip()
    write_json(
        out / "window.json",
        {
            "start": start.isoformat(),
            "end_exclusive": end.isoformat(),
            "history_start": history_start.isoformat(),
            "timezone": config["timezone"],
            "snapshot_as_of": now.isoformat(),
            "mirror_commit": freshness,
            "already_posted": False,
            "previous_canvas_invitation": state.get("last_canvas_invitation"),
        },
    )
    write_json(out / "inventory.json", inventory)
    write_json(out / "reading-index.json", reading_index)
    write_json(
        out / "review-learning-evidence.json", review_learning_evidence(review_records)
    )
    write_json(out / "tickets.json", ticket_rows)
    write_json(out / "context.json", related_files)
    write_json(out / "ci.json", ci)
    messages = out / "messages"
    messages.mkdir(exist_ok=True)
    lines = [f"Full inventory · {start.isoformat()} → {end.isoformat()} (exclusive)"]
    for section in ("merged", "open", "draft"):
        lines.append("\n" + section.upper())
        for row in inventory:
            if row["state"] == section:
                reviewers = (
                    ", ".join(row.get("requested_reviewers") or []) or "none requested"
                )
                lines.append(
                    f"• [{row['repo']}#{row['number']}]({row['url']}) {row['title']} — author: {row['person']}; requested reviewers: {reviewers}; review: {row.get('reviewDecision') or 'no decision'}"
                )
    lines.append("\nRELEVANT TICKETS (current mirror)")
    for ticket in ticket_rows:
        m = ticket["metadata"]
        lines.append(
            f"• [{m.get('identifier')}]({m.get('url')}) {m.get('title')} — {m.get('status')}; owner: {m.get('assignee') or 'unassigned'}"
        )
    lines.append(
        f"\nCoverage: {len(inventory)} PR inventory rows; {len(ticket_rows)} active/linked tickets. Mirror: {freshness}. PR/reviewer/CI states are current snapshots, not historical cutoff states. Review history starts {history_start.isoformat()}. Missing default-branch runs mean unavailable, not healthy. Generated reports excluded from synthesis."
    )
    chunks, chunk = [], ""
    for line in lines:
        if len(chunk) + len(line) > 2800:
            chunks.append(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        chunks.append(chunk)
    for i, text in enumerate(chunks, 2):
        (messages / f"{i:03d}-inventory.md").write_text(text, encoding="utf-8")
    # Stable names and manifest make retries independent of directory enumeration.
    write_json(
        out / "delivery.json",
        {
            "cutoff": end.isoformat(),
            "files": ["01-toplevel.md"]
            + [f"{i:03d}-inventory.md" for i in range(2, len(chunks) + 2)],
        },
    )
    configure_delivery(out, config)


def configure_delivery(out, config):
    """Opt into a full Canvas plus one TLDR; preserve the collected snapshot."""
    if config.get("delivery_format", "thread") != "canvas":
        return
    info = json.loads((out / "window.json").read_text())
    if info.get("already_posted"):
        return
    info["delivery_format"] = "canvas"
    if config.get("slack_summary_format") == "titles":
        info["slack_summary_format"] = "titles"
    if config.get("canvas_inventory") == "merged":
        info["canvas_inventory"] = "merged"
    write_json(out / "window.json", info)
    delivery = json.loads((out / "delivery.json").read_text())
    delivery["inventory_files"] = delivery.get("inventory_files", delivery["files"][1:])
    delivery["files"] = ["01-toplevel.md"]
    date = (
        report.instant(delivery["cutoff"]).astimezone(ZoneInfo(info["timezone"])).date()
    )
    delivery["canvas_title"] = f"Backend learning briefing — {date}"
    write_json(out / "delivery.json", delivery)
    top = out / "messages/01-toplevel.md"
    if top.exists() and not (out / "report.md").exists():
        (out / "report.md").write_text(
            top.read_text(encoding="utf-8"), encoding="utf-8"
        )


def delivery_digest(out, messages):
    info = json.loads((out / "window.json").read_text())
    content = messages
    if info.get("delivery_format") == "canvas":
        delivery = json.loads((out / "delivery.json").read_text())
        content = [
            messages,
            delivery["canvas_title"],
            (out / "canvas.md").read_text(encoding="utf-8"),
        ]
    return hashlib.sha256(json.dumps(content).encode()).hexdigest()


def publish_canvas(out, config, state, save, token):
    """Reuse the report Canvas publisher with receipts on the durable state branch."""
    delivery = json.loads((out / "delivery.json").read_text())
    cutoff = delivery["cutoff"]
    if state.get("canvas", {}).get("cutoff") != cutoff:
        state["canvas"] = {"cutoff": cutoff, "receipt": {}}
    path = out / "canvas-state.json"
    write_json(path, state["canvas"]["receipt"])

    def checkpoint(receipt):
        state["canvas"]["receipt"] = receipt
        save(state)

    return asyncio.run(
        slack_canvas.publish(
            (out / "canvas.md").read_text(encoding="utf-8"),
            delivery["canvas_title"],
            config["channel"],
            path,
            token,
            on_save=checkpoint,
        )
    )


def review_learning_evidence(records):
    """Keep review totals and usable dated comments separate from current snapshots."""
    evidence = {"review_events": 0, "inline_review_comments": 0, "comments": []}
    for row in records:
        for field, count in (
            ("reviews", "review_events"),
            ("review_comments", "inline_review_comments"),
        ):
            evidence[count] += len(row.get(field, []))
            for event in row.get(field, []):
                body = event.get("body")
                date = event.get("submitted_at") or event.get("created_at")
                if not (body and body.strip() and date and event.get("html_url")):
                    continue
                if event.get("body_available_at_cutoff") is False:
                    continue
                evidence["comments"].append(
                    {
                        "pr": f"{row['repo']}#{row['number']}",
                        "url": event["html_url"],
                        "reviewer": (event.get("user") or {}).get("login", "unknown"),
                        "date": date,
                        "body": body,
                    }
                )
    return evidence


def validate_review_learning(evidence, audit, top):
    """A claimed review pattern needs genuine comments from independent PRs."""

    def reject(detail):
        raise RuntimeError("Review learning audit: " + detail)

    for key in ("review_events", "inline_review_comments"):
        if audit.get(key) != evidence[key]:
            reject("review totals disagree with collected evidence")
    available = {(r["pr"], r["url"]) for r in evidence["comments"]}
    prs = {pr for pr, _ in available}
    inspected = set(audit.get("inspected_prs", []))
    if not inspected <= prs or len(inspected) < min(2, len(prs)):
        reject("inspect dated comments from independent PRs")
    patterns = audit.get("patterns")
    if not isinstance(patterns, list):
        reject("patterns must be an array")
    for pattern in patterns:
        citations = pattern.get("evidence", [])
        keys = {(r.get("pr"), r.get("url")) for r in citations}
        if not keys <= available or len({pr for pr, _ in keys}) < 2:
            reject("patterns need real comment URLs from at least two PRs")
        if not {pr for pr, _ in keys} <= inspected:
            reject("pattern sources must have been inspected")
        if (
            not pattern.get("summary", "").strip()
            or not pattern.get("shared_solution", "").strip()
        ):
            reject("explain the repeated problem and shared solution")
        if "What to fix once" not in top or any(url not in top for _, url in keys):
            reject("the briefing must cite its review pattern evidence")
    if not patterns and not audit.get("no_pattern_reason", "").strip():
        reject("explain why no recurring problem is supported")
    if evidence["comments"] and re.search(
        r"no review (?:comments|evidence|reviews) (?:were |was |is )?(?:present|available|found)",
        top,
        re.I,
    ):
        reject("collected review evidence cannot be described as absent")
    if re.search(r"\ball[- ]green\b", top, re.I):
        raise RuntimeError("CI claims must name the observed checks and statuses")


def validate_coverage(inventory, audit):
    expected = {f"{row['repo']}#{row['number']}" for row in inventory}
    seen = [row.get("pr") for row in audit]
    if (
        len(seen) != len(set(seen))
        or set(seen) != expected
        or any(
            row.get("placement") not in {"story", "queue", "inventory"}
            or not str(row.get("reason", "")).strip()
            for row in audit
        )
    ):
        raise RuntimeError("PR coverage audit must explain each inventory entry once")


def canvas_title_summary(content, title, invitation, previous=None):
    """Use the narrative's own headings; appendix inventories are added later."""
    invitation = invitation.strip()

    def normalized(text):
        return " ".join((text or "").split()).casefold()

    if not invitation or "\n" in invitation or len(invitation.split()) > 25:
        raise RuntimeError("Canvas invitation must be one short line, at most 25 words")
    if re.search(r"[\[\]<>]|https?://", invitation):
        raise RuntimeError(
            "Canvas invitation must be plain text without an invented link"
        )
    if normalized(invitation) == normalized(previous):
        raise RuntimeError("Canvas invitation must differ from the previous briefing")
    headings, fence = [], None
    for line in content.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        heading = re.match(r"^\s{0,3}(#{2,6})\s+(.+?)(?:\s+#+\s*)?$", line)
        if heading:
            headings.append((len(heading[1]), heading[2].strip()))
    topics = []
    for index, (level, text) in enumerate(headings):
        # These two labels group effort/lesson titles; include them on quiet days
        # only when there are no child topics. Other headings remain visible.
        has_children = index + 1 < len(headings) and headings[index + 1][0] > level
        if text.casefold() in {"what changed", "learning"} and has_children:
            continue
        topics.append(text)
    if not topics:
        raise RuntimeError("Canvas title summary needs narrative topic headings")
    return (
        f"**{title}**\n\n"
        + "\n".join("- " + topic for topic in topics)
        + "\n\n"
        + invitation
    )


def canvas_message_link(text, url, *, titles=False):
    if titles:
        body, _, invitation = text.rpartition("\n")
        return body + f"\n[{invitation}]({url})"
    return text + f"\n[Full report in Slack Canvas]({url})"


def validate_output(out):
    info = json.loads((out / "window.json").read_text())
    if info.get("already_posted"):
        return []
    delivery = json.loads((out / "delivery.json").read_text())
    title_summary = (
        info.get("delivery_format") == "canvas"
        and info.get("slack_summary_format") == "titles"
    )
    if title_summary:
        text = canvas_title_summary(
            (out / "report.md").read_text(encoding="utf-8"),
            delivery["canvas_title"],
            (out / "canvas-invitation.md").read_text(encoding="utf-8"),
            info.get("previous_canvas_invitation"),
        )
        (out / "messages/01-toplevel.md").write_text(text + "\n", encoding="utf-8")
    messages = [
        (name, (out / "messages" / name).read_text(encoding="utf-8").strip())
        for name in delivery["files"]
    ]
    if any(not text or len(text) > 15000 for _, text in messages):
        raise RuntimeError("Missing, empty or oversized briefing message")
    inventory = json.loads((out / "inventory.json").read_text())
    canvas_mode = info.get("delivery_format") == "canvas"
    if not title_summary and len(messages[0][1].split()) > (
        180 if canvas_mode else 550
    ):
        raise RuntimeError(
            "TLDR exceeds 180 words"
            if canvas_mode
            else "Top-level briefing exceeds 550 words"
        )
    inventory_text = "\n".join(
        (out / "messages" / name).read_text(encoding="utf-8")
        for name in delivery.get("inventory_files", delivery["files"][1:])
    )
    if any(f"{row['repo']}#{row['number']}" not in inventory_text for row in inventory):
        raise RuntimeError("Inventory coverage is incomplete")
    validate_coverage(inventory, json.loads((out / "coverage.json").read_text()))
    if not (out / "coverage.md").read_text().strip():
        raise RuntimeError("Missing coverage explanation")
    validate_review_learning(
        json.loads((out / "review-learning-evidence.json").read_text()),
        json.loads((out / "review-learning.json").read_text()),
        (out / "report.md").read_text(encoding="utf-8")
        if canvas_mode
        else messages[0][1],
    )
    if canvas_mode:
        content = (out / "report.md").read_text(encoding="utf-8").strip()
        if not content:
            raise RuntimeError("Missing full Canvas report")
        if info.get("canvas_inventory") == "merged":
            # Curate the reader's queue while retaining every source in artifacts.
            cited_urls = set(
                re.findall(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+", content)
            )
            linked_open = [
                row
                for row in inventory
                if row.get("state") in {"open", "draft"} and row["url"] in cited_urls
            ]
            if len(linked_open) > 8:
                raise RuntimeError("Curated report must cite at most 8 open/draft PRs")
            merged = [row for row in inventory if row.get("state") == "merged"]
            content += "\n\n## Merged PRs in this window\n\n"
            content += (
                "\n".join(
                    f"- [{row['repo']}#{row['number']}]({row['url']}) {row['title']} — author: {row['person']}"
                    for row in merged
                )
                or "No PRs merged in this window."
            )
            content += (
                "\n\nFull open/draft PR and ticket inventories are retained in the "
                "run's evidence artifact. The report highlights the work and review "
                "decisions worth acting on."
            )
        else:
            canvas_inventory = re.sub(r"(?m)^• ", "- ", inventory_text)
            for section, label in (
                ("MERGED", "Merged PRs"),
                ("OPEN", "Open PRs"),
                ("DRAFT", "Draft PRs"),
                (
                    "RELEVANT TICKETS (current mirror)",
                    "Relevant tickets (current mirror)",
                ),
            ):
                canvas_inventory = re.sub(
                    r"(?m)^" + re.escape(section) + r"$",
                    "### " + label + "\n",
                    canvas_inventory,
                )
            content += "\n\n## Complete PR and ticket inventory\n\n" + canvas_inventory
        slack_canvas.validate_content(content)
        (out / "canvas.md").write_text(content, encoding="utf-8")
    return messages


def generate(out, prompt, revision_notes=""):
    """Generate once, then allow at most two revisions using the same evidence."""
    info = json.loads((out / "window.json").read_text())
    if info.get("already_posted") or info.get("resume"):
        return
    instructions = prompt.read_text()
    if revision_notes:
        instructions += (
            "\n\nRequired operator revision instructions:\n"
            + revision_notes
            + "\nRevise report.md and the Slack invitation/message using these instructions. "
            "Keep prepared evidence and inventories unchanged; reconcile audits."
        )
    protected = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in list(out.rglob("*.json"))
        + list((out / "messages").glob("*-inventory.md"))
        if p not in {out / "coverage.json", out / "review-learning.json"}
    }

    def run_model(text, log_name):
        with (out / log_name).open("w") as log:
            subprocess.run(
                [
                    "claude",
                    "-p",
                    text,
                    "--dangerously-skip-permissions",
                    "--model",
                    "claude-sonnet-5-5",
                    "--output-format",
                    "text",
                ],
                stdout=log,
                check=True,
            )
        if any(
            not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != digest
            for p, digest in protected.items()
        ):
            raise RuntimeError("Prepared evidence changed during generation")

    if revision_notes or not (out / "messages/01-toplevel.md").exists():
        run_model(instructions, "generation.log")
    for attempt in range(3):
        try:
            validate_output(out)
            return
        except (
            RuntimeError,
            OSError,
            ValueError,
            slack_canvas.click.ClickException,
        ) as error:
            if attempt == 2:
                raise
            repair = (
                instructions + "\n\nRevise the EXISTING generated draft and audits. "
                "Keep the prepared evidence and inventory messages unchanged. "
                "Do not recollect sources or regenerate the per-PR ledger from scratch. "
                + (
                    "Write a fresh canvas-invitation.md line, at most 25 words; title bullets are assembled automatically. "
                    if info.get("slack_summary_format") == "titles"
                    else "Use Python to count TLDR words; target 100-160 and stay below 180. "
                    if info.get("delivery_format") == "canvas"
                    else "Use Python to count words; target 400-450 and stay below 550. "
                )
                + (
                    "Write the full report in report.md without a word limit. "
                    if info.get("delivery_format") == "canvas"
                    else ""
                )
                + "Remove author PR totals, jargon and unneeded measurements. "
                "Verify denominators and environments for every retained number. "
                "Resolve reviewer names through the caller's verified people mapping. "
                "For query-plan lessons require bounded buffers/rows inspected, "
                "not merely an Index Scan label. "
                "Preserve real review-pattern citations and reconcile the audits. "
                f"Validation failure: {error}"
            )
            (out / f"revision-{attempt + 1}.txt").write_text(str(error))
            run_model(repair, f"revision-{attempt + 1}.log")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["prepare", "generate", "validate", "publish"]
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--mirror", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cutoff")
    parser.add_argument("--prompt", type=Path)
    parser.add_argument("--evidence-run-id")
    parser.add_argument("--revision-notes", default="")
    parser.add_argument(
        "--isolated",
        action="store_true",
        help="Preview only; ignore delivery checkpoint",
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.command == "generate":
        if args.prompt is None:
            parser.error("generate requires --prompt")
        generate(args.out, args.prompt, args.revision_notes)
        return
    if args.evidence_run_id:
        if args.command != "prepare" or not args.isolated:
            parser.error("evidence reuse is available only to isolated previews")
        args.out.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "gh",
                "run",
                "download",
                args.evidence_run_id,
                "-R",
                os.environ["GITHUB_REPOSITORY"],
                "-n",
                "daily-learning-briefing",
                "-D",
                str(args.out),
            ],
            env=dict(os.environ, GH_TOKEN=os.environ["GITHUB_TOKEN"]),
            check=True,
            timeout=180,
            capture_output=True,
        )
        info = json.loads((args.out / "window.json").read_text())
        info.pop("resume", None)
        write_json(args.out / "window.json", info)
        configure_delivery(args.out, config)
        return
    store = StateStore(
        os.environ.get("GITHUB_REPOSITORY", config.get("mirror_repository", "")),
        config.get("state_branch", "briefing-state"),
        config["channel"],
    )
    state = {"messages": {}} if args.isolated else store.read()
    if args.command == "prepare":
        prepare(
            config,
            args.mirror.resolve(),
            args.out,
            state,
            datetime.now(timezone.utc),
            args.cutoff,
        )
        return
    messages = validate_output(args.out)
    if not messages:
        return
    delivery = json.loads((args.out / "delivery.json").read_text())
    if args.command == "publish":
        if state.get("last_cutoff") and report.instant(
            state["last_cutoff"]
        ) >= report.instant(delivery["cutoff"]):
            return
        if args.isolated:
            parser.error("isolated previews cannot publish")
        digest = delivery_digest(args.out, messages)
        if state.get("pending") and state["pending"]["digest"] != digest:
            raise RuntimeError(
                "Prepared messages differ from the partially posted thread"
            )
        if not state.get("pending"):
            state["pending"] = {
                "run_id": os.environ["GITHUB_RUN_ID"],
                "digest": digest,
                "cutoff": delivery["cutoff"],
            }
            store.save(state)
        info = json.loads((args.out / "window.json").read_text())
        if info.get("delivery_format") == "canvas":
            url = publish_canvas(
                args.out, config, state, store.save, os.environ["SLACK_BOT_TOKEN"]
            )
            messages = [
                (
                    name,
                    canvas_message_link(
                        text, url, titles=info.get("slack_summary_format") == "titles"
                    ),
                )
                for name, text in messages
            ]
        slack = Slack(config["channel"], os.environ["SLACK_BOT_TOKEN"])
        invitation = (
            (args.out / "canvas-invitation.md").read_text().strip()
            if info.get("slack_summary_format") == "titles"
            else None
        )
        publish(
            messages,
            state,
            delivery["cutoff"],
            slack,
            store.save,
            canvas_invitation=invitation,
        )


if __name__ == "__main__":
    main()
