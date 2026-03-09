"""Push command: detect git changes and push updates to Linear API."""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from issueclaw.diff import diff_markdown
from issueclaw.linear_client import LinearClient
from issueclaw.paths import parse_entity_path
from issueclaw.sync_state import SyncState


# Mapping from frontmatter field names to Linear API field names
_ISSUE_FIELD_MAP = {
    "title": "title",
    "status": "stateId",  # requires resolution
    "priority": "priority",
    "assignee": "assigneeId",  # requires resolution
    "estimate": "estimate",
    "due_date": "dueDate",
}


@dataclass
class FileChange:
    """A single file change detected from git diff."""

    path: str
    change_type: str  # "added", "modified", "deleted"
    old_content: str | None = None
    new_content: str | None = None


async def push_changes(
    changes: list[FileChange],
    api_key: str,
    repo_dir: Path,
) -> dict:
    """Push file changes to the Linear API.

    Returns stats dict with counts of updated, archived, skipped entities.
    """
    stats = {"updated": 0, "archived": 0, "created": 0, "skipped": 0}

    if not changes:
        return stats

    state = SyncState(repo_dir)
    state.load()

    # Filter to only linear/ files
    linear_changes = []
    for change in changes:
        if change.path.startswith("linear/"):
            linear_changes.append(change)
        else:
            stats["skipped"] += 1

    if not linear_changes:
        return stats

    async with LinearClient(api_key=api_key) as client:
        for change in linear_changes:
            entity_info = parse_entity_path(change.path)
            if not entity_info:
                stats["skipped"] += 1
                continue

            entity_type = entity_info["type"]
            entity_id = state.get_uuid(change.path)

            if change.change_type == "deleted":
                if entity_id and entity_type == "issue":
                    await client.archive_issue(entity_id)
                    state.remove_mapping(change.path)
                    stats["archived"] += 1
                else:
                    stats["skipped"] += 1
                continue

            if change.change_type == "modified" and change.old_content and change.new_content:
                diff = diff_markdown(change.old_content, change.new_content)
                if not diff.has_changes:
                    stats["skipped"] += 1
                    continue

                if entity_type == "issue" and entity_id:
                    # Build update fields from frontmatter changes
                    update_fields: dict[str, Any] = {}
                    for field_name, field_diff in diff.frontmatter_changes.items():
                        if field_name not in _ISSUE_FIELD_MAP or field_diff.new is None:
                            continue
                        api_field = _ISSUE_FIELD_MAP[field_name]
                        # Skip fields that need ID resolution (stateId, assigneeId)
                        if api_field.endswith("Id"):
                            continue
                        update_fields[api_field] = field_diff.new

                    # Include body changes
                    if diff.body_changed:
                        update_fields["description"] = diff.new_body.strip()

                    if update_fields:
                        await client.update_issue(entity_id, update_fields)

                    # Handle new comments
                    for comment in diff.comments_added:
                        await client.create_comment(entity_id, comment.body)

                    stats["updated"] += 1
                else:
                    stats["skipped"] += 1

    state.save()
    return stats


def detect_git_changes(repo_dir: Path) -> list[FileChange]:
    """Detect file changes in linear/ by comparing HEAD~1 to HEAD using git diff.

    Returns a list of FileChange objects with old/new content for each changed file.
    """
    result = subprocess.run(
        ["git", "diff", "HEAD~1", "--name-status", "--", "linear/"],
        capture_output=True,
        text=True,
        cwd=repo_dir,
    )
    if result.returncode != 0:
        return []

    changes: list[FileChange] = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue

        parts = line.split("\t")
        status = parts[0]

        if status.startswith("R"):
            # Rename: R100\told_path\tnew_path
            old_path = parts[1]
            new_path = parts[2]
            if not new_path.startswith("linear/"):
                continue
            old_content = _git_show(repo_dir, f"HEAD~1:{old_path}")
            new_content = (repo_dir / new_path).read_text()
            changes.append(FileChange(
                path=new_path,
                change_type="modified",
                old_content=old_content,
                new_content=new_content,
            ))
        elif status == "M":
            file_path = parts[1]
            if not file_path.startswith("linear/"):
                continue
            old_content = _git_show(repo_dir, f"HEAD~1:{file_path}")
            new_content = (repo_dir / file_path).read_text()
            changes.append(FileChange(
                path=file_path,
                change_type="modified",
                old_content=old_content,
                new_content=new_content,
            ))
        elif status == "D":
            file_path = parts[1]
            if not file_path.startswith("linear/"):
                continue
            old_content = _git_show(repo_dir, f"HEAD~1:{file_path}")
            changes.append(FileChange(
                path=file_path,
                change_type="deleted",
                old_content=old_content,
                new_content=None,
            ))
        elif status == "A":
            file_path = parts[1]
            if not file_path.startswith("linear/"):
                continue
            new_content = (repo_dir / file_path).read_text()
            changes.append(FileChange(
                path=file_path,
                change_type="added",
                old_content=None,
                new_content=new_content,
            ))

    return changes


def _git_show(repo_dir: Path, ref_path: str) -> str:
    """Get file content from a git ref (e.g., HEAD~1:path/to/file)."""
    result = subprocess.run(
        ["git", "show", ref_path],
        capture_output=True,
        text=True,
        cwd=repo_dir,
    )
    return result.stdout


@click.command("push")
@click.option(
    "--api-key",
    envvar="LINEAR_API_KEY",
    default=None,
    help="Linear API key. Defaults to LINEAR_API_KEY env var.",
)
@click.option(
    "--repo-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Path to the target repository.",
)
@click.pass_context
def push_command(ctx: click.Context, api_key: str | None, repo_dir: Path) -> None:
    """Push local markdown changes to Linear."""
    if not api_key:
        raise click.UsageError("API key required. Use --api-key or set LINEAR_API_KEY env var.")

    json_mode = ctx.obj.get("json", False) if ctx.obj else False

    changes = detect_git_changes(repo_dir)

    if not changes:
        if json_mode:
            click.echo(json.dumps({"updated": 0, "archived": 0, "created": 0, "skipped": 0}))
        else:
            click.echo("No changes detected in linear/ files.")
        return

    stats = asyncio.run(push_changes(changes, api_key, repo_dir))

    if json_mode:
        click.echo(json.dumps(stats))
    else:
        click.echo(f"Push complete: {stats['updated']} updated, {stats['archived']} archived, {stats['skipped']} skipped.")
