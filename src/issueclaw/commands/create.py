"""Create command group: create issues, projects, initiatives, documents, comments directly."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import click
import yaml

from issueclaw.linear_client import LinearClient
from issueclaw.models import LinearIssue, LinearComment
from issueclaw.paths import entity_path, slugify
from issueclaw.render import render_issue
from issueclaw.sync_state import SyncState


def _api_key_option() -> Any:
    return click.option(
        "--api-key",
        envvar="LINEAR_API_KEY",
        default=None,
        help="Linear API key. Defaults to LINEAR_API_KEY env var.",
    )


def _repo_dir_option() -> Any:
    return click.option(
        "--repo-dir",
        type=click.Path(exists=True, file_okay=False, path_type=Path),
        default=".",
        help="Path to the target repository.",
    )


@click.group("create")
def create_group() -> None:
    """Create Linear entities directly from the CLI (no git push required)."""


@create_group.command("issue")
@_api_key_option()
@_repo_dir_option()
@click.option("--team", required=True, help="Team key (e.g. AI, ENG, WEB).")
@click.option("--title", required=True, help="Issue title.")
@click.option("--status", default=None, help="Workflow status (e.g. 'Backlog', 'In Progress').")
@click.option("--priority", default=None, type=int, help="Priority: 0=None 1=Urgent 2=High 3=Medium 4=Low.")
@click.option("--assignee", default=None, help="Assignee name.")
@click.option("--label", "labels", multiple=True, help="Label name (repeatable).")
@click.option(
    "--description",
    type=click.File("r"),
    default=None,
    help="Description body: path to a file, or '-' to read from stdin.",
)
@click.pass_context
def create_issue(
    ctx: click.Context,
    api_key: str | None,
    repo_dir: Path,
    team: str,
    title: str,
    status: str | None,
    priority: int | None,
    assignee: str | None,
    labels: tuple[str, ...],
    description: click.File | None,
) -> None:
    """Create a new Linear issue. Writes canonical file to the repo immediately."""
    if not api_key:
        raise click.UsageError("API key required. Use --api-key or set LINEAR_API_KEY env var.")
    json_mode = ctx.obj.get("json", False) if ctx.obj else False
    description_text = description.read().strip() if description else None
    result = asyncio.run(
        _create_issue(api_key, repo_dir, team.upper(), title, status, priority, assignee, list(labels), description_text)
    )
    if json_mode:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Created {result['identifier']}: {result['title']}")
        click.echo(f"  File: {result['file']}")
        if result["url"]:
            click.echo(f"  URL:  {result['url']}")


@create_group.command("comment")
@_api_key_option()
@_repo_dir_option()
@click.option("--issue", "identifier", required=True, help="Issue identifier (e.g. AI-123).")
@click.option(
    "--body",
    type=click.File("r"),
    default="-",
    help="Comment body: path to a file, or '-' to read from stdin (default).",
)
@click.pass_context
def create_comment(
    ctx: click.Context,
    api_key: str | None,
    repo_dir: Path,
    identifier: str,
    body: click.File,
) -> None:
    """Add a comment to an existing issue. Updates the local file immediately."""
    if not api_key:
        raise click.UsageError("API key required. Use --api-key or set LINEAR_API_KEY env var.")
    json_mode = ctx.obj.get("json", False) if ctx.obj else False
    body_text = body.read().strip()
    if not body_text:
        raise click.UsageError("Comment body cannot be empty.")
    result = asyncio.run(_create_comment(api_key, repo_dir, identifier.upper(), body_text))
    if json_mode:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Comment added to {result['identifier']}.")
        click.echo(f"  File: {result['file']}")


@create_group.command("project")
@_api_key_option()
@_repo_dir_option()
@click.option("--name", required=True, help="Project name.")
@click.option("--team", "teams", multiple=True, required=True, help="Team key (repeatable: --team AI --team ENG).")
@click.option(
    "--description",
    type=click.File("r"),
    default=None,
    help="Description body: path to a file, or '-' to read from stdin.",
)
@click.option("--lead", default=None, help="Lead user name.")
@click.option("--priority", default=None, type=int, help="Priority: 0=None 1=Urgent 2=High 3=Medium 4=Low.")
@click.option("--start-date", default=None, help="Start date (YYYY-MM-DD).")
@click.option("--target-date", default=None, help="Target date (YYYY-MM-DD).")
@click.pass_context
def create_project(
    ctx: click.Context,
    api_key: str | None,
    repo_dir: Path,
    name: str,
    teams: tuple[str, ...],
    description: click.File | None,
    lead: str | None,
    priority: int | None,
    start_date: str | None,
    target_date: str | None,
) -> None:
    """Create a new Linear project. Writes _project.md to the repo immediately."""
    if not api_key:
        raise click.UsageError("API key required. Use --api-key or set LINEAR_API_KEY env var.")
    json_mode = ctx.obj.get("json", False) if ctx.obj else False
    description_text = description.read().strip() if description else None
    result = asyncio.run(
        _create_project(api_key, repo_dir, name, [t.upper() for t in teams], description_text, lead, priority, start_date, target_date)
    )
    if json_mode:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Created project: {result['name']}")
        click.echo(f"  File: {result['file']}")
        if result["url"]:
            click.echo(f"  URL:  {result['url']}")


@create_group.command("initiative")
@_api_key_option()
@_repo_dir_option()
@click.option("--name", required=True, help="Initiative name.")
@click.option(
    "--description",
    type=click.File("r"),
    default=None,
    help="Description body: path to a file, or '-' to read from stdin.",
)
@click.option("--owner", default=None, help="Owner user name.")
@click.option("--target-date", default=None, help="Target date (YYYY-MM-DD).")
@click.option("--status", default=None, help="Status (e.g. 'planned', 'inProgress', 'completed').")
@click.pass_context
def create_initiative(
    ctx: click.Context,
    api_key: str | None,
    repo_dir: Path,
    name: str,
    description: click.File | None,
    owner: str | None,
    target_date: str | None,
    status: str | None,
) -> None:
    """Create a new Linear initiative. Writes the markdown file to the repo immediately."""
    if not api_key:
        raise click.UsageError("API key required. Use --api-key or set LINEAR_API_KEY env var.")
    json_mode = ctx.obj.get("json", False) if ctx.obj else False
    description_text = description.read().strip() if description else None
    result = asyncio.run(_create_initiative(api_key, repo_dir, name, description_text, owner, target_date, status))
    if json_mode:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Created initiative: {result['name']}")
        click.echo(f"  File: {result['file']}")
        if result["url"]:
            click.echo(f"  URL:  {result['url']}")


@create_group.command("document")
@_api_key_option()
@_repo_dir_option()
@click.option("--title", required=True, help="Document title.")
@click.option(
    "--body",
    type=click.File("r"),
    default="-",
    help="Document body: path to a file, or '-' to read from stdin (default).",
)
@click.option("--project", "project_slug", default=None, help="Associate with a project (slug, e.g. 'metrics-platform').")
@click.pass_context
def create_document(
    ctx: click.Context,
    api_key: str | None,
    repo_dir: Path,
    title: str,
    body: click.File,
    project_slug: str | None,
) -> None:
    """Create a new Linear document. Writes the markdown file to the repo immediately."""
    if not api_key:
        raise click.UsageError("API key required. Use --api-key or set LINEAR_API_KEY env var.")
    json_mode = ctx.obj.get("json", False) if ctx.obj else False
    body_text = body.read().strip() if body else None
    result = asyncio.run(_create_document(api_key, repo_dir, title, body_text or None, project_slug))
    if json_mode:
        click.echo(json.dumps(result))
    else:
        click.echo(f"Created document: {result['title']}")
        click.echo(f"  File: {result['file']}")
        if result["url"]:
            click.echo(f"  URL:  {result['url']}")


# Async implementation helpers

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
    async with LinearClient(api_key=api_key) as client:
        teams = await client.fetch_teams()
        team_map = {t["key"]: t["id"] for t in teams}
        team_id = team_map.get(team_key)
        if not team_id:
            raise click.UsageError(f"Unknown team '{team_key}'. Available: {', '.join(sorted(team_map))}")

        create_fields: dict[str, Any] = {"title": title}

        if status:
            states = await client.fetch_team_states(team_id)
            state_map = {s["name"]: s["id"] for s in states}
            state_id = state_map.get(status)
            if not state_id:
                raise click.UsageError(
                    f"Unknown status '{status}'. Available: {', '.join(sorted(state_map))}"
                )
            create_fields["stateId"] = state_id

        if priority is not None:
            create_fields["priority"] = priority

        if assignee:
            users = await client.fetch_users()
            user_map = {u["name"]: u["id"] for u in users}
            user_id = user_map.get(assignee)
            if not user_id:
                raise click.UsageError(f"Unknown assignee '{assignee}'.")
            create_fields["assigneeId"] = user_id

        if labels:
            label_data = await client.fetch_labels_for_team(team_id)
            label_map = {l["name"]: l["id"] for l in label_data}
            unknown = [n for n in labels if n not in label_map]
            if unknown:
                raise click.UsageError(f"Unknown labels: {', '.join(unknown)}")
            create_fields["labelIds"] = [label_map[n] for n in labels]

        if description:
            create_fields["description"] = description

        issue = await client.create_issue(team_id, create_fields)
        if not issue.get("id"):
            raise click.ClickException("Linear API did not return an issue ID.")

        identifier = issue["identifier"]
        canonical_path = entity_path("issue", team_key=team_key, identifier=identifier, issue_title=title)
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

        fm_yaml = yaml.dump(frontmatter_fields, default_flow_style=False, allow_unicode=True, sort_keys=False)
        content = f"---\n{fm_yaml}---\n\n# {identifier}: {title}\n"
        if description:
            content += f"\n{description}\n"
        canonical_file.write_text(content)

        state = SyncState(repo_dir)
        state.load()
        state.add_mapping(canonical_path, issue["id"])
        state.save()

        return {"id": issue["id"], "identifier": identifier, "title": title, "url": issue.get("url", ""), "file": canonical_path}


async def _create_comment(
    api_key: str,
    repo_dir: Path,
    identifier: str,
    body: str,
) -> dict:
    # Find the issue UUID by scanning id-map for a path containing the identifier
    state = SyncState(repo_dir)
    state.load()

    issue_path: str | None = None
    issue_uuid: str | None = None
    for path, uuid in state._path_to_uuid.items():
        if f"/{identifier}-" in path or f"/{identifier}." in path:
            issue_path = path
            issue_uuid = uuid
            break

    if not issue_uuid:
        raise click.UsageError(
            f"Issue '{identifier}' not found in .sync/id-map.json. Run 'issueclaw pull' first."
        )

    async with LinearClient(api_key=api_key) as client:
        comment = await client.create_comment(issue_uuid, body)
        if not comment.get("id"):
            raise click.ClickException("Linear API did not return a comment ID.")

        # Re-fetch the full issue and rewrite the local file
        issue_data = await client.fetch_issue(issue_uuid)

    if issue_data and issue_path:
        _rewrite_issue_file(repo_dir / issue_path, issue_data, identifier)

    return {"identifier": identifier, "comment_id": comment.get("id", ""), "file": issue_path or ""}


def _rewrite_issue_file(file_path: Path, issue_data: dict, identifier: str) -> None:
    """Re-render the issue file from fresh API data after a comment was added."""
    # Build a LinearIssue model and render it
    try:
        comments_raw = issue_data.get("comments", {}).get("nodes", [])
        comments = [
            LinearComment(
                id=c["id"],
                body=c.get("body", ""),
                created_at=c.get("createdAt", ""),
                updated_at=c.get("updatedAt"),
                author=c.get("user", {}).get("name") or c.get("user", {}).get("email", ""),
            )
            for c in comments_raw
        ]
        issue = LinearIssue(
            id=issue_data["id"],
            identifier=issue_data["identifier"],
            title=issue_data.get("title", ""),
            description=issue_data.get("description"),
            status=issue_data.get("state", {}).get("name"),
            priority=issue_data.get("priority"),
            assignee=(issue_data.get("assignee") or {}).get("name"),
            labels=[l["name"] for l in (issue_data.get("labels") or {}).get("nodes", [])],
            url=issue_data.get("url"),
            created_at=issue_data.get("createdAt"),
            updated_at=issue_data.get("updatedAt"),
            comments=comments,
        )
        file_path.write_text(render_issue(issue))
    except Exception:
        # If rendering fails for any reason, leave the file as-is
        pass


async def _create_project(
    api_key: str,
    repo_dir: Path,
    name: str,
    team_keys: list[str],
    description: str | None,
    lead: str | None,
    priority: int | None,
    start_date: str | None,
    target_date: str | None,
) -> dict:
    async with LinearClient(api_key=api_key) as client:
        teams = await client.fetch_teams()
        team_map = {t["key"]: t["id"] for t in teams}
        team_ids = []
        for key in team_keys:
            tid = team_map.get(key)
            if not tid:
                raise click.UsageError(f"Unknown team '{key}'. Available: {', '.join(sorted(team_map))}")
            team_ids.append(tid)

        fields: dict[str, Any] = {}
        if description:
            fields["description"] = description
        if priority is not None:
            fields["priority"] = priority
        if start_date:
            fields["startDate"] = start_date
        if target_date:
            fields["targetDate"] = target_date
        if lead:
            users = await client.fetch_users()
            user_map = {u["name"]: u["id"] for u in users}
            lead_id = user_map.get(lead)
            if not lead_id:
                raise click.UsageError(f"Unknown lead '{lead}'.")
            fields["leadId"] = lead_id

        project = await client.create_project(name, team_ids, fields)
        if not project.get("id"):
            raise click.ClickException("Linear API did not return a project ID.")

        slug = project.get("slugId") or slugify(name)
        canonical_path = entity_path("project", slug=slug)
        canonical_file = repo_dir / canonical_path
        canonical_file.parent.mkdir(parents=True, exist_ok=True)

        frontmatter_fields: dict[str, Any] = {
            "id": project["id"],
            "name": name,
            "slug": slug,
        }
        if description:
            frontmatter_fields["description"] = description
        if priority is not None:
            frontmatter_fields["priority"] = priority
        if lead:
            frontmatter_fields["lead"] = lead
        if start_date:
            frontmatter_fields["start_date"] = start_date
        if target_date:
            frontmatter_fields["target_date"] = target_date
        if team_keys:
            frontmatter_fields["teams"] = team_keys
        if project.get("createdAt"):
            frontmatter_fields["created"] = project["createdAt"]
        if project.get("updatedAt"):
            frontmatter_fields["updated"] = project["updatedAt"]
        if project.get("url"):
            frontmatter_fields["url"] = project["url"]

        fm_yaml = yaml.dump(frontmatter_fields, default_flow_style=False, allow_unicode=True, sort_keys=False)
        content = f"---\n{fm_yaml}---\n\n# {name}\n"
        if description:
            content += f"\n{description}\n"
        canonical_file.write_text(content)

        state = SyncState(repo_dir)
        state.load()
        state.add_mapping(canonical_path, project["id"])
        state.save()

        return {"id": project["id"], "name": name, "url": project.get("url", ""), "file": canonical_path}


async def _create_initiative(
    api_key: str,
    repo_dir: Path,
    name: str,
    description: str | None,
    owner: str | None,
    target_date: str | None,
    status: str | None,
) -> dict:
    async with LinearClient(api_key=api_key) as client:
        fields: dict[str, Any] = {}
        if description:
            fields["description"] = description
        if target_date:
            fields["targetDate"] = target_date
        if status:
            fields["status"] = status
        if owner:
            users = await client.fetch_users()
            user_map = {u["name"]: u["id"] for u in users}
            owner_id = user_map.get(owner)
            if not owner_id:
                raise click.UsageError(f"Unknown owner '{owner}'.")
            fields["ownerId"] = owner_id

        initiative = await client.create_initiative(name, fields)
        if not initiative.get("id"):
            raise click.ClickException("Linear API did not return an initiative ID.")

        canonical_path = entity_path("initiative", name=name)
        canonical_file = repo_dir / canonical_path
        canonical_file.parent.mkdir(parents=True, exist_ok=True)

        frontmatter_fields: dict[str, Any] = {
            "id": initiative["id"],
            "name": name,
        }
        if description:
            frontmatter_fields["description"] = description
        if owner:
            frontmatter_fields["owner"] = owner
        if target_date:
            frontmatter_fields["target_date"] = target_date
        if status:
            frontmatter_fields["status"] = status
        if initiative.get("createdAt"):
            frontmatter_fields["created"] = initiative["createdAt"]
        if initiative.get("updatedAt"):
            frontmatter_fields["updated"] = initiative["updatedAt"]
        if initiative.get("url"):
            frontmatter_fields["url"] = initiative["url"]

        fm_yaml = yaml.dump(frontmatter_fields, default_flow_style=False, allow_unicode=True, sort_keys=False)
        content = f"---\n{fm_yaml}---\n\n# {name}\n"
        if description:
            content += f"\n{description}\n"
        canonical_file.write_text(content)

        state = SyncState(repo_dir)
        state.load()
        state.add_mapping(canonical_path, initiative["id"])
        state.save()

        return {"id": initiative["id"], "name": name, "url": initiative.get("url", ""), "file": canonical_path}


async def _create_document(
    api_key: str,
    repo_dir: Path,
    title: str,
    body: str | None,
    project_slug: str | None,
) -> dict:
    async with LinearClient(api_key=api_key) as client:
        fields: dict[str, Any] = {}
        if body:
            fields["content"] = body
        if project_slug:
            # Look up project UUID from id-map
            state = SyncState(repo_dir)
            state.load()
            project_path = entity_path("project", slug=project_slug)
            project_id = state.get_uuid(project_path)
            if not project_id:
                raise click.UsageError(
                    f"Project '{project_slug}' not found in .sync/id-map.json. Run 'issueclaw pull' first."
                )
            fields["projectId"] = project_id

        doc = await client.create_document(title, fields)
        if not doc.get("id"):
            raise click.ClickException("Linear API did not return a document ID.")

        canonical_path = entity_path("document", title=title)
        canonical_file = repo_dir / canonical_path
        canonical_file.parent.mkdir(parents=True, exist_ok=True)

        frontmatter_fields: dict[str, Any] = {
            "id": doc["id"],
            "title": title,
        }
        if doc.get("creator", {}).get("name"):
            frontmatter_fields["creator"] = doc["creator"]["name"]
        if project_slug:
            frontmatter_fields["project"] = project_slug
        if doc.get("createdAt"):
            frontmatter_fields["created"] = doc["createdAt"]
        if doc.get("updatedAt"):
            frontmatter_fields["updated"] = doc["updatedAt"]
        if doc.get("url"):
            frontmatter_fields["url"] = doc["url"]

        fm_yaml = yaml.dump(frontmatter_fields, default_flow_style=False, allow_unicode=True, sort_keys=False)
        content = f"---\n{fm_yaml}---\n\n# {title}\n"
        if body:
            content += f"\n{body}\n"
        canonical_file.write_text(content)

        state = SyncState(repo_dir)
        state.load()
        state.add_mapping(canonical_path, doc["id"])
        state.save()

        return {"id": doc["id"], "title": title, "url": doc.get("url", ""), "file": canonical_path}
