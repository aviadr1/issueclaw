"""Daily incremental metadata discovery; the durable inbox owns replay retries."""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

from issueclaw.inbox_replay import InboxClient
from issueclaw.linear_client import LinearClient

# Children must be queried independently: editing a comment need not touch its
# parent's updatedAt. Full content is fetched only by the existing replay SUT.
SOURCES = (
    ("issues", "Issue", None),
    ("comments", "Comment", "issue"),
    ("projects", "Project", None),
    ("documents", "Document", None),
    ("initiatives", "Initiative", None),
    ("projectUpdates", "ProjectUpdate", "project"),
)
OVERLAP = timedelta(minutes=5)


def comment_owner(node: dict) -> tuple[str, str]:
    # Comment is polymorphic. Resolve the owning mirrored entity while retaining
    # the comment's own identity/version for durable deduplication.
    candidates = [
        node,
        node.get("documentContent") or {},
        node.get("projectUpdate") or {},
        node.get("initiativeUpdate") or {},
    ]
    for candidate in candidates:
        for kind in ("issue", "project", "initiative", "document"):
            owner = candidate.get(kind) or {}
            if isinstance(owner.get("id"), str) and owner["id"]:
                return kind + "Id", owner["id"]
    raise ValueError("Unresolved Comment owner; checkpoint not advanced")


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Reconciliation timestamp must include timezone")
    return result.astimezone(timezone.utc)


async def discover(
    client: LinearClient, organization: str, since: str, until: str
) -> list[dict]:
    identity = await client._graphql("query { organization { id } }")
    if identity["data"].get("organization", {}).get("id") != organization:
        raise ValueError("Linear and inbox organizations differ")

    async def source(root: str, kind: str, parent: str | None) -> list[dict]:
        relationship = parent + " { id }" if parent else ""
        if kind == "Comment":
            relationship = """issue { id } project { id } initiative { id }
              documentContent { issue { id } project { id } initiative { id } document { id } }
              projectUpdate { project { id } } initiativeUpdate { initiative { id } }"""
        query = f"""query Changed($since: DateTimeOrDuration!, $until: DateTimeOrDuration!, $after: String) {{
          {root}(first: 100, after: $after, includeArchived: true, orderBy: updatedAt,
            filter: {{ updatedAt: {{ gte: $since, lte: $until }} }}) {{
            nodes {{ id updatedAt {relationship} }}
            pageInfo {{ hasNextPage endCursor }}
          }}
        }}"""
        nodes = await client._paginate(
            query, [root], {"since": since, "until": until}, max_pages=1000
        )
        records = []
        for node in nodes:
            if (
                not isinstance(node, dict)
                or not isinstance(node.get("id"), str)
                or not node["id"]
            ):
                raise ValueError("Invalid metadata identity")
            updated = timestamp(node["updatedAt"])
            if not timestamp(since) <= updated <= timestamp(until):
                raise ValueError("Linear returned metadata outside requested window")
            data = {"id": node["id"], "updatedAt": updated.isoformat()}
            if kind == "Comment":
                field, owner_id = comment_owner(node)
                data[field] = owner_id
            elif parent:
                parent_id = (node.get(parent) or {}).get("id")
                if not isinstance(parent_id, str) or not parent_id:
                    raise ValueError(
                        f"Unsupported {kind} parent; checkpoint not advanced"
                    )
                data[parent + "Id"] = parent_id
            records.append(
                {
                    "organizationId": organization,
                    "type": kind,
                    "action": "update",
                    "data": data,
                    "createdAt": updated.isoformat(),
                }
            )
        return records

    # TaskGroup joins/cancels siblings before the owning HTTP client is closed.
    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(source(*spec)) for spec in SOURCES]
    return [record for task in tasks for record in task.result()]


async def run_reconciliation(
    inbox,
    api_key: str,
    *,
    bootstrap_since: str | None,
    now: datetime | None = None,
    expected_stream: str | None = None,
) -> dict:
    status = inbox.post("status")
    if expected_stream and status["stream"] != expected_stream:
        raise ValueError("Inbox stream changed; explicit bootstrap required")
    cursor = status["reconciliation_at"]
    if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0:
        raise ValueError("Invalid reconciliation cursor")
    if not cursor and not bootstrap_since:
        raise ValueError("First reconciliation requires a trusted bootstrap timestamp")
    start = (
        datetime.fromtimestamp(cursor / 1000, timezone.utc)
        if cursor
        else timestamp(bootstrap_since or "")
    )
    until = now or datetime.now(timezone.utc)
    if start >= until:
        raise ValueError("Reconciliation cursor must precede scan start")
    since = max(datetime(1970, 1, 1, tzinfo=timezone.utc), start - OVERLAP)
    async with LinearClient(api_key) as client:
        records = await discover(
            client, status["organization_id"], since.isoformat(), until.isoformat()
        )
    # Imports are restart-safe and do not ACK processing. Never advance past a
    # failed page or failed upload. All six connections validated before writes.
    for offset in range(0, len(records), 25):
        inbox.post(
            "reconcile",
            {
                "organizationId": status["organization_id"],
                "records": records[offset : offset + 25],
            },
        )
    inbox.post(
        "reconcile-complete",
        {"expected": cursor, "until": int(until.timestamp() * 1000)},
    )
    return {"discovered": len(records), "pending": inbox.post("status")["pending"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", type=Path, default=Path("."))
    parser.add_argument(
        "--bootstrap-since", help="Trusted last successful sync; never defaults to now"
    )
    args = parser.parse_args()
    state = args.repo_dir / ".sync/state.json"
    bootstrap = args.bootstrap_since
    if not bootstrap and state.exists():
        bootstrap = json.loads(state.read_text()).get("last_sync")
    checkpoint = args.repo_dir / ".sync/inbox-checkpoint.json"
    stream = (
        json.loads(checkpoint.read_text())["stream"] if checkpoint.exists() else None
    )
    inbox = InboxClient(os.environ["INBOX_URL"], os.environ["INBOX_TOKEN"])
    try:
        result = asyncio.run(
            run_reconciliation(
                inbox,
                os.environ["LINEAR_API_KEY"],
                bootstrap_since=bootstrap,
                expected_stream=stream,
            )
        )
    except Exception as error:
        # HTTP exceptions can contain source data; CI needs only the failure type.
        raise SystemExit(
            f"Reconciliation failed ({type(error).__name__}); checkpoint not advanced unless all imports completed"
        ) from None
    print(json.dumps(result))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as handle:
            handle.write(f"pending={'true' if result['pending'] else 'false'}\n")


if __name__ == "__main__":
    main()
