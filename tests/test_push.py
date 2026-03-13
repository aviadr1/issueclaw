"""Tests for push sync: detect git changes and push to Linear API."""

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
    """INVARIANT: Modified frontmatter fields generate an update API call with mapped field names."""
    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/teams/AI/issues/AI-1-fix-bug.md", "uuid-ai-1")
    state.save()

    # Change title (a directly mappable field)
    old_content = _write_issue_md(tmp_path, "AI-1", "Fix bug").read_text()
    new_path = _write_issue_md(tmp_path, "AI-1", "Fix critical bug")
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
    assert call_args[0][0] == "uuid-ai-1"
    assert "title" in call_args[0][1]
    assert call_args[0][1]["title"] == "Fix critical bug"


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


# Tests for detect_git_changes

def test_detect_git_changes_parses_modified_files(tmp_path):
    """INVARIANT: Modified files in linear/ produce FileChange with old and new content."""
    # Write current file on disk
    issue_dir = tmp_path / "linear" / "teams" / "AI" / "issues"
    issue_dir.mkdir(parents=True)
    issue_file = issue_dir / "AI-1-fix-bug.md"
    issue_file.write_text("new content")

    # Mock git diff --name-status output
    diff_output = "M\tlinear/teams/AI/issues/AI-1-fix-bug.md\n"
    old_content = "old content"

    mock_diff = MagicMock(stdout=diff_output, returncode=0)
    mock_show = MagicMock(stdout=old_content, returncode=0)

    def fake_run(cmd, **kwargs):
        if "diff" in cmd:
            return mock_diff
        if "show" in cmd:
            return mock_show
        return MagicMock(returncode=0)

    with patch.object(subprocess, "run", side_effect=fake_run):
        changes = push_mod.detect_git_changes(tmp_path)

    assert len(changes) == 1
    assert changes[0].path == "linear/teams/AI/issues/AI-1-fix-bug.md"
    assert changes[0].change_type == "modified"
    assert changes[0].old_content == "old content"
    assert changes[0].new_content == "new content"


def test_detect_git_changes_parses_deleted_files(tmp_path):
    """INVARIANT: Deleted files produce FileChange with change_type='deleted'."""
    diff_output = "D\tlinear/teams/AI/issues/AI-2-old-issue.md\n"
    old_content = "deleted file content"

    mock_diff = MagicMock(stdout=diff_output, returncode=0)
    mock_show = MagicMock(stdout=old_content, returncode=0)

    def fake_run(cmd, **kwargs):
        if "diff" in cmd:
            return mock_diff
        if "show" in cmd:
            return mock_show
        return MagicMock(returncode=0)

    with patch.object(subprocess, "run", side_effect=fake_run):
        changes = push_mod.detect_git_changes(tmp_path)

    assert len(changes) == 1
    assert changes[0].change_type == "deleted"
    assert changes[0].old_content == "deleted file content"
    assert changes[0].new_content is None


def test_detect_git_changes_parses_added_files(tmp_path):
    """INVARIANT: Added files produce FileChange with change_type='added'."""
    issue_dir = tmp_path / "linear" / "teams" / "AI" / "issues"
    issue_dir.mkdir(parents=True)
    issue_file = issue_dir / "AI-3-new-issue.md"
    issue_file.write_text("new file content")

    diff_output = "A\tlinear/teams/AI/issues/AI-3-new-issue.md\n"

    mock_diff = MagicMock(stdout=diff_output, returncode=0)

    def fake_run(cmd, **kwargs):
        if "diff" in cmd:
            return mock_diff
        return MagicMock(returncode=0, stdout="")

    with patch.object(subprocess, "run", side_effect=fake_run):
        changes = push_mod.detect_git_changes(tmp_path)

    assert len(changes) == 1
    assert changes[0].change_type == "added"
    assert changes[0].new_content == "new file content"
    assert changes[0].old_content is None


def test_detect_git_changes_filters_non_linear_files(tmp_path):
    """INVARIANT: Files outside linear/ are excluded from detected changes."""
    diff_output = "M\tREADME.md\nM\tlinear/teams/AI/issues/AI-1-fix-bug.md\n"

    issue_dir = tmp_path / "linear" / "teams" / "AI" / "issues"
    issue_dir.mkdir(parents=True)
    (issue_dir / "AI-1-fix-bug.md").write_text("content")

    mock_diff = MagicMock(stdout=diff_output, returncode=0)
    mock_show = MagicMock(stdout="old", returncode=0)

    def fake_run(cmd, **kwargs):
        if "diff" in cmd:
            return mock_diff
        if "show" in cmd:
            return mock_show
        return MagicMock(returncode=0)

    with patch.object(subprocess, "run", side_effect=fake_run):
        changes = push_mod.detect_git_changes(tmp_path)

    assert len(changes) == 1
    assert changes[0].path == "linear/teams/AI/issues/AI-1-fix-bug.md"


def test_detect_git_changes_handles_renamed_files(tmp_path):
    """INVARIANT: Renamed files (R status) are treated as modified."""
    issue_dir = tmp_path / "linear" / "teams" / "AI" / "issues"
    issue_dir.mkdir(parents=True)
    (issue_dir / "AI-1-new-name.md").write_text("content after rename")

    # Git shows renames as "R100\told_path\tnew_path"
    diff_output = "R100\tlinear/teams/AI/issues/AI-1-old-name.md\tlinear/teams/AI/issues/AI-1-new-name.md\n"
    mock_diff = MagicMock(stdout=diff_output, returncode=0)
    mock_show = MagicMock(stdout="old content", returncode=0)

    def fake_run(cmd, **kwargs):
        if "diff" in cmd:
            return mock_diff
        if "show" in cmd:
            return mock_show
        return MagicMock(returncode=0)

    with patch.object(subprocess, "run", side_effect=fake_run):
        changes = push_mod.detect_git_changes(tmp_path)

    assert len(changes) == 1
    assert changes[0].path == "linear/teams/AI/issues/AI-1-new-name.md"
    assert changes[0].change_type == "modified"


# Tests for push_command CLI integration

def test_push_command_calls_detect_and_push(tmp_path):
    """INVARIANT: push CLI command detects changes and pushes them."""
    fake_changes = [push_mod.FileChange(
        path="linear/teams/AI/issues/AI-1-fix-bug.md",
        change_type="modified",
        old_content="old",
        new_content="new",
    )]

    with patch.object(push_mod, "detect_git_changes", return_value=fake_changes) as mock_detect, \
         patch.object(push_mod, "push_changes", new_callable=AsyncMock, return_value={"updated": 1, "archived": 0, "created": 0, "skipped": 0}) as mock_push:
        runner = CliRunner()
        result = runner.invoke(cli, ["push", "--api-key", "test-key", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0
    mock_detect.assert_called_once_with(tmp_path)
    mock_push.assert_called_once()


def test_push_command_no_changes(tmp_path):
    """INVARIANT: When no changes detected, push outputs a message and exits cleanly."""
    with patch.object(push_mod, "detect_git_changes", return_value=[]):
        runner = CliRunner()
        result = runner.invoke(cli, ["push", "--api-key", "test-key", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "no changes" in result.output.lower() or "0" in result.output


@pytest.mark.asyncio
async def test_push_maps_field_names_to_linear_api(tmp_path):
    """INVARIANT: Frontmatter field 'title' maps to Linear API field 'title' in the update call."""
    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/teams/AI/issues/AI-1-fix-bug.md", "uuid-ai-1")
    state.save()

    old_content = _write_issue_md(tmp_path, "AI-1", "Fix bug", status="Todo").read_text()
    new_content = _write_issue_md(tmp_path, "AI-1", "Fix bug v2", status="Todo").read_text()

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
    call_args = mock_client.update_issue.call_args
    fields = call_args[0][1]
    # Should use Linear API field name 'title', not frontmatter key
    assert "title" in fields
    assert fields["title"] == "Fix bug v2"


@pytest.mark.asyncio
async def test_push_maps_description_field_correctly(tmp_path):
    """INVARIANT: Body changes map to 'description' in the Linear update call."""
    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/teams/AI/issues/AI-1-fix-bug.md", "uuid-ai-1")
    state.save()

    old_content = _write_issue_md(tmp_path, "AI-1", "Fix bug", body="Original text.").read_text()
    new_content = _write_issue_md(tmp_path, "AI-1", "Fix bug", body="Updated text.").read_text()

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

    call_args = mock_client.update_issue.call_args
    fields = call_args[0][1]
    assert "description" in fields
    assert "Updated text." in fields["description"]


@pytest.mark.asyncio
async def test_push_resolves_status_to_state_id(tmp_path):
    """INVARIANT: Status field changes resolve the state name to a stateId via API."""
    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/teams/AI/issues/AI-1-fix-bug.md", "uuid-ai-1")
    state.save()

    old_content = _write_issue_md(tmp_path, "AI-1", "Fix bug", status="Todo").read_text()
    new_content = _write_issue_md(tmp_path, "AI-1", "Fix bug", status="Done").read_text()

    changes = [push_mod.FileChange(
        path="linear/teams/AI/issues/AI-1-fix-bug.md",
        change_type="modified",
        old_content=old_content,
        new_content=new_content,
    )]

    mock_client = AsyncMock()
    mock_client.update_issue.return_value = {"id": "uuid-ai-1"}
    mock_client.fetch_teams.return_value = [
        {"id": "team-ai", "name": "AI", "key": "AI"},
    ]
    mock_client.fetch_team_states.return_value = [
        {"id": "state-todo", "name": "Todo", "type": "backlog"},
        {"id": "state-done", "name": "Done", "type": "completed"},
    ]
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(push_mod, "LinearClient", return_value=mock_client):
        result = await push_mod.push_changes(changes, "test-key", tmp_path)

    assert result["updated"] == 1
    mock_client.update_issue.assert_called_once()
    call_args = mock_client.update_issue.call_args
    fields = call_args[0][1]
    assert "stateId" in fields
    assert fields["stateId"] == "state-done"


@pytest.mark.asyncio
async def test_push_resolves_assignee_to_user_id(tmp_path):
    """INVARIANT: Assignee field changes resolve the user name to an assigneeId via API."""
    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/teams/AI/issues/AI-1-fix-bug.md", "uuid-ai-1")
    state.save()

    # Write issue with different assignee (need to manually create since helper doesn't support assignee)
    from issueclaw.paths import entity_path
    rel_path = entity_path("issue", team_key="AI", identifier="AI-1", issue_title="Fix bug")
    full_path = tmp_path / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)

    old_md = """---
id: uuid-ai-1
identifier: AI-1
title: Fix bug
status: Todo
priority: 2
assignee: Aviad Rozenhek
created: '2026-01-01T00:00:00Z'
updated: '2026-01-01T00:00:00Z'
url: https://linear.app/test
---

# AI-1: Fix bug

Description.
"""
    new_md = old_md.replace("assignee: Aviad Rozenhek", "assignee: Oz Shaked")
    full_path.write_text(new_md)

    changes = [push_mod.FileChange(
        path=rel_path,
        change_type="modified",
        old_content=old_md,
        new_content=new_md,
    )]

    mock_client = AsyncMock()
    mock_client.update_issue.return_value = {"id": "uuid-ai-1"}
    mock_client.fetch_users.return_value = [
        {"id": "user-aviad", "name": "Aviad Rozenhek", "email": "aviad@test.com"},
        {"id": "user-oz", "name": "Oz Shaked", "email": "oz@test.com"},
    ]
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(push_mod, "LinearClient", return_value=mock_client):
        result = await push_mod.push_changes(changes, "test-key", tmp_path)

    assert result["updated"] == 1
    call_args = mock_client.update_issue.call_args
    fields = call_args[0][1]
    assert "assigneeId" in fields
    assert fields["assigneeId"] == "user-oz"


@pytest.mark.asyncio
async def test_push_strips_entity_heading_from_description(tmp_path):
    """INVARIANT: The entity heading (# AI-1: Title) is stripped before sending to Linear API.

    Linear generates this heading itself — sending it back creates duplicates.
    """
    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/teams/AI/issues/AI-1-fix-bug.md", "uuid-ai-1")
    state.save()

    old_content = _write_issue_md(tmp_path, "AI-1", "Fix bug", body="Original.").read_text()
    new_content = _write_issue_md(tmp_path, "AI-1", "Fix bug", body="Updated body.").read_text()

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
        await push_mod.push_changes(changes, "test-key", tmp_path)

    call_args = mock_client.update_issue.call_args
    fields = call_args[0][1]
    # The description should NOT contain the entity heading
    assert "# AI-1:" not in fields["description"]
    assert "Updated body." in fields["description"]


@pytest.mark.asyncio
async def test_push_new_update_file(tmp_path):
    """INVARIANT: New update files under projects/*/updates/ push to Linear API."""
    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/projects/weekly-reports/_project.md", "uuid-weekly-reports")
    state.save()

    update_content = """---
id: new-update-uuid
author: Aviad Rozenhek
health: onTrack
created: '2026-03-13T21:00:00Z'
---

Weekly report: 24 shipped, 27 in flight.
"""
    update_path = "linear/projects/weekly-reports/updates/2026-03-13-aviad-rozenhek.md"
    full_path = tmp_path / update_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(update_content)

    changes = [push_mod.FileChange(
        path=update_path,
        change_type="added",
        old_content=None,
        new_content=update_content,
    )]

    mock_client = AsyncMock()
    mock_client.create_project_update.return_value = {"id": "new-update-uuid"}
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(push_mod, "LinearClient", return_value=mock_client):
        result = await push_mod.push_changes(changes, "test-key", tmp_path)

    assert result["created"] == 1
    mock_client.create_project_update.assert_called_once()
    call_args = mock_client.create_project_update.call_args
    assert call_args[0][0] == "uuid-weekly-reports"
    assert "24 shipped" in call_args[0][1]
    assert call_args[0][2] == "onTrack"


@pytest.mark.asyncio
async def test_push_update_file_without_project_mapping_is_skipped(tmp_path):
    """INVARIANT: Update files for unknown projects are skipped."""
    state = SyncState(tmp_path)
    state.load()
    state.save()

    update_content = """---
id: orphan-update
author: Aviad
health: onTrack
---

Some content.
"""
    changes = [push_mod.FileChange(
        path="linear/projects/unknown-project/updates/2026-03-13-aviad.md",
        change_type="added",
        old_content=None,
        new_content=update_content,
    )]

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(push_mod, "LinearClient", return_value=mock_client):
        result = await push_mod.push_changes(changes, "test-key", tmp_path)

    assert result["skipped"] == 1
    mock_client.create_project_update.assert_not_called()
