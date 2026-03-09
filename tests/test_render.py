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
    """INVARIANT: Rendered issue has correct YAML frontmatter fields and title heading."""
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
    # Top-level heading with identifier and title
    assert "\n# AI-123: Implement chapter detection\n" in body
    assert "Build chapter detection." in body


def test_render_issue_with_project_and_lifecycle():
    """INVARIANT: Issue renders project, milestone, parent, and lifecycle dates."""
    issue = LinearIssue(
        id="uuid-123",
        identifier="AI-123",
        title="Test issue",
        description="Body.",
        status="Done",
        priority=2,
        assignee="Aviad",
        project="Metrics Platform",
        milestone="MVP",
        parent_id="AI-100",
        started_at="2026-01-15T10:00:00Z",
        completed_at="2026-02-01T14:00:00Z",
        created="2026-01-01T00:00:00Z",
        updated="2026-02-01T14:00:00Z",
        url="https://linear.app/test",
    )
    md = render_issue(issue)
    fm, _ = _parse_frontmatter(md)
    assert fm["project"] == "Metrics Platform"
    assert fm["milestone"] == "MVP"
    assert fm["parent"] == "AI-100"
    assert fm["started_at"] == "2026-01-15T10:00:00Z"
    assert fm["completed_at"] == "2026-02-01T14:00:00Z"


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
    """INVARIANT: Comments are embedded under # Comments section with ## sub-headings."""
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
    assert "\n# Comments\n" in md
    assert "## aviad@gigaverse.ai - 2026-02-15T09:00:00Z" in md
    assert "<!-- comment-id: c1 -->" in md
    assert "Started working." in md
    assert "## john@gigaverse.ai - 2026-02-20T11:00:00Z" in md
    assert "<!-- comment-id: c2 -->" in md


def test_render_issue_without_comments():
    """INVARIANT: Issues without comments have no # Comments section."""
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
    assert "# Comments" not in md


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
    assert "\n# Chapter Detection\n" in body
    assert "Build chapter detection." in body


def test_render_project_with_content():
    """INVARIANT: Project content field renders as main body (richer than description)."""
    project = LinearProject(
        id="uuid-proj",
        name="Metrics Platform",
        slug="metrics-platform",
        description="Short description.",
        content="# Data-as-Code\n\nTreat data infrastructure identically to application code.",
        status="started",
        lead_name="Mateusz",
        priority=2,
        health="onTrack",
        progress=0.75,
        scope=36,
        url="https://linear.app/test",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
    )
    md = render_project(project)
    fm, body = _parse_frontmatter(md)
    # Content should be the body when present (richer than description)
    assert "# Data-as-Code" in body
    assert "Treat data infrastructure" in body
    # Health, progress, scope should be in frontmatter
    assert fm["health"] == "onTrack"
    assert fm["progress"] == 0.75
    assert fm["scope"] == 36


def test_render_project_with_milestones():
    """INVARIANT: Project milestones render as a section in the body."""
    project = LinearProject(
        id="uuid-proj",
        name="Test Project",
        slug="test-project",
        status="started",
        milestones=[
            {"name": "MVP", "description": "First release", "targetDate": "2026-03-01", "status": "done", "progress": 1.0},
            {"name": "Beta", "description": "Public beta", "targetDate": "2026-06-01", "status": "inProgress", "progress": 0.5},
        ],
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
    )
    md = render_project(project)
    assert "\n# Milestones\n" in md
    assert "MVP" in md
    assert "First release" in md
    assert "Beta" in md


def test_render_project_with_updates():
    """INVARIANT: Project status updates render as a section."""
    project = LinearProject(
        id="uuid-proj",
        name="Test Project",
        slug="test-project",
        status="started",
        project_updates=[
            {
                "body": "## Release 42\n\nDeployed to production.",
                "health": "onTrack",
                "createdAt": "2026-02-17T11:04:21Z",
                "user": {"name": "Oz Shaked"},
            },
        ],
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
    )
    md = render_project(project)
    assert "\n# Status Updates\n" in md
    assert "Release 42" in md
    assert "Deployed to production" in md
    assert "Oz Shaked" in md


def test_render_project_with_members_and_teams():
    """INVARIANT: Project members and teams render in frontmatter."""
    project = LinearProject(
        id="uuid-proj",
        name="Test Project",
        slug="test-project",
        status="started",
        teams=[{"name": "Web", "key": "WEB"}, {"name": "Engineering", "key": "ENG"}],
        members=["Aviad Rozenhek", "Mateusz"],
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
    )
    md = render_project(project)
    fm, _ = _parse_frontmatter(md)
    assert fm["teams"] == ["WEB", "ENG"]
    assert fm["members"] == ["Aviad Rozenhek", "Mateusz"]


def test_render_project_with_initiatives_and_documents():
    """INVARIANT: Linked initiatives and documents render as sections."""
    project = LinearProject(
        id="uuid-proj",
        name="Test Project",
        slug="test-project",
        status="started",
        initiatives=[{"name": "Community metrics"}],
        documents=[{"title": "Architecture Design"}, {"title": "Migration Strategy"}],
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
    )
    md = render_project(project)
    assert "\n# Initiatives\n" in md
    assert "Community metrics" in md
    assert "\n# Documents\n" in md
    assert "Architecture Design" in md
    assert "Migration Strategy" in md


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
    assert "\n# Q1 2026 Roadmap\n" in body
    assert "Q1 focus areas." in body


def test_render_initiative_with_projects():
    """INVARIANT: Initiative linked projects render as a section."""
    initiative = LinearInitiative(
        id="uuid-init",
        name="Community metrics",
        description="Track community health.",
        status="Active",
        owner_name="Aviad",
        projects=[{"name": "Metrics Platform"}, {"name": "Analytics Dashboard"}],
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
    )
    md = render_initiative(initiative)
    assert "\n# Projects\n" in md
    assert "Metrics Platform" in md
    assert "Analytics Dashboard" in md


def test_render_initiative_with_content():
    """INVARIANT: Initiative content renders as body when present."""
    initiative = LinearInitiative(
        id="uuid-init",
        name="Test Initiative",
        description="Short description.",
        content="# Detailed Plan\n\nThis is the full content.",
        status="Active",
        owner_name="Aviad",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
    )
    md = render_initiative(initiative)
    _, body = _parse_frontmatter(md)
    assert "# Detailed Plan" in body
    assert "full content" in body


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
    assert "\n# Architecture Overview\n" in body
    assert "Details here." in body


def test_render_document_with_project():
    """INVARIANT: Document linked to a project shows project in frontmatter."""
    doc = LinearDocument(
        id="uuid-doc",
        title="Architecture Design",
        content="# Architecture\nDetails.",
        project_name="Metrics Platform",
        project_id="proj-uuid",
        url="https://linear.app/...",
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
    )
    md = render_document(doc)
    fm, _ = _parse_frontmatter(md)
    assert fm["project"] == "Metrics Platform"
