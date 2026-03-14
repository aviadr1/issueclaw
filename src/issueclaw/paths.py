"""Path conventions for Linear entity files."""

from __future__ import annotations

import re


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def entity_path(
    entity_type: str,
    *,
    team_key: str | None = None,
    identifier: str | None = None,
    slug: str | None = None,
    project_slug: str | None = None,
    name: str | None = None,
    title: str | None = None,
    slug_id: str | None = None,
    issue_title: str | None = None,
) -> str:
    """Build the file path for a Linear entity.

    Returns paths relative to repo root like:
        linear/teams/AI/issues/AI-123-fix-login-bug.md
        linear/projects/chapter-detection/_project.md
        linear/initiatives/q1-2026-roadmap.md
        linear/documents/architecture-overview.md
    """
    if entity_type == "issue":
        slug_suffix = f"-{slugify(issue_title)}" if issue_title else ""
        return f"linear/teams/{team_key}/issues/{identifier}{slug_suffix}.md"
    elif entity_type == "project":
        return f"linear/projects/{slug}/_project.md"
    elif entity_type == "milestone":
        return f"linear/projects/{project_slug}/milestones/{slugify(name) if name else name}.md"
    elif entity_type == "update":
        return f"linear/projects/{project_slug}/updates/{slug}.md"
    elif entity_type == "initiative":
        return f"linear/initiatives/{slugify(name) if name else name}.md"
    elif entity_type == "document":
        return f"linear/documents/{slugify(title) if title else title}.md"
    else:
        raise ValueError(f"Unknown entity type: {entity_type}")


# Regex patterns for parsing paths
_ISSUE_RE = re.compile(r"^linear/teams/([^/]+)/issues/([A-Z]+-\d+)(?:-[^/]+)?\.md$")
_NEW_ISSUE_RE = re.compile(r"^linear/new/([^/]+)/([^/]+)\.md$")
_PROJECT_RE = re.compile(r"^linear/projects/([^/]+)/_project\.md$")
_MILESTONE_RE = re.compile(r"^linear/projects/([^/]+)/milestones/([^/]+)\.md$")
_UPDATE_RE = re.compile(r"^linear/projects/([^/]+)/updates/([^/]+)\.md$")
_INITIATIVE_RE = re.compile(r"^linear/initiatives/([^/]+)\.md$")
_DOCUMENT_RE = re.compile(r"^linear/documents/([^/]+)\.md$")


def update_file_slug(created_at: str, author: str) -> str:
    """Generate a slug for a project update file.

    Format: YYYY-MM-DD-author-name (e.g., 2026-03-13-aviad-rozenhek)
    """
    date_part = created_at[:10] if created_at else "unknown"
    author_slug = slugify(author) if author else "unknown"
    return f"{date_part}-{author_slug}"


def parse_entity_path(path: str) -> dict | None:
    """Parse a file path to determine entity type and identifiers.

    Returns a dict with 'type' and entity-specific keys, or None if not a linear path.

    New issue queue: files at linear/new/{TEAM}/{slug}.md are parsed as type "new_issue".
    They will be created in Linear and moved to linear/teams/{TEAM}/issues/{ID}-{slug}.md.
    """
    m = _ISSUE_RE.match(path)
    if m:
        return {"type": "issue", "team_key": m.group(1), "identifier": m.group(2)}

    m = _NEW_ISSUE_RE.match(path)
    if m:
        return {"type": "new_issue", "team_key": m.group(1), "slug": m.group(2)}

    m = _MILESTONE_RE.match(path)
    if m:
        return {"type": "milestone", "project_slug": m.group(1), "name": m.group(2)}

    m = _UPDATE_RE.match(path)
    if m:
        return {"type": "update", "project_slug": m.group(1), "slug": m.group(2)}

    m = _PROJECT_RE.match(path)
    if m:
        return {"type": "project", "slug": m.group(1)}

    m = _INITIATIVE_RE.match(path)
    if m:
        return {"type": "initiative", "name": m.group(1)}

    m = _DOCUMENT_RE.match(path)
    if m:
        return {"type": "document", "slug": m.group(1)}

    return None
