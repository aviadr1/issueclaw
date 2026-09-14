"""Explicit recovery requires preserved bytes and never weakens normal replay."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from issueclaw import alias_recovery
from issueclaw.commands import apply_webhook as webhook
from issueclaw.entity_changes import FileChange, apply_changes
from issueclaw.inbox_contract import Payload, WorkItem
from issueclaw.inbox_replay import git
from issueclaw.sync_state import SyncState
from tests.test_apply_webhook import _make_issue_api_response
from tests.test_inbox_replay import repo as repo


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["success", "source_failure", "cancelled", "changed_after_backup"]
)
async def test_recovery_preserves_originals_until_verified_source_preparation(
    repo, mode
):
    path, _ = repo
    raw = _make_issue_api_response()
    state = SyncState(path)
    for name in ("old", "new"):
        relative = f"linear/{name}.md"
        (path / "linear").mkdir(exist_ok=True)
        (path / relative).write_text(name)
        state.add_mapping(relative, raw["id"])
    state.save()
    git(path, "add", ".")
    git(path, "commit", "-m", "historical conflicting files")
    git(path, "push", "origin", "HEAD:refs/heads/recovery/test")
    commit = alias_recovery.verify_recovery(path, "recovery/test")
    if mode == "changed_after_backup":
        (path / "linear/old.md").write_text("not preserved remotely")
    before = {
        p: p.read_bytes()
        for root in (path / "linear", path / ".sync")
        for p in root.rglob("*")
        if p.is_file()
    }
    item = WorkItem(
        key=f"org/Issue/{raw['id']}",
        generation=1,
        payload=Payload(
            type="Issue",
            action="update",
            data={"id": raw["id"]},
            createdAt="2026-09-14T00:00:00Z",
        ),
    )
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.fetch_issue.return_value = raw
    changes: list[FileChange] = []
    if mode == "source_failure":
        client.fetch_issue.side_effect = RuntimeError("upstream unavailable")
    if mode == "cancelled":
        client.fetch_issue.side_effect = asyncio.CancelledError()
    with patch.object(webhook, "LinearClient", return_value=client):
        if mode != "success":
            with pytest.raises((ValueError, RuntimeError, asyncio.CancelledError)):
                await alias_recovery.prepare_recovered_entity(
                    item, path, "unused", commit
                )
            if mode == "changed_after_backup":
                client.fetch_issue.assert_not_awaited()
        else:
            changes = await alias_recovery.prepare_recovered_entity(
                item, path, "unused", commit
            )
    assert before == {
        p: p.read_bytes()
        for root in (path / "linear", path / ".sync")
        for p in root.rglob("*")
        if p.is_file()
    }
    if mode == "success":
        apply_changes(path, changes)
        state.load()
        assert len(state.get_paths(raw["id"])) == 1
        assert raw["title"] in (path / state.get_paths(raw["id"])[0]).read_text()
        assert git(path, "show", f"{commit}:linear/old.md") == "old"
        assert git(path, "show", f"{commit}:linear/new.md") == "new"


def test_recovery_requires_an_existing_remote_recovery_branch(repo):
    path, _ = repo
    with pytest.raises(ValueError):
        alias_recovery.verify_recovery(path, "main")
    with pytest.raises(ValueError):
        alias_recovery.verify_recovery(path, "recovery/missing")
