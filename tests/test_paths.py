from issueclaw.paths import entity_path, parse_entity_path, slugify


def test_issue_path():
    """INVARIANT: Issue path includes identifier and slugified title."""
    assert entity_path("issue", team_key="AI", identifier="AI-123", issue_title="Fix login bug") == "linear/teams/AI/issues/AI-123-fix-login-bug.md"


def test_issue_path_without_title():
    """INVARIANT: Issue path works without title (just identifier)."""
    assert entity_path("issue", team_key="AI", identifier="AI-123") == "linear/teams/AI/issues/AI-123.md"


def test_project_path():
    """INVARIANT: Project path follows linear/projects/{slug}/_project.md convention."""
    assert entity_path("project", slug="chapter-detection") == "linear/projects/chapter-detection/_project.md"


def test_milestone_path():
    """INVARIANT: Milestone path nests under project directory."""
    path = entity_path("milestone", project_slug="chapter-detection", name="mvp")
    assert path == "linear/projects/chapter-detection/milestones/mvp.md"


def test_initiative_path():
    """INVARIANT: Initiative path uses slugified name."""
    assert entity_path("initiative", name="Q1 2026 Roadmap") == "linear/initiatives/q1-2026-roadmap.md"


def test_document_path():
    """INVARIANT: Document path uses slugified title."""
    path = entity_path("document", title="Architecture Overview")
    assert path == "linear/documents/architecture-overview.md"


def test_parse_issue_path():
    """INVARIANT: Parsing an issue path returns type and identifiers."""
    result = parse_entity_path("linear/teams/AI/issues/AI-123-fix-login-bug.md")
    assert result["type"] == "issue"
    assert result["team_key"] == "AI"
    assert result["identifier"] == "AI-123"


def test_parse_issue_path_without_slug():
    """INVARIANT: Parsing an issue path without slug still works."""
    result = parse_entity_path("linear/teams/AI/issues/AI-123.md")
    assert result["type"] == "issue"
    assert result["identifier"] == "AI-123"


def test_parse_project_path():
    """INVARIANT: Parsing a project path returns type and slug."""
    result = parse_entity_path("linear/projects/chapter-detection/_project.md")
    assert result["type"] == "project"
    assert result["slug"] == "chapter-detection"


def test_parse_milestone_path():
    """INVARIANT: Parsing a milestone path returns project slug and name."""
    result = parse_entity_path("linear/projects/chapter-detection/milestones/mvp.md")
    assert result["type"] == "milestone"
    assert result["project_slug"] == "chapter-detection"
    assert result["name"] == "mvp"


def test_parse_initiative_path():
    """INVARIANT: Parsing an initiative path returns type and name."""
    result = parse_entity_path("linear/initiatives/q1-2026-roadmap.md")
    assert result["type"] == "initiative"
    assert result["name"] == "q1-2026-roadmap"


def test_parse_document_path():
    """INVARIANT: Parsing a document path returns type and slug."""
    result = parse_entity_path("linear/documents/architecture-overview.md")
    assert result["type"] == "document"
    assert result["slug"] == "architecture-overview"


def test_parse_non_linear_path_returns_none():
    """INVARIANT: Non-linear paths return None."""
    assert parse_entity_path("src/main.py") is None
    assert parse_entity_path("README.md") is None


def test_slugify():
    """INVARIANT: Slugify converts text to URL-friendly lowercase slug."""
    assert slugify("Q1 2026 Roadmap") == "q1-2026-roadmap"
    assert slugify("Architecture Overview") == "architecture-overview"
    assert slugify("Hello   World!!") == "hello-world"
    assert slugify("already-slugified") == "already-slugified"
