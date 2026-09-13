"""Prepare existing webhook behavior in an isolated, minimal entity workspace."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil

from issueclaw.commands.apply_webhook import apply_webhook
from issueclaw.sync_state import SyncState


@dataclass(frozen=True)
class FileChange:
    path: str
    content: bytes | None


def checked_path(root: Path, relative: str) -> Path:
    path = root / relative
    if not (
        relative.startswith("linear/") or relative.startswith(".sync/")
    ) or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Entity path escapes the mirror")
    return path


async def prepare_entity(payload: dict, api_key: str, repo: Path) -> list[FileChange]:
    """Reuse authoritative parsers/renderers; failed keys cannot leak partial writes.

    Copy only mapping metadata and this entity's existing file, not the entire
    mirror. TemporaryDirectory owns cleanup immediately, including cancellation.
    """
    state = SyncState(repo)
    state.load()
    entity_id = payload["data"]["id"]
    paths = [".sync/id-map.json", ".sync/state.json"]
    old_path = state.get_path(entity_id)
    if old_path:
        paths.append(old_path)
    with TemporaryDirectory(prefix="issueclaw-entity-") as directory:
        scratch = Path(directory)
        before = {}
        for relative in paths:
            source = checked_path(repo, relative)
            if source.is_file():
                before[relative] = source.read_bytes()
                target = checked_path(scratch, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        result = await apply_webhook(payload, api_key, scratch)
        if result["action"] == "skip":
            raise ValueError("Unsupported event retained")
        after = {
            str(p.relative_to(scratch)): p.read_bytes()
            for p in scratch.rglob("*")
            if p.is_file()
        }
        changes = []
        for relative in sorted(before.keys() | after.keys()):
            checked_path(repo, relative)
            owner = state.get_uuid(relative)
            if relative.startswith("linear/") and owner and owner != entity_id:
                raise ValueError("Rendered path belongs to another entity")
            content = after.get(relative)
            if before.get(relative) != content:
                changes.append(FileChange(relative, content))
        return changes


def apply_changes(repo: Path, changes: list[FileChange]) -> None:
    """Disk failures abort the whole publication; never ACK partly written files."""
    for change in changes:
        path = checked_path(repo, change.path)
        if change.content is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(change.content)
