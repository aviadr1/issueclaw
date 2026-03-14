"""Create command: create a new Linear issue directly from the CLI."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import click
import yaml

from issueclaw.linear_client import LinearClient
from issueclaw.paths import entity_path, slugify
from issueclaw.sync_state import SyncState


async def _create_issue(
    api_key: str,
    repo_dir: Path,
    team_key: str,
    title: str,
    status: str | None,
    priority: int | None,
    assignee: str | None,
    labels: list[str],
    description: str | None,
) -> dict:
    """Create a new Linear issue and write the canonical file to the repo."""
    async with LinearClient(api_key=api_key) as client:
        # Resolve team
        teams = await client.fetch_teams()
        team_map = {t["key"]: t["id"] for t in teams}
        team_id = team_map.get(team_key)
        if not team_id:
            available = ", ".join(sorted(team_map))
            raise click.UsageError(f"Unknown team '{team_key}'. Available: {available}")

        create_fields: dict[str, Any] = {"title": title}

        if status:
            states = await client.fetch_team_states(team_id)
            state_map = {s["name"]: s["id"] for s in states}
            state_id = state_map.get(status)
            if state_id:
                create_fields["stateId"] = state_id
            else:
                available_states = ", ".join(sorted(state_map))
                raise click.UsageError(
                    f"Unknown status '{status}' for team {team_key}. Available: {available_states}"
                )

        if priority is not None:
            create_fields["priority"] = priority

        if assignee:
            users = await client.fetch_users()
            user_map = {u["name"]: u["id"] for u in users}
            user_id = user_map.get(assignee)
            if user_id:
                create_fields["assigneeId"] = user_id
            else:
                raise click.UsageError(f"Unknown assignee '{assignee}'.")

        if labels:
            label_data = await client.fetch_labels_for_team(team_id)
            label_map = {l["name"]: l["id"] for l in label_data}
            label_ids = [label_map[n] for n in labels if n in label_map]
            unknown = [n for n in labels if n not in label_map]
            if unknown:
                raise click.UsageError(f"Unknown labels: {', '.join(unknown)}")
            if label_ids:
                create_fields["labelIds"] = label_ids

        if description:
            create_fields["description"] = description

        issue = await client.create_issue(team_id, create_fields)
        if not issue.get("id"):
            raise click.ClickException("Linear API did not return an issue ID.")

        identifier = issue["identifier"]
        canonical_path = entity_path(
            "issue", team_key=team_key, identifier=identifier, issue_title=title
        )
        canonical_file = repo_dir / canonical_path
        canonical_file.parent.mkdir(parents=True, exist_ok=True)

        frontmatter_fields: dict[str, Any] = {
            "id": issue["id"],
            "identifier": identifier,
            "title": title,
        }
        if status:
            frontmatter_fields["status"] = status
        if priority is not None:
            frontmatter_fields["priority"] = priority
        if assignee:
            frontmatter_fields["assignee"] = assignee
        if labels:
            frontmatter_fields["labels"] = labels
        if issue.get("createdAt"):
            frontmatter_fields["created"] = issue["createdAt"]
        if issue.get("updatedAt"):
            frontmatter_fields["updated"] = issue["updatedAt"]
        if issue.get("url"):
            frontmatter_fields["url"] = issue["url"]

        fm_yaml = yaml.dump(
            frontmatter_fields, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
        content = f"---\n{fm_yaml}---\n\n# {identifier}: {title}\n"
        if description:
            content += f"\n{description}\n"
        canonical_file.write_text(content)

        state = SyncState(repo_dir)
        state.load()
        state.add_mapping(canonical_path, issue["id"])
        state.save()

        return {
            "id": issue["id"],
            "identifier": identifier,
            "title": title,
            "url": issue.get("url", ""),
            "file": canonical_path,
        }


@click.command("create")
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
@click.option("--team", required=True, help="Team key (e.g. AI, ENG, WEB).")
@click.option("--title", required=True, help="Issue title.")
@click.option("--status", default=None, help="Workflow status name (e.g. 'Backlog', 'In Progress').")
@click.option("--priority", default=None, type=int, help="Priority: 0=None 1=Urgent 2=High 3=Medium 4=Low.")
@click.option("--assignee", default=None, help="Assignee name.")
@click.option("--label", "labels", multiple=True, help="Label name (repeatable: --label Bug --label Task).")
@click.option("--description", default=None, help="Issue description body.")
@click.pass_context
def create_command(
    ctx: click.Context,
    api_key: str | None,
    repo_dir: Path,
    team: str,
    title: str,
    status: str | None,
    priority: int | None,
    assignee: str | None,
    labels: tuple[str, ...],
    description: str | None,
) -> None:
    """Create a new Linear issue directly (no git push required).

    The canonical markdown file is written immediately to the repo.
    """
    if not api_key:
        raise click.UsageError("API key required. Use --api-key or set LINEAR_API_KEY env var.")

    json_mode = ctx.obj.get("json", False) if ctx.obj else False

    result = asyncio.run(
        _create_issue(
            api_key=api_key,
            repo_dir=repo_dir,
            team_key=team.upper(),
            title=title,
            status=status,
            priority=priority,
            assignee=assignee,
            labels=list(labels),
            description=description,
        )
    )

    if json_mode:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Created {result['identifier']}: {result['title']}")
        click.echo(f"  File: {result['file']}")
        if result["url"]:
            click.echo(f"  URL:  {result['url']}")
