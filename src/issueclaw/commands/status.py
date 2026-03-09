"""Status command: show sync state summary."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import click

from issueclaw.sync_state import SyncState


@click.command("status")
@click.option(
    "--repo-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
    help="Path to the target repository.",
)
@click.pass_context
def status_command(ctx: click.Context, repo_dir: Path) -> None:
    """Show sync status and entity counts."""
    json_mode = ctx.obj.get("json", False) if ctx.obj else False

    state = SyncState(repo_dir)
    state.load()

    id_map_file = repo_dir / ".sync" / "id-map.json"
    if not id_map_file.exists():
        if json_mode:
            click.echo(json.dumps({"error": "not initialized"}))
        else:
            click.echo("No sync state found. Not initialized yet.")
        return

    # Count entities by type from id-map paths
    counts: Counter[str] = Counter()
    for path in state._path_to_uuid:
        if "/issues/" in path:
            counts["issues"] += 1
        elif "/projects/" in path:
            counts["projects"] += 1
        elif "/milestones/" in path:
            counts["milestones"] += 1
        elif "/initiatives/" in path:
            counts["initiatives"] += 1
        elif "/documents/" in path:
            counts["documents"] += 1

    # Count teams from issue paths
    teams: set[str] = set()
    for path in state._path_to_uuid:
        if "/issues/" in path:
            parts = path.split("/")
            if len(parts) >= 3:
                teams.add(parts[2])  # linear/teams/{KEY}/issues/...

    if json_mode:
        data = {
            "issues": counts["issues"],
            "projects": counts["projects"],
            "milestones": counts["milestones"],
            "initiatives": counts["initiatives"],
            "documents": counts["documents"],
            "teams": sorted(teams),
            "total": sum(counts.values()),
            "last_sync": state.last_sync,
        }
        click.echo(json.dumps(data))
    else:
        click.echo(f"Synced entities: {sum(counts.values())} total")
        click.echo(f"  Issues:      {counts['issues']}")
        click.echo(f"  Projects:    {counts['projects']}")
        click.echo(f"  Milestones:  {counts['milestones']}")
        click.echo(f"  Initiatives: {counts['initiatives']}")
        click.echo(f"  Documents:   {counts['documents']}")
        if teams:
            click.echo(f"  Teams:       {', '.join(sorted(teams))}")
        if state.last_sync:
            click.echo(f"Last sync: {state.last_sync}")
