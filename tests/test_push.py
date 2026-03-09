"""Tests for push sync: detect git changes and push to Linear API."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from issueclaw.commands import push as push_mod
from issueclaw.main import cli
from issueclaw.sync_state import SyncState


def _write_issue_md(repo_dir: Path, identifier: str, title: str, status: str = "Todo",
                    body: str = "Description.", team_key: str = "AI",
                    comments: str = "") -> Path:
    """Write a minimal issue markdown file and return its path."""
    from issueclaw.paths import entity_path
    rel_path = entity_path("issue", team_key=team_key, identifier=identifier, issue_title=title)
    full_path = repo_dir / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    md = f"""---
id: uuid-{identifier.lower()}
identifier: {identifier}
title: {title}
status: {status}
priority: 2
created: '2026-01-01T00:00:00Z'
updated: '2026-01-01T00:00:00Z'
url: https://linear.app/test
---

# {identifier}: {title}

{body}
{comments}"""
    full_path.write_text(md)
    return full_path


@pytest.mark.asyncio
async def test_push_detects_modified_frontmatter(tmp_path):
    """INVARIANT: Modified frontmatter fields generate an update API call."""
    # Set up old state
    _write_issue_md(tmp_path, "AI-1", "Fix bug", status="Todo")
    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/teams/AI/issues/AI-1-fix-bug.md", "uuid-ai-1")
    state.save()

    # Simulate git diff: changed files with old and new content
    old_content = _write_issue_md(tmp_path, "AI-1", "Fix bug", status="Todo").read_text()
    new_path = _write_issue_md(tmp_path, "AI-1", "Fix bug", status="Done")
    new_content = new_path.read_text()

    changes = [push_mod.FileChange(
        path="linear/teams/AI/issues/AI-1-fix-bug.md",
        change_type="modified",
        old_content=old_content,
        new_content=new_content,
    )]

    mock_client = AsyncMock()
    mock_client.update_issue.return_value = {"id": "uuid-ai-1"}
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(push_mod, "LinearClient", return_value=mock_client):
        result = await push_mod.push_changes(changes, "test-key", tmp_path)

    assert result["updated"] == 1
    mock_client.update_issue.assert_called_once()
    call_args = mock_client.update_issue.call_args
    assert call_args[0][0] == "uuid-ai-1"  # entity ID
    assert "status" in call_args[0][1] or "status" in call_args[1].get("fields", {})


@pytest.mark.asyncio
async def test_push_detects_modified_body(tmp_path):
    """INVARIANT: Modified body generates an update with description field."""
    _write_issue_md(tmp_path, "AI-1", "Fix bug", body="Original.")
    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/teams/AI/issues/AI-1-fix-bug.md", "uuid-ai-1")
    state.save()

    old_content = _write_issue_md(tmp_path, "AI-1", "Fix bug", body="Original.").read_text()
    new_path = _write_issue_md(tmp_path, "AI-1", "Fix bug", body="Updated description.")
    new_content = new_path.read_text()

    changes = [push_mod.FileChange(
        path="linear/teams/AI/issues/AI-1-fix-bug.md",
        change_type="modified",
        old_content=old_content,
        new_content=new_content,
    )]

    mock_client = AsyncMock()
    mock_client.update_issue.return_value = {"id": "uuid-ai-1"}
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(push_mod, "LinearClient", return_value=mock_client):
        result = await push_mod.push_changes(changes, "test-key", tmp_path)

    assert result["updated"] == 1


@pytest.mark.asyncio
async def test_push_deleted_file_archives_issue(tmp_path):
    """INVARIANT: Deleted issue files trigger an archive call in Linear."""
    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/teams/AI/issues/AI-1-fix-bug.md", "uuid-ai-1")
    state.save()

    changes = [push_mod.FileChange(
        path="linear/teams/AI/issues/AI-1-fix-bug.md",
        change_type="deleted",
        old_content="old content",
        new_content=None,
    )]

    mock_client = AsyncMock()
    mock_client.archive_issue.return_value = {"id": "uuid-ai-1"}
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(push_mod, "LinearClient", return_value=mock_client):
        result = await push_mod.push_changes(changes, "test-key", tmp_path)

    assert result["archived"] == 1
    mock_client.archive_issue.assert_called_once_with("uuid-ai-1")


@pytest.mark.asyncio
async def test_push_new_comment(tmp_path):
    """INVARIANT: New comments in issue files create comments via API."""
    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/teams/AI/issues/AI-1-fix-bug.md", "uuid-ai-1")
    state.save()

    old_content = _write_issue_md(tmp_path, "AI-1", "Fix bug").read_text()
    comments = """
# Comments

## Aviad - 2026-03-09T10:00:00Z
<!-- comment-id: new-comment -->

This is a new comment from git.
"""
    new_path = _write_issue_md(tmp_path, "AI-1", "Fix bug", comments=comments)
    new_content = new_path.read_text()

    changes = [push_mod.FileChange(
        path="linear/teams/AI/issues/AI-1-fix-bug.md",
        change_type="modified",
        old_content=old_content,
        new_content=new_content,
    )]

    mock_client = AsyncMock()
    mock_client.update_issue.return_value = {"id": "uuid-ai-1"}
    mock_client.create_comment.return_value = {"id": "new-comment-uuid"}
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(push_mod, "LinearClient", return_value=mock_client):
        result = await push_mod.push_changes(changes, "test-key", tmp_path)

    mock_client.create_comment.assert_called_once()
    call_args = mock_client.create_comment.call_args
    assert call_args[0][0] == "uuid-ai-1"  # issue ID
    assert "new comment from git" in call_args[0][1]  # comment body


@pytest.mark.asyncio
async def test_push_no_changes_is_noop(tmp_path):
    """INVARIANT: No changes produces zero API calls."""
    result = await push_mod.push_changes([], "test-key", tmp_path)
    assert result["updated"] == 0
    assert result["archived"] == 0


@pytest.mark.asyncio
async def test_push_skips_non_linear_files(tmp_path):
    """INVARIANT: Files outside linear/ directory are ignored."""
    changes = [push_mod.FileChange(
        path="README.md",
        change_type="modified",
        old_content="old",
        new_content="new",
    )]

    result = await push_mod.push_changes(changes, "test-key", tmp_path)
    assert result["skipped"] == 1
