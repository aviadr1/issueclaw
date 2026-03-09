"""Pull command: sync Linear data to local repository as markdown files."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import click
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from issueclaw.linear_client import LinearClient
from issueclaw.models import (
    LinearComment,
    LinearDocument,
    LinearInitiative,
    LinearIssue,
    LinearProject,
)
from issueclaw.paths import entity_path
from issueclaw.render import render_document, render_initiative, render_issue, render_project
from issueclaw.sync_state import SyncState

_console = Console(stderr=True)

def _default_log(msg: str) -> None:
    _console.print(msg)


def _noop_log(msg: str) -> None:
    pass


@contextmanager
def _progress_bar(description: str, total: int | None = None, enabled: bool = True):
    """Context manager for a rich progress bar. Yields an advance callback."""
    if not enabled or total is None:
        yield lambda: None
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=_console,
        transient=True,
    ) as progress:
        task = progress.add_task(description, total=total)
        yield lambda: progress.advance(task)


async def _run_pull(
    api_key: str,
    repo_dir: Path,
    teams_filter: list[str] | None,
    log: Callable[[str], None] = _default_log,
    show_progress: bool = True,
) -> dict:
    """Execute the pull sync operation.

    Returns a stats dict with counts of synced entities.
    """
    async with LinearClient(api_key=api_key) as client:
        state = SyncState(repo_dir)
        state.load()

        stats = {"issues": 0, "projects": 0, "initiatives": 0, "documents": 0}

        # Fetch teams
        log("Fetching teams...")
        teams = await client.fetch_teams()
        log(f"Found {len(teams)} teams")

        # Filter teams if specified
        if teams_filter:
            filter_set = {t.upper() for t in teams_filter}
            teams = [t for t in teams if t["key"].upper() in filter_set]
            log(f"Filtered to {len(teams)} teams: {', '.join(t['key'] for t in teams)}")

        # Sync issues per team
        for team in teams:
            team_key = team["key"]
            team_id = team["id"]

            log(f"Fetching issues for team {team_key}...")
            raw_issues = await client.fetch_issues(team_id, include_comments=True)
            log(f"  {len(raw_issues)} issues in {team_key}")

            with _progress_bar(f"Writing {team_key} issues", len(raw_issues), enabled=show_progress) as advance:
                for raw_issue in raw_issues:
                    issue = _parse_issue(raw_issue, team_key)
                    # Comments are included inline from the issue query
                    raw_comments = (raw_issue.get("comments") or {}).get("nodes", [])
                    issue.comments = [LinearComment.from_api(c) for c in raw_comments]

                    path = entity_path("issue", team_key=team_key, identifier=issue.identifier)
                    content = render_issue(issue)

                    full_path = repo_dir / path
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(content)

                    state.add_mapping(path, issue.id)
                    stats["issues"] += 1
                    advance()

            # Save after each team
            state.set_last_sync(datetime.now(timezone.utc).isoformat())
            state.save()
            log(f"  Saved ({stats['issues']} issues total)")

        # Sync projects
        log("Fetching projects...")
        raw_projects = await client.fetch_projects()
        log(f"  {len(raw_projects)} projects")
        for raw_proj in raw_projects:
            project = LinearProject.from_api(raw_proj)
            path = entity_path("project", slug=project.slug)
            content = render_project(project)

            full_path = repo_dir / path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)

            state.add_mapping(path, project.id)
            stats["projects"] += 1

        state.set_last_sync(datetime.now(timezone.utc).isoformat())
        state.save()

        # Sync initiatives
        log("Fetching initiatives...")
        raw_inits = await client.fetch_initiatives()
        log(f"  {len(raw_inits)} initiatives")
        for raw_init in raw_inits:
            initiative = LinearInitiative.from_api(raw_init)
            path = entity_path("initiative", name=initiative.name)
            content = render_initiative(initiative)

            full_path = repo_dir / path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)

            state.add_mapping(path, initiative.id)
            stats["initiatives"] += 1

        state.set_last_sync(datetime.now(timezone.utc).isoformat())
        state.save()

        # Sync documents
        log("Fetching documents...")
        raw_docs = await client.fetch_documents()
        log(f"  {len(raw_docs)} documents")
        for raw_doc in raw_docs:
            doc = LinearDocument.from_api(raw_doc)
            path = entity_path("document", title=doc.title)
            content = render_document(doc)

            full_path = repo_dir / path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)

            state.add_mapping(path, doc.id)
            stats["documents"] += 1

        # Final save
        state.set_last_sync(datetime.now(timezone.utc).isoformat())
        state.save()

    return stats


def _parse_issue(raw: dict, team_key: str) -> LinearIssue:
    """Parse a raw Linear API issue response into a LinearIssue model."""
    state = raw.get("state") or {}
    assignee = raw.get("assignee") or {}
    labels_data = raw.get("labels") or {}
    labels_nodes = labels_data.get("nodes", []) if isinstance(labels_data, dict) else labels_data

    return LinearIssue(
        id=raw["id"],
        identifier=raw.get("identifier", ""),
        title=raw.get("title", ""),
        description=raw.get("description"),
        status=state.get("name", "") if isinstance(state, dict) else str(state),
        priority=raw.get("priority"),
        priority_name=raw.get("priorityLabel"),
        assignee=assignee.get("name") if isinstance(assignee, dict) else assignee,
        assignee_id=assignee.get("id") if isinstance(assignee, dict) else None,
        labels=[lb.get("name", "") for lb in labels_nodes] if labels_nodes else [],
        team_key=team_key,
        estimate=raw.get("estimate"),
        due_date=raw.get("dueDate"),
        created=raw.get("createdAt", ""),
        updated=raw.get("updatedAt", ""),
        url=raw.get("url", ""),
    )


@click.command("pull")
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
    help="Path to the target repository (where Linear data is mirrored).",
)
@click.option(
    "--teams",
    default=None,
    help="Comma-separated team keys to sync (e.g. AI,ENG). Syncs all if omitted.",
)
@click.pass_context
def pull_command(ctx: click.Context, api_key: str | None, repo_dir: Path, teams: str | None) -> None:
    """Pull Linear data into the repository as markdown files."""
    if not api_key:
        raise click.UsageError("API key required. Use --api-key or set LINEAR_API_KEY env var.")

    teams_filter = [t.strip() for t in teams.split(",")] if teams else None

    json_mode = ctx.obj.get("json", False) if ctx.obj else False
    quiet = ctx.obj.get("quiet", 0) if ctx.obj else 0

    log = _noop_log if (json_mode or quiet) else _default_log
    show_progress = not (json_mode or quiet)

    stats = asyncio.run(_run_pull(api_key, repo_dir, teams_filter, log=log, show_progress=show_progress))

    if json_mode:
        click.echo(json.dumps(stats))
    elif not quiet:
        total = sum(stats.values())
        click.echo(f"Synced {total} entities: {stats['issues']} issues, "
                    f"{stats['projects']} projects, {stats['initiatives']} initiatives, "
                    f"{stats['documents']} documents")
