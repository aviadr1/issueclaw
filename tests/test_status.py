"""Tests for the status command."""

from click.testing import CliRunner

from issueclaw.main import cli
from issueclaw.sync_state import SyncState


def test_status_shows_entity_counts(tmp_path):
    """INVARIANT: Status command shows counts of synced entities by type."""
    # Set up sync state with some mappings
    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/teams/AI/issues/AI-1-fix-bug.md", "uuid-1")
    state.add_mapping("linear/teams/AI/issues/AI-2-add-feature.md", "uuid-2")
    state.add_mapping("linear/teams/ENG/issues/ENG-1-refactor.md", "uuid-3")
    state.add_mapping("linear/projects/metrics/_project.md", "uuid-4")
    state.add_mapping("linear/initiatives/q1-roadmap.md", "uuid-5")
    state.add_mapping("linear/documents/arch-overview.md", "uuid-6")
    state.set_last_sync("2026-03-09T12:00:00Z")
    state.save()

    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "3" in result.output  # 3 issues
    assert "1" in result.output  # 1 project
    assert "issues" in result.output.lower()
    assert "project" in result.output.lower()


def test_status_shows_last_sync(tmp_path):
    """INVARIANT: Status command shows the last sync timestamp."""
    state = SyncState(tmp_path)
    state.load()
    state.set_last_sync("2026-03-09T12:00:00Z")
    state.save()

    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "2026-03-09" in result.output


def test_status_no_sync_state(tmp_path):
    """INVARIANT: Status command handles missing sync state gracefully."""
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert (
        "no sync" in result.output.lower() or "not initialized" in result.output.lower()
    )


def test_status_json_mode(tmp_path):
    """INVARIANT: Status command outputs valid JSON in json mode."""
    import json

    state = SyncState(tmp_path)
    state.load()
    state.add_mapping("linear/teams/AI/issues/AI-1-fix.md", "uuid-1")
    state.add_mapping("linear/projects/p1/_project.md", "uuid-2")
    state.set_last_sync("2026-03-09T12:00:00Z")
    state.save()

    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "status", "--repo-dir", str(tmp_path)])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "issues" in data
    assert "projects" in data
    assert "last_sync" in data
