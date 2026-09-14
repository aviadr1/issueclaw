"""Identity invariants through production webhook preparation and pull entry points."""

from unittest.mock import AsyncMock, patch

import pytest

from issueclaw.commands import apply_webhook as webhook
from issueclaw.commands import pull
from issueclaw.entity_changes import apply_changes, prepare_entity
from issueclaw.paths import entity_path
from issueclaw.sync_state import SyncState
from tests.test_apply_webhook import _make_issue_api_response


@pytest.fixture
def aliases(tmp_path):
    state = SyncState(tmp_path)
    for name, owner in [("old", "entity"), ("new", "entity"), ("other", "other")]:
        relative = f"linear/{name}.md"
        (tmp_path / "linear").mkdir(exist_ok=True)
        (tmp_path / relative).write_text("original")
        state.add_mapping(relative, owner)
    state.save()
    return state


@pytest.mark.parametrize("kind", ["Issue", "Project", "Initiative", "Document"])
@pytest.mark.parametrize("isolated", [False, True])
@pytest.mark.asyncio
async def test_remove_clears_all_owned_paths_not_other_entities(
    tmp_path, aliases, kind, isolated
):
    payload = {"type": kind, "action": "remove", "data": {"id": "entity"}}
    if isolated:
        apply_changes(tmp_path, await prepare_entity(payload, "unused", tmp_path))
    else:
        await webhook.apply_webhook(payload, "unused", tmp_path)
    aliases.load()
    assert not (tmp_path / "linear/old.md").exists()
    assert not (tmp_path / "linear/new.md").exists()
    assert aliases.get_path("entity") is None
    assert (tmp_path / "linear/other.md").read_text() == "original"
    assert aliases.get_uuid("linear/other.md") == "other"


def test_removing_one_alias_preserves_reverse_lookup(aliases):
    aliases.remove_mapping("linear/new.md")
    assert aliases.get_path("entity") == "linear/old.md"


@pytest.mark.parametrize("conflict", ["foreign", "unmapped", "divergent"])
@pytest.mark.parametrize("isolated", [False, True])
@pytest.mark.asyncio
async def test_refresh_preserves_conflicting_files(
    tmp_path, aliases, conflict, isolated
):
    raw = _make_issue_api_response()
    raw["id"] = "entity"
    target = entity_path(
        "issue", team_key="AI", identifier=raw["identifier"], issue_title=raw["title"]
    )
    if conflict == "divergent":
        (tmp_path / "linear/old.md").write_text("pending edit")
    else:
        file = tmp_path / target
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("do not overwrite")
        if conflict == "foreign":
            aliases.add_mapping(target, "foreign")
            aliases.save()
    before = {
        str(p.relative_to(tmp_path)): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.fetch_issue.return_value = raw
    payload = {"type": "Issue", "action": "update", "data": {"id": "entity"}}
    with patch.object(webhook, "LinearClient", return_value=client):
        with pytest.raises(ValueError):
            if isolated:
                apply_changes(
                    tmp_path, await prepare_entity(payload, "unused", tmp_path)
                )
            else:
                await webhook.apply_webhook(payload, "unused", tmp_path)
    if isolated and conflict == "divergent":
        client.fetch_issue.assert_not_awaited()
    assert {
        str(p.relative_to(tmp_path)): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    } == before


@pytest.mark.parametrize("isolated", [False, True])
@pytest.mark.asyncio
async def test_refresh_consolidates_identical_aliases(tmp_path, aliases, isolated):
    raw = _make_issue_api_response()
    raw["id"] = "entity"
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.fetch_issue.return_value = raw
    payload = {"type": "Issue", "action": "update", "data": {"id": "entity"}}
    with patch.object(webhook, "LinearClient", return_value=client):
        if isolated:
            apply_changes(tmp_path, await prepare_entity(payload, "unused", tmp_path))
        else:
            await webhook.apply_webhook(payload, "unused", tmp_path)
    aliases.load()
    assert len(aliases.get_paths("entity")) == 1
    assert len(list((tmp_path / "linear").rglob("*.md"))) == 2
    assert (tmp_path / "linear/other.md").read_text() == "original"


@pytest.mark.asyncio
async def test_pull_title_changes_do_not_accumulate_paths(tmp_path):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.fetch_teams.return_value = [{"key": "AI", "id": "team"}]
    client.fetch_projects.return_value = []
    client.fetch_initiatives.return_value = []
    client.fetch_documents.return_value = []
    with patch.object(pull, "LinearClient", return_value=client):
        for title in ["First title", "Second title", "Third title"]:
            raw = _make_issue_api_response()
            raw["title"] = title
            client.fetch_issues.return_value = [raw]
            await pull._run_pull(
                "unused", tmp_path, None, show_progress=False, log=lambda _: None
            )
            files = list((tmp_path / "linear").rglob("*.md"))
            assert len(files) == 1
            assert title in files[0].read_text()
