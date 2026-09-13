"""Project links must resolve to independently owned, fully fetched updates."""

import json
import re
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from issueclaw.commands import apply_webhook as webhook
from issueclaw.entity_changes import apply_changes, prepare_entity
from issueclaw.linear_client import LinearClient
from issueclaw.sync_state import SyncState
from tests.test_apply_webhook import _make_project_api_response


@pytest.fixture
def project_response():
    raw = _make_project_api_response()
    raw["projectUpdates"]["nodes"] = [
        {
            "id": f"update-{i}",
            "body": f"progress {i}",
            "createdAt": "2026-09-13T00:00:00Z",
            "user": {"name": "same author"},
        }
        for i in range(2)
    ]
    return raw


@pytest.mark.asyncio
@pytest.mark.parametrize("isolated", [False, True])
async def test_project_refresh_writes_distinct_update_bodies_and_moves_them(
    tmp_path, isolated, project_response
):
    raw = project_response
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.fetch_project.return_value = raw
    payload = {"type": "Project", "action": "update", "data": {"id": raw["id"]}}
    with patch.object(webhook, "LinearClient", return_value=client):
        for name in ["First name", "Renamed project"]:
            raw["name"] = name
            if isolated:
                apply_changes(
                    tmp_path, await prepare_entity(payload, "unused", tmp_path)
                )
            else:
                await webhook.apply_webhook(payload, "unused", tmp_path)
            pages = list(tmp_path.glob("linear/projects/*/_project.md"))
            assert len(pages) == 1
            refs = re.findall(r"\]\((updates/[^)]+)\)", pages[0].read_text())
            assert len(set(refs)) == 2
            for i, ref in enumerate(refs):
                assert f"progress {i}" in (pages[0].parent / ref).read_text()
            assert len(list(tmp_path.glob("linear/projects/*/updates/*.md"))) == 2
            mapping = json.loads((tmp_path / ".sync/id-map.json").read_text())
            assert set(mapping.values()) == {raw["id"], "update-0", "update-1"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "conflict", ["foreign", "unmapped", "divergent", "outside_alias"]
)
async def test_child_conflicts_never_escape_isolated_preparation(
    tmp_path, project_response, conflict
):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.fetch_project.return_value = project_response
    payload = {
        "type": "Project",
        "action": "update",
        "data": {"id": project_response["id"]},
    }
    with patch.object(webhook, "LinearClient", return_value=client):
        apply_changes(tmp_path, await prepare_entity(payload, "unused", tmp_path))
        state = SyncState(tmp_path)
        state.load()
        target = state.get_path("update-0")
        assert target
        if conflict in {"foreign", "unmapped"}:
            state.remove_mapping(target)
            if conflict == "foreign":
                state.add_mapping(target, "foreign-owner")
        else:
            alias = (
                "linear/projects/legacy/updates/conflict.md"
                if conflict == "outside_alias"
                else target + ".old.md"
            )
            (tmp_path / alias).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / alias).write_text("unpublished content")
            state.add_mapping(alias, "update-0")
        state.save()
        before = {
            str(p.relative_to(tmp_path)): p.read_bytes()
            for p in tmp_path.rglob("*")
            if p.is_file()
        }
        with pytest.raises(ValueError):
            await prepare_entity(payload, "unused", tmp_path)
        assert before == {
            str(p.relative_to(tmp_path)): p.read_bytes()
            for p in tmp_path.rglob("*")
            if p.is_file()
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("broken_page", [False, True])
async def test_project_update_pagination_is_complete_or_fails_closed(bulk, broken_page):
    first = {
        "nodes": [{"id": f"u-{i}"} for i in range(10)],
        "pageInfo": {"hasNextPage": True, "endCursor": "next"},
    }

    def handle(request):
        body = json.loads(request.content)
        if body.get("variables", {}).get("after") == "next":
            if broken_page:
                return httpx.Response(
                    200, json={"errors": [{"message": "unavailable"}]}
                )
            return httpx.Response(
                200,
                json={
                    "data": {
                        "project": {
                            "projectUpdates": {
                                "nodes": [{"id": "last"}],
                                "pageInfo": {"hasNextPage": False},
                            }
                        }
                    }
                },
            )
        raw = {"id": "project", "projectUpdates": first}
        return httpx.Response(
            200,
            json={
                "data": {
                    "projects": {"nodes": [raw], "pageInfo": {"hasNextPage": False}}
                }
                if bulk
                else {"project": raw}
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as transport:
        client = LinearClient("unused")
        client._client = transport

        async def fetch():
            return (
                (await client.fetch_projects())[0]
                if bulk
                else await client.fetch_project("project")
            )

        if broken_page:
            with pytest.raises(ValueError):
                await fetch()
        else:
            result = await fetch()
            assert [u["id"] for u in result["projectUpdates"]["nodes"]] == [
                *[f"u-{i}" for i in range(10)],
                "last",
            ]
