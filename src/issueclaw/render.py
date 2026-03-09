"""Render Linear entities to markdown files with YAML frontmatter."""

from __future__ import annotations

from typing import Any

import yaml

from issueclaw.models import LinearComment, LinearDocument, LinearInitiative, LinearIssue, LinearProject


def _render_frontmatter(fields: dict[str, Any]) -> str:
    """Render a dict as YAML frontmatter between --- markers.

    Omits keys with None values to keep files clean.
    """
    cleaned = {k: v for k, v in fields.items() if v is not None}
    # Use default_flow_style=False for readable multi-line YAML
    fm_yaml = yaml.dump(cleaned, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return f"---\n{fm_yaml}---\n"


def _render_comments(comments: list[LinearComment]) -> str:
    """Render comments as markdown sections."""
    if not comments:
        return ""
    lines = ["\n## Comments\n"]
    for comment in comments:
        lines.append(f"\n### {comment.author_name} - {comment.created}")
        lines.append(f"<!-- comment-id: {comment.id} -->\n")
        lines.append(comment.body)
        lines.append("")
    return "\n".join(lines)


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
        "estimate": issue.estimate,
        "due_date": issue.due_date,
        "created": issue.created or None,
        "updated": issue.updated or None,
        "url": issue.url or None,
    }

    md = _render_frontmatter(fields)
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
        "lead": project.lead_name,
        "priority": project.priority,
        "start_date": project.start_date,
        "target_date": project.target_date,
        "labels": project.labels or None,
        "url": project.url or None,
        "created": project.created or None,
        "updated": project.updated or None,
    }

    md = _render_frontmatter(fields)
    if project.description:
        md += f"\n{project.description}\n"

    return md


def render_initiative(initiative: LinearInitiative) -> str:
    """Render a Linear initiative to markdown."""
    fields: dict[str, Any] = {
        "id": initiative.id,
        "name": initiative.name,
        "status": initiative.status or None,
        "owner": initiative.owner_name,
        "target_date": initiative.target_date,
        "created": initiative.created or None,
        "updated": initiative.updated or None,
    }

    md = _render_frontmatter(fields)
    if initiative.description:
        md += f"\n{initiative.description}\n"

    return md


def render_document(doc: LinearDocument) -> str:
    """Render a Linear document to markdown."""
    fields: dict[str, Any] = {
        "id": doc.id,
        "title": doc.title,
        "slug_id": doc.slug_id or None,
        "url": doc.url or None,
        "creator": doc.creator_name,
        "created": doc.created or None,
        "updated": doc.updated or None,
    }

    md = _render_frontmatter(fields)
    if doc.content:
        md += f"\n{doc.content}\n"

    return md
