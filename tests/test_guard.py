"""Tests for guard behavior that prevents misplaced new linear files."""

from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from issueclaw.commands import guard as guard_mod
from issueclaw.commands import push as push_mod
from issueclaw.main import cli
from issueclaw.sync_state import SyncState


def test_find_misplaced_added_files_allows_supported_creation_inputs(tmp_path):
    """INVARIANT: New issue queue/update files and mapped files are allowed."""
    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/initiatives/q1-roadmap.md", "init-uuid-1")
    state.save()

    changes = [
        push_mod.FileChange(
            path="linear/new/AI/new-auth-flow.md",
            change_type="added",
            new_content="---\ntitle: New auth flow\n---\n",
        ),
        push_mod.FileChange(
            path="linear/projects/auth/updates/2026-04-09-eng.md",
            change_type="added",
            new_content="Update body",
        ),
        push_mod.FileChange(
            path="linear/initiatives/q1-roadmap.md",
            change_type="added",
            new_content="Mapped canonical file",
        ),
    ]

    misplaced = push_mod.find_misplaced_added_files(changes, tmp_path)
    assert misplaced == []


def test_find_misplaced_added_files_flags_unmapped_canonical_additions(tmp_path):
    """INVARIANT: Unmapped canonical additions are flagged as misplaced."""
    changes = [
        push_mod.FileChange(
            path="linear/teams/AI/issues/new-auth-flow.md",
            change_type="added",
            new_content="new issue in wrong place",
        ),
        push_mod.FileChange(
            path="linear/documents/auth-rfc.md",
            change_type="added",
            new_content="new doc in wrong place",
        ),
    ]

    misplaced = push_mod.find_misplaced_added_files(changes, tmp_path)
    assert misplaced == [
        "linear/documents/auth-rfc.md",
        "linear/teams/AI/issues/new-auth-flow.md",
    ]


def test_push_command_fails_fast_on_misplaced_added_files(tmp_path):
    """INVARIANT: `issueclaw push` fails before API calls when additions are misplaced."""
    fake_changes = [
        push_mod.FileChange(
            path="linear/teams/AI/issues/new-auth-flow.md",
            change_type="added",
            new_content="new issue in wrong place",
        )
    ]

    with (
        patch.object(push_mod, "detect_git_changes", return_value=fake_changes),
        patch.object(
            push_mod,
            "push_changes",
            new_callable=AsyncMock,
            return_value={"updated": 0, "archived": 0, "created": 0, "skipped": 0},
        ) as mock_push,
    ):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["push", "--api-key", "test-key", "--repo-dir", str(tmp_path)]
        )

    assert result.exit_code != 0
    assert "Refusing to push" in result.output
    assert "linear/new/AI/new-auth-flow.md" in result.output
    mock_push.assert_not_called()


def test_guard_command_reports_misplaced_with_move_hint(tmp_path):
    """INVARIANT: `issueclaw guard` reports actionable move hints for likely issue files."""
    fake_changes = [
        push_mod.FileChange(
            path="linear/teams/AI/issues/new-auth-flow.md",
            change_type="added",
            new_content="new issue in wrong place",
        )
    ]

    with patch.object(guard_mod, "detect_git_changes", return_value=fake_changes):
        runner = CliRunner()
        result = runner.invoke(cli, ["guard", "--repo-dir", str(tmp_path)])

    assert result.exit_code != 0
    assert (
        "mv linear/teams/AI/issues/new-auth-flow.md "
        "linear/new/AI/new-auth-flow.md" in result.output
    )
