"""Tests for the diff preview command."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from issueclaw.commands import diff_cmd as diff_mod
from issueclaw.commands import push as push_mod
from issueclaw.main import cli


def test_diff_shows_changed_files(tmp_path):
    """INVARIANT: Diff command lists changed linear/ files with change types."""
    fake_changes = [
        push_mod.FileChange(
            path="linear/teams/AI/issues/AI-1-fix-bug.md",
            change_type="modified",
            old_content="old",
            new_content="new",
        ),
        push_mod.FileChange(
            path="linear/teams/AI/issues/AI-2-new.md",
            change_type="added",
            old_content=None,
            new_content="new file",
        ),
    ]

    with patch.object(diff_mod, "detect_git_changes", return_value=fake_changes):
        runner = CliRunner()
        result = runner.invoke(cli, ["diff", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "AI-1" in result.output
    assert "AI-2" in result.output
    assert "modified" in result.output.lower()
    assert "added" in result.output.lower()


def test_diff_shows_field_changes(tmp_path):
    """INVARIANT: Diff command shows which fields changed for modified files."""
    old_content = """---
id: uuid-1
identifier: AI-1
title: Fix bug
status: Todo
priority: 2
created: '2026-01-01T00:00:00Z'
updated: '2026-01-01T00:00:00Z'
url: https://linear.app/test
---

# AI-1: Fix bug

Original description.
"""
    new_content = old_content.replace("status: Todo", "status: Done").replace(
        "Original description.", "Updated description."
    )

    fake_changes = [
        push_mod.FileChange(
            path="linear/teams/AI/issues/AI-1-fix-bug.md",
            change_type="modified",
            old_content=old_content,
            new_content=new_content,
        ),
    ]

    with patch.object(diff_mod, "detect_git_changes", return_value=fake_changes):
        runner = CliRunner()
        result = runner.invoke(cli, ["diff", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "status" in result.output.lower()
    assert "Todo" in result.output
    assert "Done" in result.output


def test_diff_no_changes(tmp_path):
    """INVARIANT: Diff command reports no changes when none detected."""
    with patch.object(diff_mod, "detect_git_changes", return_value=[]):
        runner = CliRunner()
        result = runner.invoke(cli, ["diff", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "no changes" in result.output.lower()


def test_diff_json_mode(tmp_path):
    """INVARIANT: Diff command outputs JSON in json mode."""
    import json

    fake_changes = [
        push_mod.FileChange(
            path="linear/teams/AI/issues/AI-1-fix-bug.md",
            change_type="modified",
            old_content="---\nid: x\nstatus: Todo\n---\n\n# AI-1: T\n\nBody",
            new_content="---\nid: x\nstatus: Done\n---\n\n# AI-1: T\n\nBody",
        ),
    ]

    with patch.object(diff_mod, "detect_git_changes", return_value=fake_changes):
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "diff", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["path"] == "linear/teams/AI/issues/AI-1-fix-bug.md"
