"""Pull command: sync Linear data to local repository as markdown files."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import click

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


async def _run_pull(
    api_key: str,
    repo_dir: Path,
    teams_filter: list[str] | None,
    verbose: int = 0,
    quiet: int = 0,
) -> dict:
    """Execute the pull sync operation.

    Returns a stats dict with counts of synced entities.
    """
    client = LinearClient(api_key=api_key)
    state = SyncState(repo_dir)
    state.load()

    stats = {"issues": 0, "projects": 0, "initiatives": 0, "documents": 0}

    # Fetch teams
    teams = await client.fetch_teams()

    # Filter teams if specified
    if teams_filter:
        filter_set = {t.upper() for t in teams_filter}
        teams = [t for t in teams if t["key"].upper() in filter_set]

    # Sync issues per team
    for team in teams:
        team_key = team["key"]
        team_id = team["id"]

        raw_issues = await client.fetch_issues(team_id)
        for raw_issue in raw_issues:
            # Parse the raw API response into our model
            issue = _parse_issue(raw_issue, team_key)

            # Fetch comments for this issue
            raw_comments = await client.fetch_comments(issue.id)
            issue.comments = [LinearComment.from_api(c) for c in raw_comments]

            # Build path and render
            path = entity_path("issue", team_key=team_key, identifier=issue.identifier)
            content = render_issue(issue)

            # Write file
            full_path = repo_dir / path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)

            state.add_mapping(path, issue.id)
            stats["issues"] += 1

    # Sync projects
    raw_projects = await client.fetch_projects()
    for raw_proj in raw_projects:
        project = LinearProject.from_api(raw_proj)
        path = entity_path("project", slug=project.slug)
        content = render_project(project)

        full_path = repo_dir / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)

        state.add_mapping(path, project.id)
        stats["projects"] += 1

    # Sync initiatives
    raw_inits = await client.fetch_initiatives()
    for raw_init in raw_inits:
        initiative = LinearInitiative.from_api(raw_init)
        path = entity_path("initiative", name=initiative.name)
        content = render_initiative(initiative)

        full_path = repo_dir / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)

        state.add_mapping(path, initiative.id)
        stats["initiatives"] += 1

    # Sync documents
    raw_docs = await client.fetch_documents()
    for raw_doc in raw_docs:
        doc = LinearDocument.from_api(raw_doc)
        path = entity_path("document", title=doc.title)
        content = render_document(doc)

        full_path = repo_dir / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)

        state.add_mapping(path, doc.id)
        stats["documents"] += 1

    # Save state
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

    verbose = ctx.obj.get("verbose", 0) if ctx.obj else 0
    quiet = ctx.obj.get("quiet", 0) if ctx.obj else 0

    stats = asyncio.run(_run_pull(api_key, repo_dir, teams_filter, verbose, quiet))

    if not quiet:
        total = sum(stats.values())
        click.echo(f"Synced {total} entities: {stats['issues']} issues, "
                    f"{stats['projects']} projects, {stats['initiatives']} initiatives, "
                    f"{stats['documents']} documents")
