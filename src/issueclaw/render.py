"""Render Linear entities to markdown files with YAML frontmatter."""

from __future__ import annotations

from typing import Any

import yaml

from issueclaw.models import (
    LinearComment,
    LinearDocument,
    LinearInitiative,
    LinearIssue,
    LinearProject,
)
from issueclaw.paths import update_file_slug


def _render_frontmatter(fields: dict[str, Any]) -> str:
    """Render a dict as YAML frontmatter between --- markers.

    Omits keys with None values to keep files clean.
    """
    cleaned = {k: v for k, v in fields.items() if v is not None}
    # Use default_flow_style=False for readable multi-line YAML
    fm_yaml = yaml.dump(
        cleaned, default_flow_style=False, allow_unicode=True, sort_keys=False
    )
    return f"---\n{fm_yaml}---\n"


def _render_sections(
    items: list[dict[str, str]],
    section_header: str,
    id_marker: str,
) -> str:
    """Render a list of section items (comments or updates) to markdown.

    Each item dict must have: id, author, date, body.
    Optionally: health (rendered as [health] suffix on header).
    """
    if not items:
        return ""
    lines = [f"\n# {section_header}\n"]
    for item in items:
        header = f"\n## {item['author']} - {item['date']}"
        if item.get("health"):
            header += f" [{item['health']}]"
        lines.append(header)
        lines.append(f"<!-- {id_marker}: {item['id']} -->\n")
        lines.append(item["body"])
        lines.append("")
    return "\n".join(lines)


def _render_comments(comments: list[LinearComment]) -> str:
    """Render comments as markdown sections."""
    items = [
        {"id": c.id, "author": c.author_name, "date": c.created, "body": c.body}
        for c in comments
    ]
    return _render_sections(items, "Comments", "comment-id")


def _render_update_refs(updates: list[dict]) -> str:
    """Render project status updates as a reference list pointing to individual files."""
    if not updates:
        return ""
    lines = ["\n# Status Updates\n"]
    for u in updates:
        user = u.get("user", {})
        author = user.get("name", "") if isinstance(user, dict) else str(user)
        date = u.get("createdAt", "")
        health = u.get("health", "")
        slug = update_file_slug(date, author)
        health_tag = f" [{health}]" if health else ""
        lines.append(f"- [{date}](updates/{slug}.md) by {author}{health_tag}")
    lines.append("")
    return "\n".join(lines)


def render_project_update(update: dict) -> str:
    """Render an individual project status update to its own markdown file."""
    user = update.get("user", {})
    author = user.get("name", "") if isinstance(user, dict) else str(user)
    fields: dict[str, Any] = {
        "id": update.get("id", ""),
        "author": author,
        "health": update.get("health", ""),
        "created": update.get("createdAt", ""),
    }
    md = _render_frontmatter(fields)
    if update.get("body"):
        md += f"\n{update['body']}\n"
    return md


def render_issue(issue: LinearIssue) -> str:
    """Render a Linear issue to markdown."""
    fields: dict[str, Any] = {
        "id": issue.id,
        "identifier": issue.identifier,
        "title": issue.title,
        "status": issue.status or None,
        "priority": issue.priority,
        "assignee": issue.assignee,
        "labels": issue.labels or None,
        "project": issue.project,
        "milestone": issue.milestone,
        "parent": issue.parent_id,
        "estimate": issue.estimate,
        "due_date": issue.due_date,
        "started_at": issue.started_at,
        "completed_at": issue.completed_at,
        "canceled_at": issue.canceled_at,
        "created": issue.created or None,
        "updated": issue.updated or None,
        "url": issue.url or None,
    }

    md = _render_frontmatter(fields)
    md += f"\n# {issue.identifier}: {issue.title}\n"
    if issue.description:
        md += f"\n{issue.description}\n"

    if issue.comments:
        md += _render_comments(issue.comments)

    return md


def render_project(project: LinearProject) -> str:
    """Render a Linear project to markdown."""
    fields: dict[str, Any] = {
        "id": project.id,
        "name": project.name,
        "slug": project.slug or None,
        "status": project.status or None,
        "health": project.health,
        "progress": project.progress,
        "scope": project.scope,
        "lead": project.lead_name,
        "priority": project.priority,
        "start_date": project.start_date,
        "target_date": project.target_date,
        "labels": project.labels or None,
        "teams": [t.get("key", t.get("name", "")) for t in project.teams]
        if project.teams
        else None,
        "members": project.members or None,
        "url": project.url or None,
        "created": project.created or None,
        "updated": project.updated or None,
    }

    md = _render_frontmatter(fields)
    md += f"\n# {project.name}\n"

    # Content is richer than description; prefer it as the body
    body_text = project.content or project.description
    if body_text:
        md += f"\n{body_text}\n"

    if project.milestones:
        md += "\n# Milestones\n\n"
        for ms in project.milestones:
            status = f" ({ms.get('status', '')})" if ms.get("status") else ""
            progress = (
                f" - {ms.get('progress', 0) * 100:.0f}%"
                if ms.get("progress") is not None
                else ""
            )
            md += f"- **{ms.get('name', '')}**{status}{progress}\n"
            if ms.get("targetDate"):
                md += f"  Target: {ms['targetDate']}\n"
            if ms.get("description"):
                md += f"  {ms['description']}\n"

    if project.project_updates:
        md += _render_update_refs(project.project_updates)

    if project.initiatives:
        md += "\n# Initiatives\n\n"
        for init in project.initiatives:
            md += f"- {init.get('name', '')}\n"

    if project.documents:
        md += "\n# Documents\n\n"
        for doc in project.documents:
            md += f"- {doc.get('title', '')}\n"

    return md


def render_initiative(initiative: LinearInitiative) -> str:
    """Render a Linear initiative to markdown."""
    fields: dict[str, Any] = {
        "id": initiative.id,
        "name": initiative.name,
        "status": initiative.status or None,
        "health": initiative.health,
        "owner": initiative.owner_name,
        "target_date": initiative.target_date,
        "url": initiative.url or None,
        "created": initiative.created or None,
        "updated": initiative.updated or None,
    }

    md = _render_frontmatter(fields)
    md += f"\n# {initiative.name}\n"

    # Content is richer than description; prefer it as the body
    body_text = initiative.content or initiative.description
    if body_text:
        md += f"\n{body_text}\n"

    if initiative.projects:
        md += "\n# Projects\n\n"
        for proj in initiative.projects:
            md += f"- {proj.get('name', '')}\n"

    return md


def render_document(doc: LinearDocument) -> str:
    """Render a Linear document to markdown."""
    fields: dict[str, Any] = {
        "id": doc.id,
        "title": doc.title,
        "slug_id": doc.slug_id or None,
        "project": doc.project_name,
        "url": doc.url or None,
        "creator": doc.creator_name,
        "created": doc.created or None,
        "updated": doc.updated or None,
    }

    md = _render_frontmatter(fields)
    md += f"\n# {doc.title}\n"
    if doc.content:
        md += f"\n{doc.content}\n"

    return md
