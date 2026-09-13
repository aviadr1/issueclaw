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
        owner = self.get_uuid(path)
        if owner is not None and owner != uuid:
            raise ValueError("Mirror path belongs to another entity")
        self._path_to_uuid[path] = uuid
        self._uuid_to_path[uuid] = path

    def remove_mapping(self, path: str) -> None:
        """Remove a mapping by file path."""
        uuid = self._path_to_uuid.pop(path, None)
        if uuid:
            self._uuid_to_path.pop(uuid, None)
            remaining = self.get_paths(uuid)
            if remaining:
                self._uuid_to_path[uuid] = remaining[-1]

    def get_paths(self, uuid: str) -> list[str]:
        """Return all historical paths; legacy mirrors can contain aliases."""
        return [path for path, owner in self._path_to_uuid.items() if owner == uuid]

    def _mirror_path(self, relative: str) -> Path:
        path = self._repo_root / relative
        if not relative.startswith("linear/") or not path.resolve().is_relative_to(
            self._repo_root.resolve()
        ):
            raise ValueError("Entity path escapes the mirror")
        return path

    def remove_entity(self, uuid: str) -> None:
        """Authoritative deletion removes every owned alias, never another identity."""
        paths = [(p, self._mirror_path(p)) for p in self.get_paths(uuid)]
        for relative, path in paths:
            path.unlink(missing_ok=True)
            self.remove_mapping(relative)

    def write_entity(self, relative: str, uuid: str, content: str) -> None:
        """Converge to one path; reject ownership/content ambiguity before writing.

        Comparing historical aliases prevents silent loss of divergent pending
        edits. Such identities require an explicit conflict resolution first.
        """
        target = self._mirror_path(relative)
        owner = self.get_uuid(relative)
        if owner is not None and owner != uuid:
            raise ValueError("Mirror path belongs to another entity")
        if owner is None and target.exists():
            raise ValueError("Refusing to overwrite an unmapped mirror file")
        paths = [(p, self._mirror_path(p)) for p in self.get_paths(uuid)]
        snapshots = {p.read_bytes() for _, p in paths if p.is_file()}
        if len(snapshots) > 1:
            raise ValueError("Conflicting identity aliases require explicit resolution")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        for old_relative, old_path in paths:
            if old_relative != relative:
                old_path.unlink(missing_ok=True)
                self.remove_mapping(old_relative)
        self.add_mapping(relative, uuid)

    def get_uuid(self, path: str) -> str | None:
        """Look up a UUID by file path."""
        return self._path_to_uuid.get(path)

    def get_path(self, uuid: str) -> str | None:
        """Look up a file path by UUID."""
        return self._uuid_to_path.get(uuid)

    def set_last_sync(self, timestamp: str) -> None:
        """Record the last sync timestamp."""
        self.last_sync = timestamp
