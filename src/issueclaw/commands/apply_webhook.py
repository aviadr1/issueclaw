"""Apply a Linear webhook payload to the local repository."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import click

from issueclaw.linear_client import LinearClient
from issueclaw.models import (
    LinearComment,
    LinearDocument,
    LinearInitiative,
    LinearIssue,
    LinearProject,
)
from issueclaw.paths import entity_path, slugify
from issueclaw.render import render_document, render_initiative, render_issue, render_project
from issueclaw.sync_state import SyncState


_SUPPORTED_TYPES = {"Issue", "Comment", "Project", "Initiative", "Document"}


async def apply_webhook(
    payload: dict,
    api_key: str,
    repo_dir: Path,
) -> dict:
    """Apply a single webhook payload to the repo.

    Returns a result dict with action taken and entity info.
    """
    action = payload.get("action", "")
    entity_type = payload.get("type", "")
    entity_id = payload["data"]["id"]

    if entity_type not in _SUPPORTED_TYPES:
        return {"action": "skip", "entity_type": entity_type, "reason": "unsupported type"}

    state = SyncState(repo_dir)
    state.load()

    # Remove action: delete the file using the id-map
    if action == "remove":
        return _handle_remove(entity_id, entity_type, state, repo_dir)

    # For comments, re-fetch the parent issue
    if entity_type == "Comment":
        issue_id = payload["data"].get("issueId")
        if not issue_id:
            return {"action": "skip", "entity_type": entity_type, "reason": "no issueId"}
        return await _handle_comment(issue_id, api_key, state, repo_dir)

    # Create/update: fetch full entity via API and render
    return await _handle_create_or_update(action, entity_type, entity_id, api_key, state, repo_dir)


def _handle_remove(entity_id: str, entity_type: str, state: SyncState, repo_dir: Path) -> dict:
    """Delete the file associated with an entity."""
    old_path = state.get_path(entity_id)
    if old_path:
        full_path = repo_dir / old_path
        if full_path.exists():
            full_path.unlink()
        state.remove_mapping(old_path)
        state.save()
    return {"action": "remove", "entity_type": entity_type, "entity_id": entity_id}


async def _handle_comment(
    issue_id: str, api_key: str, state: SyncState, repo_dir: Path,
) -> dict:
    """Re-fetch the parent issue and re-render its file (with updated comments)."""
    async with LinearClient(api_key=api_key) as client:
        raw_issue = await client.fetch_issue(issue_id)
    return _write_issue(raw_issue, state, repo_dir, action="update", entity_type="Comment")


async def _handle_create_or_update(
    action: str, entity_type: str, entity_id: str,
    api_key: str, state: SyncState, repo_dir: Path,
) -> dict:
    """Fetch the full entity and render it to a markdown file."""
    async with LinearClient(api_key=api_key) as client:
        if entity_type == "Issue":
            raw = await client.fetch_issue(entity_id)
            return _write_issue(raw, state, repo_dir, action=action, entity_type=entity_type)

        elif entity_type == "Project":
            raw = await client.fetch_project(entity_id)
            project = LinearProject.from_api(raw)
            path = entity_path("project", slug=project.slug)
            content = render_project(project)

        elif entity_type == "Initiative":
            raw = await client.fetch_initiative(entity_id)
            initiative = LinearInitiative.from_api(raw)
            path = entity_path("initiative", name=initiative.name)
            content = render_initiative(initiative)

        elif entity_type == "Document":
            raw = await client.fetch_document(entity_id)
            doc = LinearDocument.from_api(raw)
            path = entity_path("document", title=doc.title)
            content = render_document(doc)

        else:
            return {"action": "skip", "entity_type": entity_type, "reason": "unhandled type"}

    # Clean up old file if path changed
    _cleanup_old_path(entity_id, path, state, repo_dir)

    full_path = repo_dir / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)

    state.add_mapping(path, entity_id)
    state.save()

    return {"action": action, "entity_type": entity_type, "entity_id": entity_id, "path": path}


def _write_issue(raw: dict, state: SyncState, repo_dir: Path, action: str, entity_type: str) -> dict:
    """Parse, render, and write an issue file. Handles team key extraction."""
    team_data = raw.get("team") or {}
    team_key = team_data.get("key", "UNKNOWN")
    entity_id = raw["id"]

    # Parse issue (reusing pull.py's logic)
    from issueclaw.commands.pull import _parse_issue
    issue = _parse_issue(raw, team_key)

    # Parse inline comments
    raw_comments = (raw.get("comments") or {}).get("nodes", [])
    issue.comments = [LinearComment.from_api(c) for c in raw_comments]

    path = entity_path("issue", team_key=team_key, identifier=issue.identifier, issue_title=issue.title)
    content = render_issue(issue)

    # Clean up old file if path changed (e.g., title rename)
    _cleanup_old_path(entity_id, path, state, repo_dir)

    full_path = repo_dir / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)

    state.add_mapping(path, entity_id)
    state.save()

    return {"action": action, "entity_type": entity_type, "entity_id": entity_id, "path": path}


def _cleanup_old_path(entity_id: str, new_path: str, state: SyncState, repo_dir: Path) -> None:
    """If the entity was previously at a different path, remove the old file."""
    old_path = state.get_path(entity_id)
    if old_path and old_path != new_path:
        old_full = repo_dir / old_path
        if old_full.exists():
            old_full.unlink()
        state.remove_mapping(old_path)


@click.command("apply-webhook")
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
@click.option(
    "--payload",
    envvar="WEBHOOK_PAYLOAD",
    default=None,
    help="Webhook payload JSON. Defaults to WEBHOOK_PAYLOAD env var.",
)
@click.pass_context
def apply_webhook_command(ctx: click.Context, api_key: str | None, repo_dir: Path, payload: str | None) -> None:
    """Apply a Linear webhook payload to update repository files."""
    if not api_key:
        raise click.UsageError("API key required. Use --api-key or set LINEAR_API_KEY env var.")
    if not payload:
        raise click.UsageError("Webhook payload required. Use --payload or set WEBHOOK_PAYLOAD env var.")

    parsed = json.loads(payload)
    json_mode = ctx.obj.get("json", False) if ctx.obj else False

    result = asyncio.run(apply_webhook(parsed, api_key, repo_dir))

    if json_mode:
        click.echo(json.dumps(result))
    else:
        action = result.get("action", "unknown")
        entity_type = result.get("entity_type", "unknown")
        path = result.get("path", "")
        if action == "skip":
            click.echo(f"Skipped: {entity_type} ({result.get('reason', '')})")
        elif action == "remove":
            click.echo(f"Removed: {entity_type} {result.get('entity_id', '')}")
        else:
            click.echo(f"{action.title()}d: {entity_type} -> {path}")
