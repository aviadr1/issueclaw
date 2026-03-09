import json

from issueclaw.sync_state import SyncState


def test_id_map_add_and_lookup(tmp_path):
    """INVARIANT: id-map maps file paths to Linear UUIDs bidirectionally."""
    state = SyncState(tmp_path)
    state.add_mapping("linear/teams/AI/issues/AI-123.md", "uuid-123")
    assert state.get_uuid("linear/teams/AI/issues/AI-123.md") == "uuid-123"
    assert state.get_path("uuid-123") == "linear/teams/AI/issues/AI-123.md"


def test_id_map_persistence(tmp_path):
    """INVARIANT: id-map persists to disk and survives reload."""
    state = SyncState(tmp_path)
    state.add_mapping("linear/teams/AI/issues/AI-123.md", "uuid-123")
    state.save()

    state2 = SyncState(tmp_path)
    state2.load()
    assert state2.get_uuid("linear/teams/AI/issues/AI-123.md") == "uuid-123"
    assert state2.get_path("uuid-123") == "linear/teams/AI/issues/AI-123.md"


def test_id_map_remove(tmp_path):
    """INVARIANT: Removing a mapping clears both directions."""
    state = SyncState(tmp_path)
    state.add_mapping("linear/teams/AI/issues/AI-123.md", "uuid-123")
    state.remove_mapping("linear/teams/AI/issues/AI-123.md")
    assert state.get_uuid("linear/teams/AI/issues/AI-123.md") is None
    assert state.get_path("uuid-123") is None


def test_id_map_multiple_entries(tmp_path):
    """INVARIANT: id-map handles multiple entries independently."""
    state = SyncState(tmp_path)
    state.add_mapping("linear/teams/AI/issues/AI-1.md", "uuid-1")
    state.add_mapping("linear/teams/AI/issues/AI-2.md", "uuid-2")
    state.add_mapping("linear/projects/foo/_project.md", "uuid-3")
    assert state.get_uuid("linear/teams/AI/issues/AI-1.md") == "uuid-1"
    assert state.get_uuid("linear/teams/AI/issues/AI-2.md") == "uuid-2"
    assert state.get_uuid("linear/projects/foo/_project.md") == "uuid-3"


def test_state_json_timestamps(tmp_path):
    """INVARIANT: state.json tracks last sync timestamp."""
    state = SyncState(tmp_path)
    state.set_last_sync("2026-03-09T12:00:00Z")
    state.save()

    state2 = SyncState(tmp_path)
    state2.load()
    assert state2.last_sync == "2026-03-09T12:00:00Z"


def test_load_empty_state(tmp_path):
    """INVARIANT: Loading non-existent state files gives clean defaults."""
    state = SyncState(tmp_path)
    state.load()
    assert state.get_uuid("nonexistent") is None
    assert state.last_sync is None


def test_sync_dir_created_on_save(tmp_path):
    """INVARIANT: Save creates .sync directory if it does not exist."""
    sync_dir = tmp_path / ".sync"
    assert not sync_dir.exists()
    state = SyncState(tmp_path)
    state.add_mapping("test.md", "uuid")
    state.save()
    assert sync_dir.exists()
    assert (sync_dir / "id-map.json").exists()
    assert (sync_dir / "state.json").exists()
