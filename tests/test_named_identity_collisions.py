"""Names are not unique IDs: exercise every named-entity writer."""

from unittest.mock import AsyncMock, patch

import pytest

from issueclaw.commands import apply_webhook as webhook
from issueclaw.commands import create, pull
from issueclaw.entity_changes import apply_changes, prepare_entity
from issueclaw.sync_state import SyncState
from tests.test_apply_webhook import (
    _make_document_api_response,
    _make_initiative_api_response,
)


async def refresh(repo, kind, entry, identity, title):
    raw = (
        _make_document_api_response()
        if kind == "Document"
        else _make_initiative_api_response()
    )
    raw.update(id=identity, title=title, name=title)
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.fetch_teams.return_value = [{"id": "team", "key": "AI"}]
    client.fetch_issues.return_value = []
    client.fetch_projects.return_value = []
    client.fetch_documents.return_value = [raw] if kind == "Document" else []
    client.fetch_initiatives.return_value = [raw] if kind == "Initiative" else []
    client.fetch_document.return_value = raw
    client.fetch_initiative.return_value = raw
    client.create_document.return_value = raw
    client.create_initiative.return_value = raw
    payload = {"type": kind, "action": "update", "data": {"id": identity}}
    with (
        patch.object(webhook, "LinearClient", return_value=client),
        patch.object(pull, "LinearClient", return_value=client),
        patch.object(create, "LinearClient", return_value=client),
    ):
        if entry == "replay":
            apply_changes(repo, await prepare_entity(payload, "unused", repo))
        elif entry == "webhook":
            await webhook.apply_webhook(payload, "unused", repo)
        elif entry == "pull":
            await pull._run_pull(
                "unused", repo, None, show_progress=False, log=lambda _: None
            )
        elif kind == "Document":
            await create._create_document("unused", repo, title, "body", None, "AI")
        else:
            await create._create_initiative(
                "unused", repo, title, "body", None, None, None
            )


@pytest.mark.parametrize("kind", ["Document", "Initiative"])
@pytest.mark.parametrize("entry", ["webhook", "replay", "pull", "create"])
@pytest.mark.parametrize("second_title", ["Shared name", "Shared_name!"])
@pytest.mark.asyncio
async def test_distinct_named_identities_coexist_and_retry_stably(
    tmp_path, kind, entry, second_title
):
    await refresh(tmp_path, kind, entry, "first-id", "Shared name")
    state = SyncState(tmp_path)
    state.load()
    first_path = state.get_path("first-id")
    assert first_path is not None
    original = (tmp_path / first_path).read_bytes()
    await refresh(tmp_path, kind, entry, "second-id", second_title)
    state.load()
    second_path = state.get_path("second-id")
    assert second_path is not None
    assert second_path != first_path
    assert "second-id" in second_path
    assert (tmp_path / first_path).read_bytes() == original
    assert "second-id" in (tmp_path / second_path).read_text()
    state.remove_entity("first-id")
    state.save()
    await refresh(tmp_path, kind, entry, "second-id", second_title)
    state.load()
    assert state.get_paths("second-id") == [second_path]
    assert not (tmp_path / first_path).exists()


@pytest.mark.parametrize("entry", ["webhook", "replay", "pull", "create"])
@pytest.mark.parametrize("fallback_owner", [None, "third-id"])
@pytest.mark.asyncio
async def test_collision_fallback_never_overwrites_unrelated_content(
    tmp_path, entry, fallback_owner
):
    await refresh(tmp_path, "Document", entry, "first-id", "Shared name")
    state = SyncState(tmp_path)
    state.load()
    fallback = "linear/documents/shared-name-second-id.md"
    (tmp_path / fallback).write_text("unrelated content")
    if fallback_owner:
        state.add_mapping(fallback, fallback_owner)
        state.save()
    before = {
        str(p.relative_to(tmp_path)): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    with pytest.raises(ValueError):
        await refresh(tmp_path, "Document", entry, "second-id", "Shared name")
    # Pull may update last-sync only on success; no failing writer may touch files.
    assert {
        str(p.relative_to(tmp_path)): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    } == before
