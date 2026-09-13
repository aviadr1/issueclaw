"""Exercise production discovery against the HTTP boundary, not mocked query helpers."""

import json
from unittest.mock import patch
from datetime import datetime, timezone

import httpx
import pytest

from issueclaw.inbox_reconcile import discover, run_reconciliation
from issueclaw.linear_client import LinearClient

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_filtered_metadata_all_six_sources(changed):
    queries = []

    def handle(request):
        body = json.loads(request.content)
        query = body["query"]
        queries.append(body)
        if "organization {" in query:
            return httpx.Response(200, json={"data": {"organization": {"id": "org"}}})
        source = next(
            s
            for s in (
                "issues",
                "comments",
                "projects",
                "documents",
                "initiatives",
                "projectUpdates",
            )
            if s + "(" in query
        )
        assert "includeArchived: true" in query
        assert "orderBy: updatedAt" in query
        assert "gte: $since" in query and "lte: $until" in query
        assert not any(field in query for field in ("description", "body", "title"))
        nodes = (
            [
                {
                    "id": source,
                    "updatedAt": "2026-09-12T12:00:00Z",
                    "issue": {"id": "parent"},
                    "project": {"id": "parent"},
                }
            ]
            if changed
            else []
        )
        return httpx.Response(
            200,
            json={
                "data": {source: {"nodes": nodes, "pageInfo": {"hasNextPage": False}}}
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
        linear = LinearClient("unused")
        linear._client = transport
        records = await discover(linear, "org", "2026-09-12T00:00:00Z", NOW.isoformat())
    assert len(queries) == 7
    assert len(records) == (6 if changed else 0)
    if changed:
        by_type = {r["type"]: r for r in records}
        assert by_type["Comment"]["data"]["issueId"] == "parent"
        assert by_type["ProjectUpdate"]["data"]["projectId"] == "parent"


class Inbox:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def post(self, path, body=None):
        self.calls.append((path, body))
        if path == "status":
            return {
                "organization_id": "org",
                "stream": "stream",
                "reconciliation_at": 0,
                "pending": 0,
            }
        if path == "reconcile" and self.fail:
            raise RuntimeError("upload failed")
        return {}


@pytest.mark.asyncio
async def test_missing_bootstrap_fails_without_advancing():
    inbox = Inbox()
    with pytest.raises(ValueError, match="bootstrap"):
        await run_reconciliation(inbox, "unused", bootstrap_since=None, now=NOW)
    assert [p for p, _ in inbox.calls] == ["status"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "count,fail_at",
    [(0, None), (26, None), (26, "upload"), (26, "page"), (26, "identity")],
)
async def test_discovery_publication_boundary(count, fail_at):
    inbox = Inbox(fail=fail_at == "upload")

    def handle(request):
        body = json.loads(request.content)
        query = body["query"]
        if "organization {" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "organization": {
                            "id": "wrong" if fail_at == "identity" else "org"
                        }
                    }
                },
            )
        root = next(
            s
            for s in (
                "issues",
                "comments",
                "projects",
                "documents",
                "initiatives",
                "projectUpdates",
            )
            if s + "(" in query
        )
        if fail_at == "page" and root == "documents":
            return httpx.Response(200, json={"errors": [{"message": "denied"}]})
        nodes = (
            [{"id": str(i), "updatedAt": "2026-09-12T12:00:00Z"} for i in range(count)]
            if root == "issues"
            else []
        )
        return httpx.Response(
            200,
            json={"data": {root: {"nodes": nodes, "pageInfo": {"hasNextPage": False}}}},
        )

    # Substitute only the external HTTP transport. Production client creation,
    # query execution, pagination, discovery and upload ordering remain real.
    with patch.object(
        httpx.AsyncClient,
        "_transport_for_url",
        return_value=httpx.MockTransport(handle),
    ):
        if fail_at:
            with pytest.raises((ValueError, RuntimeError, ExceptionGroup)):
                await run_reconciliation(
                    inbox, "unused", bootstrap_since="2026-09-12T00:00:00Z", now=NOW
                )
        else:
            result = await run_reconciliation(
                inbox, "unused", bootstrap_since="2026-09-12T00:00:00Z", now=NOW
            )
            assert result == {"discovered": count, "pending": 0}
    paths = [p for p, _ in inbox.calls]
    assert ("reconcile-complete" in paths) == (fail_at is None)
    if not fail_at:
        uploads = [b for p, b in inbox.calls if p == "reconcile"]
        assert [len(b["records"]) for b in uploads] == ([25, 1] if count else [])
        assert paths[-2:] == ["reconcile-complete", "status"]


@pytest.mark.asyncio
async def test_metadata_pagination_can_cross_previous_100_page_limit():
    def handle(request):
        body = json.loads(request.content)
        page = int(body["variables"].get("after") or 0)
        return httpx.Response(
            200,
            json={
                "data": {
                    "issues": {
                        "nodes": [{"id": str(page)}],
                        "pageInfo": {
                            "hasNextPage": page < 100,
                            "endCursor": str(page + 1),
                        },
                    }
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
        linear = LinearClient("unused")
        linear._client = transport
        assert len(await linear._paginate("query", ["issues"], max_pages=1000)) == 101
