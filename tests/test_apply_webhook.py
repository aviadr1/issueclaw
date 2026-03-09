"""Tests for webhook application: apply incoming Linear webhook payloads to the repo."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from issueclaw.commands import apply_webhook as webhook_mod
from issueclaw.main import cli
from issueclaw.sync_state import SyncState


def _make_webhook_payload(action: str, entity_type: str, entity_id: str, **extra_data) -> dict:
    """Create a minimal webhook payload for testing."""
    data = {"id": entity_id, **extra_data}
    return {
        "action": action,
        "type": entity_type,
        "data": data,
        "url": f"https://linear.app/test/{entity_id}",
        "createdAt": "2026-03-09T10:00:00Z",
    }


def _make_issue_api_response(identifier: str = "AI-1", title: str = "Fix bug", team_key: str = "AI") -> dict:
    """Create a mock API response for a single issue fetch."""
    return {
        "id": "issue-uuid-1",
        "identifier": identifier,
        "title": title,
        "description": "Description text.",
        "priority": 2,
        "priorityLabel": "High",
        "url": "https://linear.app/test/issue/AI-1",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-03-09T10:00:00Z",
        "state": {"name": "In Progress"},
        "assignee": {"id": "user-1", "name": "Aviad", "email": "aviad@test.com"},
        "labels": {"nodes": [{"name": "bug"}]},
        "team": {"id": "team-uuid", "key": team_key, "name": "AI Team"},
        "project": None,
        "projectMilestone": None,
        "parent": None,
        "comments": {"nodes": []},
    }


def _make_project_api_response(name: str = "Metrics Platform") -> dict:
    """Create a mock API response for a single project fetch."""
    return {
        "id": "proj-uuid-1",
        "name": name,
        "slugId": "abc123",
        "description": "Project description.",
        "content": "# Full Content\n\nRich details.",
        "priority": 2,
        "health": "onTrack",
        "progress": 0.5,
        "scope": 20,
        "status": {"name": "In Progress"},
        "lead": {"id": "user-1", "name": "Aviad"},
        "url": "https://linear.app/test/project/metrics",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-03-09T10:00:00Z",
        "teams": {"nodes": [{"key": "AI", "name": "AI Team"}]},
        "members": {"nodes": [{"name": "Aviad"}]},
        "labels": {"nodes": []},
        "projectMilestones": {"nodes": []},
        "projectUpdates": {"nodes": []},
        "initiatives": {"nodes": []},
        "documents": {"nodes": []},
    }


def _make_initiative_api_response(name: str = "Q1 Roadmap") -> dict:
    """Create a mock API response for a single initiative fetch."""
    return {
        "id": "init-uuid-1",
        "name": name,
        "description": "Initiative description.",
        "content": None,
        "status": "Active",
        "health": "onTrack",
        "targetDate": "2026-06-30",
        "url": "https://linear.app/test/initiative/q1",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-03-09T10:00:00Z",
        "owner": {"id": "user-1", "name": "Aviad"},
        "projects": {"nodes": []},
    }


def _make_document_api_response(title: str = "Architecture Doc") -> dict:
    """Create a mock API response for a single document fetch."""
    return {
        "id": "doc-uuid-1",
        "title": title,
        "content": "# Architecture\n\nDetails here.",
        "slugId": "doc-slug",
        "url": "https://linear.app/test/doc/1",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-03-09T10:00:00Z",
        "creator": {"id": "user-1", "name": "Aviad"},
        "updatedBy": None,
        "project": None,
    }


@pytest.mark.asyncio
async def test_apply_webhook_issue_create(tmp_path):
    """INVARIANT: Issue create webhook fetches the full issue and writes a markdown file."""
    payload = _make_webhook_payload("create", "Issue", "issue-uuid-1", teamId="team-uuid")
    api_response = _make_issue_api_response()

    mock_client = AsyncMock()
    mock_client.fetch_issue.return_value = api_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(webhook_mod, "LinearClient", return_value=mock_client):
        result = await webhook_mod.apply_webhook(payload, "test-api-key", tmp_path)

    assert result["action"] == "create"
    assert result["entity_type"] == "Issue"
    expected_path = tmp_path / "linear" / "teams" / "AI" / "issues" / "AI-1-fix-bug.md"
    assert expected_path.exists()
    content = expected_path.read_text()
    assert "AI-1" in content
    assert "Fix bug" in content


@pytest.mark.asyncio
async def test_apply_webhook_issue_update(tmp_path):
    """INVARIANT: Issue update webhook re-fetches and overwrites the existing file."""
    # Pre-create an existing file
    issue_dir = tmp_path / "linear" / "teams" / "AI" / "issues"
    issue_dir.mkdir(parents=True)
    old_file = issue_dir / "AI-1-fix-bug.md"
    old_file.write_text("old content")

    # Set up sync state with existing mapping
    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/teams/AI/issues/AI-1-fix-bug.md", "issue-uuid-1")
    state.save()

    payload = _make_webhook_payload("update", "Issue", "issue-uuid-1", teamId="team-uuid")
    api_response = _make_issue_api_response(title="Fix bug v2")

    mock_client = AsyncMock()
    mock_client.fetch_issue.return_value = api_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(webhook_mod, "LinearClient", return_value=mock_client):
        result = await webhook_mod.apply_webhook(payload, "test-api-key", tmp_path)

    assert result["action"] == "update"
    # New file should exist with updated title slug
    new_file = issue_dir / "AI-1-fix-bug-v2.md"
    assert new_file.exists()
    content = new_file.read_text()
    assert "Fix bug v2" in content


@pytest.mark.asyncio
async def test_apply_webhook_issue_remove(tmp_path):
    """INVARIANT: Issue remove webhook deletes the markdown file."""
    # Pre-create the file and sync state
    issue_dir = tmp_path / "linear" / "teams" / "AI" / "issues"
    issue_dir.mkdir(parents=True)
    issue_file = issue_dir / "AI-1-fix-bug.md"
    issue_file.write_text("content")

    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/teams/AI/issues/AI-1-fix-bug.md", "issue-uuid-1")
    state.save()

    payload = _make_webhook_payload("remove", "Issue", "issue-uuid-1")

    # No API client needed for remove
    result = await webhook_mod.apply_webhook(payload, "test-api-key", tmp_path)

    assert result["action"] == "remove"
    assert not issue_file.exists()


@pytest.mark.asyncio
async def test_apply_webhook_project_create(tmp_path):
    """INVARIANT: Project create webhook fetches and writes project markdown."""
    payload = _make_webhook_payload("create", "Project", "proj-uuid-1")
    api_response = _make_project_api_response()

    mock_client = AsyncMock()
    mock_client.fetch_project.return_value = api_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(webhook_mod, "LinearClient", return_value=mock_client):
        result = await webhook_mod.apply_webhook(payload, "test-api-key", tmp_path)

    assert result["entity_type"] == "Project"
    expected_path = tmp_path / "linear" / "projects" / "metrics-platform" / "_project.md"
    assert expected_path.exists()
    content = expected_path.read_text()
    assert "Metrics Platform" in content
    assert "Full Content" in content


@pytest.mark.asyncio
async def test_apply_webhook_initiative_create(tmp_path):
    """INVARIANT: Initiative create webhook fetches and writes initiative markdown."""
    payload = _make_webhook_payload("create", "Initiative", "init-uuid-1")
    api_response = _make_initiative_api_response()

    mock_client = AsyncMock()
    mock_client.fetch_initiative.return_value = api_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(webhook_mod, "LinearClient", return_value=mock_client):
        result = await webhook_mod.apply_webhook(payload, "test-api-key", tmp_path)

    assert result["entity_type"] == "Initiative"
    expected_path = tmp_path / "linear" / "initiatives" / "q1-roadmap.md"
    assert expected_path.exists()


@pytest.mark.asyncio
async def test_apply_webhook_document_create(tmp_path):
    """INVARIANT: Document create webhook fetches and writes document markdown."""
    payload = _make_webhook_payload("create", "Document", "doc-uuid-1")
    api_response = _make_document_api_response()

    mock_client = AsyncMock()
    mock_client.fetch_document.return_value = api_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(webhook_mod, "LinearClient", return_value=mock_client):
        result = await webhook_mod.apply_webhook(payload, "test-api-key", tmp_path)

    assert result["entity_type"] == "Document"
    expected_path = tmp_path / "linear" / "documents" / "architecture-doc.md"
    assert expected_path.exists()


@pytest.mark.asyncio
async def test_apply_webhook_comment_triggers_parent_issue_refetch(tmp_path):
    """INVARIANT: Comment webhook re-fetches the parent issue and updates its file."""
    payload = _make_webhook_payload("create", "Comment", "comment-uuid-1", issueId="issue-uuid-1")
    api_response = _make_issue_api_response()
    api_response["comments"] = {"nodes": [
        {"id": "comment-uuid-1", "body": "New comment!", "createdAt": "2026-03-09T10:00:00Z",
         "updatedAt": "2026-03-09T10:00:00Z", "user": {"id": "user-1", "name": "Aviad"}},
    ]}

    mock_client = AsyncMock()
    mock_client.fetch_issue.return_value = api_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(webhook_mod, "LinearClient", return_value=mock_client):
        result = await webhook_mod.apply_webhook(payload, "test-api-key", tmp_path)

    assert result["entity_type"] == "Comment"
    issue_file = tmp_path / "linear" / "teams" / "AI" / "issues" / "AI-1-fix-bug.md"
    assert issue_file.exists()
    content = issue_file.read_text()
    assert "New comment!" in content


@pytest.mark.asyncio
async def test_apply_webhook_unknown_type_ignored(tmp_path):
    """INVARIANT: Unknown entity types return a skip result without errors."""
    payload = _make_webhook_payload("create", "Cycle", "cycle-uuid-1")

    result = await webhook_mod.apply_webhook(payload, "test-api-key", tmp_path)

    assert result["action"] == "skip"


@pytest.mark.asyncio
async def test_apply_webhook_remove_cleans_up_old_path_on_rename(tmp_path):
    """INVARIANT: When an issue is updated with a new title, the old file is removed."""
    # Pre-create old file with old title
    issue_dir = tmp_path / "linear" / "teams" / "AI" / "issues"
    issue_dir.mkdir(parents=True)
    old_file = issue_dir / "AI-1-old-title.md"
    old_file.write_text("old content")

    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/teams/AI/issues/AI-1-old-title.md", "issue-uuid-1")
    state.save()

    payload = _make_webhook_payload("update", "Issue", "issue-uuid-1", teamId="team-uuid")
    api_response = _make_issue_api_response(title="New title")

    mock_client = AsyncMock()
    mock_client.fetch_issue.return_value = api_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(webhook_mod, "LinearClient", return_value=mock_client):
        await webhook_mod.apply_webhook(payload, "test-api-key", tmp_path)

    # Old file should be gone
    assert not old_file.exists()
    # New file should exist
    new_file = issue_dir / "AI-1-new-title.md"
    assert new_file.exists()


def test_apply_webhook_cli_command(tmp_path):
    """INVARIANT: CLI apply-webhook command parses payload and writes files."""
    payload = _make_webhook_payload("create", "Issue", "issue-uuid-1", teamId="team-uuid")
    api_response = _make_issue_api_response()

    mock_client = AsyncMock()
    mock_client.fetch_issue.return_value = api_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    runner = CliRunner()
    with patch.object(webhook_mod, "LinearClient", return_value=mock_client):
        result = runner.invoke(cli, [
            "apply-webhook",
            "--api-key", "test-key",
            "--repo-dir", str(tmp_path),
            "--payload", json.dumps(payload),
        ])

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    assert "Created" in result.output or "Issue" in result.output
    expected_path = tmp_path / "linear" / "teams" / "AI" / "issues" / "AI-1-fix-bug.md"
    assert expected_path.exists()
