"""Exercise the real Linear HTTP client, not mocked pagination internals."""

import json

import httpx
import pytest

from issueclaw.linear_client import LinearClient


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "graphql", "cursor"])
async def test_issue_snapshot_never_silently_truncates_comments(failure):
    def respond(request):
        body = json.loads(request.content)
        after = body["variables"].get("after")
        if "IssueComments" not in body["query"]:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "issue": {
                            "id": "issue",
                            "comments": {
                                "nodes": [{"id": "first"}],
                                "pageInfo": {"hasNextPage": True, "endCursor": "next"},
                            },
                        }
                    }
                },
            )
        if failure == "graphql":
            return httpx.Response(
                200, json={"data": {"issue": None}, "errors": [{"message": "denied"}]}
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "issue": {
                        "comments": {
                            "nodes": [{"id": "last" if after else "first"}],
                            "pageInfo": {
                                "hasNextPage": failure == "cursor",
                                "endCursor": after,
                            },
                        }
                    }
                }
            },
        )

    client = LinearClient("fake")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    async with client:
        if failure:
            with pytest.raises(ValueError):
                await client.fetch_issue("issue")
        else:
            issue = await client.fetch_issue("issue")
            assert [c["id"] for c in issue["comments"]["nodes"]] == ["first", "last"]
