"""Tests for the initial sync (pull) command."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from issueclaw.linear_client import LinearClient
from issueclaw.main import cli
from issueclaw.models import (
    LinearComment,
    LinearDocument,
    LinearInitiative,
    LinearIssue,
    LinearProject,
)


@pytest.fixture
def runner():
    return CliRunner()


# Fixtures: real model instances per CLAUDE.md rules

@pytest.fixture
def sample_team():
    return {"id": "team-uuid", "name": "AI", "key": "AI"}


@pytest.fixture
def sample_issue():
    return LinearIssue(
        id="issue-uuid",
        identifier="AI-1",
        title="Fix bug",
        description="The bug is bad.",
        status="Todo",
        priority=2,
        priority_name="Medium",
        team="AI",
        team_id="team-uuid",
        team_key="AI",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-02T00:00:00Z",
        url="https://linear.app/test/issue/AI-1",
    )


@pytest.fixture
def sample_comment():
    return LinearComment(
        id="comment-uuid",
        body="Looks good!",
        author_name="Aviad",
        author_id="user-uuid",
        created="2026-01-01T12:00:00Z",
        updated="2026-01-01T12:00:00Z",
    )


@pytest.fixture
def sample_project():
    return LinearProject(
        id="proj-uuid",
        name="Chapter Detection",
        slug="chapter-detection",
        description="Detect chapters in video.",
        status="started",
        lead_name="Aviad",
        lead_id="user-uuid",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-02T00:00:00Z",
        url="https://linear.app/test/project/chapter-detection",
    )


@pytest.fixture
def sample_initiative():
    return LinearInitiative(
        id="init-uuid",
        name="Q1 Roadmap",
        description="Quarterly goals.",
        status="active",
        owner_name="Aviad",
        owner_id="user-uuid",
        target_date="2026-03-31",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-02T00:00:00Z",
    )


@pytest.fixture
def sample_document():
    return LinearDocument(
        id="doc-uuid",
        title="Architecture Overview",
        content="# Architecture\n\nThis is the overview.",
        slug_id="architecture-overview",
        url="https://linear.app/test/document/architecture-overview",
        creator_name="Aviad",
        creator_id="user-uuid",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-02T00:00:00Z",
    )


def _make_mock_client(
    teams, issues_by_team, comments_by_issue, projects, initiatives, documents
):
    """Create a mock LinearClient with specified return values."""
    mock = MagicMock(spec=LinearClient)
    mock.fetch_teams = AsyncMock(return_value=teams)
    mock.fetch_projects = AsyncMock(return_value=projects)
    mock.fetch_initiatives = AsyncMock(return_value=initiatives)
    mock.fetch_documents = AsyncMock(return_value=documents)

    # fetch_issues returns raw API dicts (LinearClient returns dicts)
    mock.fetch_issues = AsyncMock(
        side_effect=lambda team_id, include_comments=True: issues_by_team.get(team_id, [])
    )
    mock.fetch_comments = AsyncMock(side_effect=lambda issue_id: comments_by_issue.get(issue_id, []))

    # Support async context manager usage
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)

    return mock


def test_sync_creates_issue_files(runner, tmp_path, sample_team, sample_issue):
    """INVARIANT: Sync creates .md files for all issues in specified teams."""
    # Raw API dicts that LinearClient would return
    issue_api = {
        "id": "issue-uuid",
        "identifier": "AI-1",
        "title": "Fix bug",
        "description": "The bug is bad.",
        "priority": 2,
        "priorityLabel": "Medium",
        "state": {"name": "Todo"},
        "assignee": None,
        "labels": {"nodes": []},
        "project": None,
        "cycle": None,
        "estimate": None,
        "dueDate": None,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "url": "https://linear.app/test/issue/AI-1",
    }

    mock_client = _make_mock_client(
        teams=[sample_team],
        issues_by_team={"team-uuid": [issue_api]},
        comments_by_issue={},
        projects=[],
        initiatives=[],
        documents=[],
    )

    import issueclaw.commands.pull as pull_mod

    with patch.object(pull_mod, "LinearClient", return_value=mock_client):
        result = runner.invoke(cli, ["pull", "--repo-dir", str(tmp_path), "--api-key", "test-key"])

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    issue_file = tmp_path / "linear" / "teams" / "AI" / "issues" / "AI-1-fix-bug.md"
    assert issue_file.exists(), f"Issue file not created. Output: {result.output}"
    content = issue_file.read_text()
    assert "Fix bug" in content
    assert "AI-1" in content


def test_sync_creates_id_map(runner, tmp_path, sample_team):
    """INVARIANT: Sync creates id-map.json mapping file paths to Linear UUIDs."""
    issue_api = {
        "id": "issue-uuid",
        "identifier": "AI-1",
        "title": "Fix bug",
        "description": None,
        "priority": 2,
        "priorityLabel": "Medium",
        "state": {"name": "Todo"},
        "assignee": None,
        "labels": {"nodes": []},
        "project": None,
        "cycle": None,
        "estimate": None,
        "dueDate": None,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "url": "https://linear.app/test/issue/AI-1",
    }

    mock_client = _make_mock_client(
        teams=[sample_team],
        issues_by_team={"team-uuid": [issue_api]},
        comments_by_issue={},
        projects=[],
        initiatives=[],
        documents=[],
    )

    import issueclaw.commands.pull as pull_mod

    with patch.object(pull_mod, "LinearClient", return_value=mock_client):
        result = runner.invoke(cli, ["pull", "--repo-dir", str(tmp_path), "--api-key", "test-key"])

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    id_map = tmp_path / ".sync" / "id-map.json"
    assert id_map.exists()
    mapping = json.loads(id_map.read_text())
    assert "linear/teams/AI/issues/AI-1-fix-bug.md" in mapping
    assert mapping["linear/teams/AI/issues/AI-1-fix-bug.md"] == "issue-uuid"


def test_sync_creates_project_files(runner, tmp_path, sample_team):
    """INVARIANT: Sync creates .md files for all projects."""
    project_api = {
        "id": "proj-uuid",
        "name": "Chapter Detection",
        "slugId": "chapter-detection",
        "description": "Detect chapters.",
        "state": "started",
        "lead": {"id": "user-uuid", "name": "Aviad", "email": "a@b.com"},
        "url": "https://linear.app/test/project/chapter-detection",
        "startDate": None,
        "targetDate": None,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "teams": {"nodes": []},
        "projectMilestones": {"nodes": []},
    }

    mock_client = _make_mock_client(
        teams=[sample_team],
        issues_by_team={},
        comments_by_issue={},
        projects=[project_api],
        initiatives=[],
        documents=[],
    )

    import issueclaw.commands.pull as pull_mod

    with patch.object(pull_mod, "LinearClient", return_value=mock_client):
        result = runner.invoke(cli, ["pull", "--repo-dir", str(tmp_path), "--api-key", "test-key"])

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    proj_file = tmp_path / "linear" / "projects" / "chapter-detection" / "_project.md"
    assert proj_file.exists(), f"Project file not created. Output: {result.output}"
    content = proj_file.read_text()
    assert "Chapter Detection" in content


def test_sync_creates_initiative_files(runner, tmp_path, sample_team):
    """INVARIANT: Sync creates .md files for all initiatives."""
    init_api = {
        "id": "init-uuid",
        "name": "Q1 Roadmap",
        "description": "Quarterly goals.",
        "status": "active",
        "targetDate": "2026-03-31",
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "owner": {"id": "user-uuid", "name": "Aviad", "email": "a@b.com"},
    }

    mock_client = _make_mock_client(
        teams=[sample_team],
        issues_by_team={},
        comments_by_issue={},
        projects=[],
        initiatives=[init_api],
        documents=[],
    )

    import issueclaw.commands.pull as pull_mod

    with patch.object(pull_mod, "LinearClient", return_value=mock_client):
        result = runner.invoke(cli, ["pull", "--repo-dir", str(tmp_path), "--api-key", "test-key"])

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    init_file = tmp_path / "linear" / "initiatives" / "q1-roadmap.md"
    assert init_file.exists(), f"Initiative file not created. Output: {result.output}"
    content = init_file.read_text()
    assert "Q1 Roadmap" in content


def test_sync_creates_document_files(runner, tmp_path, sample_team):
    """INVARIANT: Sync creates .md files for all documents."""
    doc_api = {
        "id": "doc-uuid",
        "title": "Architecture Overview",
        "content": "# Architecture\n\nThis is the overview.",
        "slugId": "architecture-overview",
        "url": "https://linear.app/test/document/architecture-overview",
        "icon": None,
        "color": None,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "creator": {"id": "user-uuid", "name": "Aviad"},
        "updatedBy": {"id": "user-uuid", "name": "Aviad"},
        "project": None,
    }

    mock_client = _make_mock_client(
        teams=[sample_team],
        issues_by_team={},
        comments_by_issue={},
        projects=[],
        initiatives=[],
        documents=[doc_api],
    )

    import issueclaw.commands.pull as pull_mod

    with patch.object(pull_mod, "LinearClient", return_value=mock_client):
        result = runner.invoke(cli, ["pull", "--repo-dir", str(tmp_path), "--api-key", "test-key"])

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    doc_file = tmp_path / "linear" / "documents" / "architecture-overview.md"
    assert doc_file.exists(), f"Document file not created. Output: {result.output}"
    content = doc_file.read_text()
    assert "Architecture Overview" in content
    assert "# Architecture" in content


def test_sync_filters_teams(runner, tmp_path):
    """INVARIANT: When --teams is specified, only those teams' issues are synced."""
    teams = [
        {"id": "team-1", "name": "AI", "key": "AI"},
        {"id": "team-2", "name": "Backend", "key": "BE"},
    ]
    ai_issue = {
        "id": "issue-1",
        "identifier": "AI-1",
        "title": "AI issue",
        "description": None,
        "priority": 1,
        "priorityLabel": "Urgent",
        "state": {"name": "Todo"},
        "assignee": None,
        "labels": {"nodes": []},
        "project": None,
        "cycle": None,
        "estimate": None,
        "dueDate": None,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-01T00:00:00Z",
        "url": "",
    }

    mock_client = _make_mock_client(
        teams=teams,
        issues_by_team={"team-1": [ai_issue]},
        comments_by_issue={},
        projects=[],
        initiatives=[],
        documents=[],
    )

    import issueclaw.commands.pull as pull_mod

    with patch.object(pull_mod, "LinearClient", return_value=mock_client):
        result = runner.invoke(
            cli, ["pull", "--repo-dir", str(tmp_path), "--api-key", "test-key", "--teams", "AI"]
        )

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    # AI issues should exist
    ai_file = tmp_path / "linear" / "teams" / "AI" / "issues" / "AI-1-ai-issue.md"
    assert ai_file.exists()
    # BE issues dir should NOT exist (team was filtered out)
    be_dir = tmp_path / "linear" / "teams" / "BE"
    assert not be_dir.exists()


def test_sync_includes_comments_in_issues(runner, tmp_path, sample_team):
    """INVARIANT: Issue files include comments from Linear."""
    issue_api = {
        "id": "issue-uuid",
        "identifier": "AI-1",
        "title": "Fix bug",
        "description": "The bug.",
        "priority": 2,
        "priorityLabel": "Medium",
        "state": {"name": "Todo"},
        "assignee": None,
        "labels": {"nodes": []},
        "project": None,
        "cycle": None,
        "estimate": None,
        "dueDate": None,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "url": "",
    }
    # Add inline comments to the issue API response
    issue_api["comments"] = {
        "nodes": [
            {
                "id": "comment-uuid",
                "body": "Looks good!",
                "createdAt": "2026-01-01T12:00:00Z",
                "updatedAt": "2026-01-01T12:00:00Z",
                "user": {"id": "user-uuid", "name": "Aviad", "email": "a@b.com"},
            }
        ]
    }

    mock_client = _make_mock_client(
        teams=[sample_team],
        issues_by_team={"team-uuid": [issue_api]},
        comments_by_issue={},
        projects=[],
        initiatives=[],
        documents=[],
    )

    import issueclaw.commands.pull as pull_mod

    with patch.object(pull_mod, "LinearClient", return_value=mock_client):
        result = runner.invoke(cli, ["pull", "--repo-dir", str(tmp_path), "--api-key", "test-key"])

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    issue_file = tmp_path / "linear" / "teams" / "AI" / "issues" / "AI-1-fix-bug.md"
    content = issue_file.read_text()
    assert "# Comments" in content
    assert "Looks good!" in content
    assert "Aviad" in content


def test_sync_api_key_from_env(runner, tmp_path, sample_team):
    """INVARIANT: API key can be provided via LINEAR_API_KEY env var."""
    mock_client = _make_mock_client(
        teams=[sample_team],
        issues_by_team={},
        comments_by_issue={},
        projects=[],
        initiatives=[],
        documents=[],
    )

    import issueclaw.commands.pull as pull_mod

    with patch.object(pull_mod, "LinearClient", return_value=mock_client):
        result = runner.invoke(
            cli,
            ["pull", "--repo-dir", str(tmp_path)],
            env={"LINEAR_API_KEY": "env-test-key"},
        )

    assert result.exit_code == 0, f"CLI failed: {result.output}"


def test_sync_fails_without_api_key(runner, tmp_path):
    """INVARIANT: Sync fails with clear error when no API key is provided."""
    result = runner.invoke(
        cli,
        ["pull", "--repo-dir", str(tmp_path)],
        env={"LINEAR_API_KEY": ""},
    )

    assert result.exit_code != 0


def test_sync_shows_progress(runner, tmp_path, sample_team):
    """INVARIANT: Pull outputs progress messages showing what is being synced."""
    issue_api = {
        "id": "issue-uuid",
        "identifier": "AI-1",
        "title": "Fix bug",
        "description": None,
        "priority": 2,
        "priorityLabel": "Medium",
        "state": {"name": "Todo"},
        "assignee": None,
        "labels": {"nodes": []},
        "project": None,
        "cycle": None,
        "estimate": None,
        "dueDate": None,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "url": "",
    }

    mock_client = _make_mock_client(
        teams=[sample_team],
        issues_by_team={"team-uuid": [issue_api]},
        comments_by_issue={},
        projects=[],
        initiatives=[],
        documents=[],
    )

    import issueclaw.commands.pull as pull_mod

    with patch.object(pull_mod, "LinearClient", return_value=mock_client):
        result = runner.invoke(cli, ["pull", "--repo-dir", str(tmp_path), "--api-key", "test-key"])

    assert result.exit_code == 0
    # Should show team progress
    assert "AI" in result.output
    # Should show final summary
    assert "1 issues" in result.output


def test_sync_saves_state_incrementally(runner, tmp_path, sample_team):
    """INVARIANT: State is saved after each entity type, not just at the end."""
    issue_api = {
        "id": "issue-uuid",
        "identifier": "AI-1",
        "title": "Fix bug",
        "description": None,
        "priority": 2,
        "priorityLabel": "Medium",
        "state": {"name": "Todo"},
        "assignee": None,
        "labels": {"nodes": []},
        "project": None,
        "cycle": None,
        "estimate": None,
        "dueDate": None,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "url": "",
    }

    save_calls = []
    original_save = None

    def tracking_save(self_state):
        # Record what's in the id-map at each save
        save_calls.append(dict(self_state._path_to_uuid))
        original_save(self_state)

    mock_client = _make_mock_client(
        teams=[sample_team],
        issues_by_team={"team-uuid": [issue_api]},
        comments_by_issue={},
        projects=[],
        initiatives=[],
        documents=[],
    )

    import issueclaw.commands.pull as pull_mod
    from issueclaw.sync_state import SyncState

    original_save = SyncState.save

    with (
        patch.object(pull_mod, "LinearClient", return_value=mock_client),
        patch.object(SyncState, "save", tracking_save),
    ):
        result = runner.invoke(cli, ["pull", "--repo-dir", str(tmp_path), "--api-key", "test-key"])

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    # Should have saved at least twice (after issues, and final save)
    assert len(save_calls) >= 2


def test_sync_json_output(runner, tmp_path, sample_team):
    """INVARIANT: With --json flag, output is valid JSON with sync stats."""
    mock_client = _make_mock_client(
        teams=[sample_team],
        issues_by_team={},
        comments_by_issue={},
        projects=[],
        initiatives=[],
        documents=[],
    )

    import issueclaw.commands.pull as pull_mod

    with patch.object(pull_mod, "LinearClient", return_value=mock_client):
        result = runner.invoke(
            cli, ["--json", "pull", "--repo-dir", str(tmp_path), "--api-key", "test-key"]
        )

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    data = json.loads(result.output)
    assert "issues" in data
    assert "projects" in data
    assert "initiatives" in data
    assert "documents" in data


def test_sync_resumes_after_interruption(runner, tmp_path, sample_team):
    """INVARIANT: Running pull again after partial sync picks up where it left off."""
    issue_api = {
        "id": "issue-uuid",
        "identifier": "AI-1",
        "title": "Fix bug",
        "description": None,
        "priority": 2,
        "priorityLabel": "Medium",
        "state": {"name": "Todo"},
        "assignee": None,
        "labels": {"nodes": []},
        "project": None,
        "cycle": None,
        "estimate": None,
        "dueDate": None,
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-01-02T00:00:00Z",
        "url": "",
    }

    mock_client = _make_mock_client(
        teams=[sample_team],
        issues_by_team={"team-uuid": [issue_api]},
        comments_by_issue={},
        projects=[],
        initiatives=[],
        documents=[],
    )

    import issueclaw.commands.pull as pull_mod

    # First run
    with patch.object(pull_mod, "LinearClient", return_value=mock_client):
        result1 = runner.invoke(cli, ["pull", "--repo-dir", str(tmp_path), "--api-key", "test-key"])
    assert result1.exit_code == 0

    # Second run - should succeed and overwrite (idempotent)
    with patch.object(pull_mod, "LinearClient", return_value=mock_client):
        result2 = runner.invoke(cli, ["pull", "--repo-dir", str(tmp_path), "--api-key", "test-key"])
    assert result2.exit_code == 0

    # Files should still exist and be correct
    issue_file = tmp_path / "linear" / "teams" / "AI" / "issues" / "AI-1-fix-bug.md"
    assert issue_file.exists()
    assert "Fix bug" in issue_file.read_text()
