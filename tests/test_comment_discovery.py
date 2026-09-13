"""Real discovery must route polymorphic Linear comments, not skip them."""

import json
import httpx
import pytest
from issueclaw.inbox_reconcile import discover
from issueclaw.linear_client import LinearClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "owner,field",
    [
        ({"issue": {"id": "owner"}}, "issueId"),
        ({"initiative": {"id": "owner"}}, "initiativeId"),
        ({"project": {"id": "owner"}}, "projectId"),
        ({"documentContent": {"document": {"id": "owner"}}}, "documentId"),
        ({"documentContent": {"issue": {"id": "owner"}}}, "issueId"),
        ({"documentContent": {"initiative": {"id": "owner"}}}, "initiativeId"),
        ({"projectUpdate": {"project": {"id": "owner"}}}, "projectId"),
        ({"initiativeUpdate": {"initiative": {"id": "owner"}}}, "initiativeId"),
    ],
)
async def test_comment_owner_is_preserved_through_discovery(owner, field):
    def handle(request):
        query = json.loads(request.content)["query"]
        if "organization {" in query:
            return httpx.Response(200, json={"data": {"organization": {"id": "org"}}})
        root = next(
            k
            for k in [
                "issues",
                "comments",
                "projects",
                "documents",
                "initiatives",
                "projectUpdates",
            ]
            if k + "(" in query
        )
        nodes = (
            [{"id": "comment", "updatedAt": "2026-09-13T12:00:00Z", **owner}]
            if root == "comments"
            else []
        )
        return httpx.Response(
            200,
            json={"data": {root: {"nodes": nodes, "pageInfo": {"hasNextPage": False}}}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = LinearClient("unused")
        client._client = http
        records = await discover(
            client, "org", "2026-09-13T00:00:00Z", "2026-09-14T00:00:00Z"
        )
    assert len(records) == 1
    assert records[0]["type"] == "Comment"
    assert records[0]["data"]["id"] == "comment"
    assert records[0]["data"][field] == "owner"
