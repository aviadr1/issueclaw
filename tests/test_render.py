import yaml

from issueclaw.models import LinearComment, LinearDocument, LinearInitiative, LinearIssue, LinearProject
from issueclaw.render import render_document, render_initiative, render_issue, render_project


def _parse_frontmatter(md: str) -> tuple[dict, str]:
    """Helper: split rendered markdown into frontmatter dict and body."""
    assert md.startswith("---\n"), "Rendered markdown must start with ---"
    parts = md.split("---\n", 2)
    fm = yaml.safe_load(parts[1])
    body = parts[2] if len(parts) > 2 else ""
    return fm, body


def test_render_issue_frontmatter():
    """INVARIANT: Rendered issue has correct YAML frontmatter fields."""
    issue = LinearIssue(
        id="uuid-123",
        identifier="AI-123",
        title="Implement chapter detection",
        description="Build chapter detection.",
        status="In Progress",
        priority=2,
        priority_name="High",
        assignee="aviad@gigaverse.ai",
        labels=["feature", "ai"],
        team="AI",
        project="chapter-detection",
        created="2026-01-15T10:00:00Z",
        updated="2026-03-01T14:30:00Z",
        url="https://linear.app/gigaverse/issue/AI-123",
    )
    md = render_issue(issue)
    fm, body = _parse_frontmatter(md)
    assert fm["id"] == "uuid-123"
    assert fm["identifier"] == "AI-123"
    assert fm["title"] == "Implement chapter detection"
    assert fm["status"] == "In Progress"
    assert fm["priority"] == 2
    assert fm["assignee"] == "aviad@gigaverse.ai"
    assert fm["labels"] == ["feature", "ai"]
    assert "Build chapter detection." in body


def test_render_issue_omits_none_fields():
    """INVARIANT: None/empty optional fields are omitted from frontmatter."""
    issue = LinearIssue(
        id="uuid-min",
        identifier="AI-1",
        title="Minimal",
        status="Backlog",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
        url="https://linear.app/test",
    )
    md = render_issue(issue)
    fm, _ = _parse_frontmatter(md)
    assert "assignee" not in fm
    assert "due_date" not in fm
    assert "estimate" not in fm
    assert "project" not in fm
    # Required fields still present
    assert fm["id"] == "uuid-min"
    assert fm["identifier"] == "AI-1"


def test_render_issue_with_comments():
    """INVARIANT: Comments are embedded under ## Comments section."""
    comments = [
        LinearComment(
            id="c1",
            body="Started working.",
            author_name="aviad@gigaverse.ai",
            created="2026-02-15T09:00:00Z",
            updated="2026-02-15T09:00:00Z",
        ),
        LinearComment(
            id="c2",
            body="Looks good!",
            author_name="john@gigaverse.ai",
            created="2026-02-20T11:00:00Z",
            updated="2026-02-20T11:00:00Z",
        ),
    ]
    issue = LinearIssue(
        id="uuid-123",
        identifier="AI-123",
        title="Test",
        description="Body.",
        status="Todo",
        priority=3,
        priority_name="Normal",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
        url="https://linear.app/test",
        comments=comments,
    )
    md = render_issue(issue)
    assert "## Comments" in md
    assert "### aviad@gigaverse.ai - 2026-02-15T09:00:00Z" in md
    assert "<!-- comment-id: c1 -->" in md
    assert "Started working." in md
    assert "### john@gigaverse.ai - 2026-02-20T11:00:00Z" in md
    assert "<!-- comment-id: c2 -->" in md


def test_render_issue_without_comments():
    """INVARIANT: Issues without comments have no ## Comments section."""
    issue = LinearIssue(
        id="uuid",
        identifier="AI-1",
        title="No comments",
        description="Body.",
        status="Todo",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
        url="https://linear.app/test",
    )
    md = render_issue(issue)
    assert "## Comments" not in md


def test_render_project():
    """INVARIANT: Project renders with correct frontmatter."""
    project = LinearProject(
        id="uuid-proj",
        name="Chapter Detection",
        slug="chapter-detection",
        description="Build chapter detection.",
        status="started",
        lead_name="aviad@gigaverse.ai",
        priority=2,
        start_date="2026-01-01",
        target_date="2026-06-30",
        labels=["ai-features"],
        url="https://linear.app/gigaverse/project/chapter-detection",
        created="2026-01-01T00:00:00Z",
        updated="2026-03-01T00:00:00Z",
    )
    md = render_project(project)
    fm, body = _parse_frontmatter(md)
    assert fm["name"] == "Chapter Detection"
    assert fm["slug"] == "chapter-detection"
    assert fm["status"] == "started"
    assert fm["lead"] == "aviad@gigaverse.ai"
    assert "Build chapter detection." in body


def test_render_initiative():
    """INVARIANT: Initiative renders with correct frontmatter."""
    initiative = LinearInitiative(
        id="uuid-init",
        name="Q1 2026 Roadmap",
        description="Q1 focus areas.",
        status="Active",
        owner_name="aviad@gigaverse.ai",
        target_date="2026-03-31",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
    )
    md = render_initiative(initiative)
    fm, body = _parse_frontmatter(md)
    assert fm["name"] == "Q1 2026 Roadmap"
    assert fm["status"] == "Active"
    assert fm["owner"] == "aviad@gigaverse.ai"
    assert "Q1 focus areas." in body


def test_render_document():
    """INVARIANT: Document renders title in frontmatter, content as body."""
    doc = LinearDocument(
        id="uuid-doc",
        title="Architecture Overview",
        content="# Overview\nDetails here.",
        slug_id="abc123",
        url="https://linear.app/...",
        creator_name="Jakub",
        created="2026-01-01T00:00:00Z",
        updated="2026-02-01T00:00:00Z",
    )
    md = render_document(doc)
    fm, body = _parse_frontmatter(md)
    assert fm["title"] == "Architecture Overview"
    assert fm["id"] == "uuid-doc"
    assert "# Overview" in body
    assert "Details here." in body
