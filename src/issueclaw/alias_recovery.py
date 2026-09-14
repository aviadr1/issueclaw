"""Explicit, backup-verified recovery tooling; never used by ordinary replay.

Run in a dedicated local recovery checkout with no concurrent writer. Every
historical alias must already exist byte-for-byte in the verified remote backup.
Source failures restore the checkout; only successful preparation returns edits.
"""

import argparse
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import re
import time

from pydantic import TypeAdapter

from issueclaw.entity_changes import (
    FileChange,
    apply_changes,
    checked_path,
    prepare_entity,
)
from issueclaw.inbox_contract import WorkItem
from issueclaw.inbox_replay import git
from issueclaw.sync_state import IdentityConflict, SyncState


def verify_recovery(repo: Path, branch: str) -> str:
    """Require an actual remote recovery ref, not merely an unpushed local name."""
    if not branch.startswith("recovery/") or not re.fullmatch(
        r"[A-Za-z0-9_./-]+", branch
    ):
        raise ValueError("An explicit recovery branch is required")
    ref = "refs/heads/" + branch
    lines = git(repo, "ls-remote", "--heads", "origin", ref).splitlines()
    if len(lines) != 1 or lines[0].split()[1] != ref:
        raise ValueError("Remote recovery branch is missing or ambiguous")
    commit = lines[0].split()[0]
    git(repo, "cat-file", "-e", commit + "^{commit}")
    return commit


async def prepare_recovered_entity(
    item: WorkItem, repo: Path, api_key: str, recovery_commit: str
) -> list[FileChange]:
    """Prepare Linear-authoritative edits only for remotely preserved aliases.

    Temporarily equalize verified aliases in the dedicated recovery checkout so
    the unchanged production renderer can refresh them. Always restore originals
    before returning or raising. Compare final content with the real originals,
    not the temporary equalized bytes, including paths the renderer leaves alone.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", recovery_commit):
        raise ValueError("Recovery must be pinned to a verified commit")
    if item.payload.action not in ("create", "update"):
        raise ValueError("Alias recovery only refreshes current source content")
    state = SyncState(repo)
    state.load()
    originals = {}
    for relative in state.get_paths(item.payload.data["id"]):
        path = checked_path(repo, relative)
        if path.is_file():
            if git(repo, "hash-object", "--", str(path)) != git(
                repo, "rev-parse", f"{recovery_commit}:{relative}"
            ):
                raise ValueError(
                    "Historical alias is not preserved in the recovery commit"
                )
            originals[relative] = path.read_bytes()
    if len(set(originals.values())) < 2:
        raise ValueError("No divergent aliases to recover")
    normalized = next(iter(originals.values()))
    try:
        for relative in originals:
            checked_path(repo, relative).write_bytes(normalized)
        changes = await prepare_entity(item.payload.model_dump(), api_key, repo)
        final = {relative: normalized for relative in originals}
        final.update({change.path: change.content for change in changes})
    finally:
        # Includes source failures, timeout cancellation and KeyboardInterrupt.
        for relative, content in originals.items():
            checked_path(repo, relative).write_bytes(content)
    return [
        FileChange(path, content)
        for path, content in final.items()
        if path not in originals or content != originals[path]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", type=Path, required=True)
    parser.add_argument("--items-file", type=Path, required=True)
    parser.add_argument("--recovery-branch", required=True)
    parser.add_argument("--limit", type=int, choices=range(1, 26), default=25)
    args = parser.parse_args()
    repo = args.repo_dir.resolve()
    if git(repo, "branch", "--show-current") in ("main", "master", "") or git(
        repo, "status", "--porcelain"
    ):
        raise ValueError("Use a clean dedicated recovery branch, never main")
    recovery_commit = verify_recovery(repo, args.recovery_branch)
    items = TypeAdapter(list[WorkItem]).validate_json(args.items_file.read_text())

    async def recover() -> dict:
        outcomes = Counter()
        errors = Counter()
        deadline = time.monotonic() + 120
        for item in items:
            state = SyncState(repo)
            state.load()
            try:
                state.validate_aliases(item.payload.data["id"])
            except IdentityConflict:
                pass
            else:
                continue
            if sum(outcomes.values()) >= args.limit or time.monotonic() >= deadline:
                break
            try:
                changes = await asyncio.wait_for(
                    prepare_recovered_entity(
                        item, repo, os.environ["LINEAR_API_KEY"], recovery_commit
                    ),
                    timeout=min(20, deadline - time.monotonic()),
                )
            except Exception as error:
                outcomes["failed"] += 1
                errors[type(error).__name__] += 1
                continue
            # Disk failure is fatal. Never continue a partially applied change.
            apply_changes(repo, changes)
            outcomes["prepared"] += 1
        return {
            "outcomes": dict(outcomes),
            "error_types": dict(errors),
            "recovery_commit": recovery_commit,
            "published": False,
            "claimed": False,
            "acknowledged": False,
        }

    print(json.dumps(asyncio.run(recover())))


if __name__ == "__main__":
    main()
