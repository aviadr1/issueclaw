"""Manage .sync/id-map.json and .sync/state.json."""

from __future__ import annotations

import json
from pathlib import Path


class SyncState:
    """Manages sync state: file path <-> Linear UUID mappings and timestamps."""

    def __init__(self, repo_root: Path | str) -> None:
        self._repo_root = Path(repo_root)
        self._sync_dir = self._repo_root / ".sync"
        self._id_map_file = self._sync_dir / "id-map.json"
        self._state_file = self._sync_dir / "state.json"
        # path -> uuid
        self._path_to_uuid: dict[str, str] = {}
        # uuid -> path
        self._uuid_to_path: dict[str, str] = {}
        # Timestamps
        self.last_sync: str | None = None

    def load(self) -> None:
        """Load state from disk. No-op if files don't exist."""
        if self._id_map_file.exists():
            data = json.loads(self._id_map_file.read_text())
            self._path_to_uuid = data
            self._uuid_to_path = {v: k for k, v in data.items()}

        if self._state_file.exists():
            data = json.loads(self._state_file.read_text())
            self.last_sync = data.get("last_sync")

    def save(self) -> None:
        """Persist state to disk."""
        self._sync_dir.mkdir(parents=True, exist_ok=True)

        self._id_map_file.write_text(
            json.dumps(self._path_to_uuid, indent=2, ensure_ascii=False) + "\n"
        )

        state_data = {}
        if self.last_sync is not None:
            state_data["last_sync"] = self.last_sync
        self._state_file.write_text(
            json.dumps(state_data, indent=2, ensure_ascii=False) + "\n"
        )

    def add_mapping(self, path: str, uuid: str) -> None:
        """Add a file path <-> UUID mapping."""
        self._path_to_uuid[path] = uuid
        self._uuid_to_path[uuid] = path

    def remove_mapping(self, path: str) -> None:
        """Remove a mapping by file path."""
        uuid = self._path_to_uuid.pop(path, None)
        if uuid:
            self._uuid_to_path.pop(uuid, None)

    def get_uuid(self, path: str) -> str | None:
        """Look up a UUID by file path."""
        return self._path_to_uuid.get(path)

    def get_path(self, uuid: str) -> str | None:
        """Look up a file path by UUID."""
        return self._uuid_to_path.get(uuid)

    def set_last_sync(self, timestamp: str) -> None:
        """Record the last sync timestamp."""
        self.last_sync = timestamp
