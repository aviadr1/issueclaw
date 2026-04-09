from issueclaw.models import LinearComment, LinearIssue, LinearProject
from issueclaw.parse import ParsedComment, ParsedSection, parse_markdown
from issueclaw.render import render_issue, render_project


def test_parse_issue_with_comments():
    """INVARIANT: Parser extracts frontmatter, body, and comments from .md files."""
    md = """---
id: "uuid-123"
identifier: "AI-123"
title: "Test issue"
status: "In Progress"
priority: 2
labels:
  - "feature"
---

Issue description here.

# Comments

## aviad@gigaverse.ai - 2026-02-15T09:00:00Z
<!-- comment-id: c1-uuid -->

Started working on this.

## john@gigaverse.ai - 2026-02-20T11:00:00Z
<!-- comment-id: c2-uuid -->

Looks good!
"""
    result = parse_markdown(md)
    assert result.frontmatter["id"] == "uuid-123"
    assert result.frontmatter["status"] == "In Progress"
    assert result.frontmatter["labels"] == ["feature"]
    assert "Issue description here." in result.body
    assert len(result.comments) == 2
    assert result.comments[0].id == "c1-uuid"
    assert result.comments[0].author == "aviad@gigaverse.ai"
    assert result.comments[0].timestamp == "2026-02-15T09:00:00Z"
    assert "Started working" in result.comments[0].body
    assert result.comments[1].id == "c2-uuid"
    assert result.comments[1].author == "john@gigaverse.ai"


def test_parse_issue_without_comments():
    """INVARIANT: Parser works when no comments section exists."""
    md = """---
id: "uuid-456"
title: "No comments"
---

Just a body.
"""
    result = parse_markdown(md)
    assert result.frontmatter["id"] == "uuid-456"
    assert "Just a body." in result.body
    assert result.comments == []


def test_parse_empty_body():
    """INVARIANT: Parser handles files with only frontmatter."""
    md = """---
id: "uuid-789"
title: "Empty body"
---
"""
    result = parse_markdown(md)
    assert result.frontmatter["id"] == "uuid-789"
    assert result.body.strip() == ""
    assert result.comments == []


def test_parse_comment_with_multiline_body():
    """INVARIANT: Parser captures full multi-line comment bodies."""
    md = """---
id: "uuid"
title: "Test"
---

Body.

# Comments

## user@test.com - 2026-01-01T00:00:00Z
<!-- comment-id: c1 -->

First paragraph.

Second paragraph with **bold**.

- List item 1
- List item 2
"""
    result = parse_markdown(md)
    assert len(result.comments) == 1
    assert "First paragraph." in result.comments[0].body
    assert "Second paragraph" in result.comments[0].body
    assert "- List item 1" in result.comments[0].body


def test_roundtrip_issue():
    """INVARIANT: render -> parse -> verify preserves all data."""
    comments = [
        LinearComment(
            id="c1",
            body="Hello.",
            author_name="user@test.com",
            created="2026-01-02T00:00:00Z",
            updated="2026-01-02T00:00:00Z",
        ),
    ]
    issue = LinearIssue(
        id="uuid",
        identifier="AI-1",
        title="Test",
        description="Body text.",
        status="Todo",
        priority=3,
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
        url="https://linear.app/test",
        comments=comments,
    )
    md = render_issue(issue)
    parsed = parse_markdown(md)
    assert parsed.frontmatter["identifier"] == "AI-1"
    assert parsed.frontmatter["priority"] == 3
    assert "Body text." in parsed.body
    assert len(parsed.comments) == 1
    assert parsed.comments[0].id == "c1"
    assert parsed.comments[0].author == "user@test.com"
    assert "Hello." in parsed.comments[0].body


def test_parse_project_with_status_updates():
    """INVARIANT: Parser extracts status updates from project files."""
    md = """---
id: "uuid-proj"
name: "Test Project"
status: "started"
---

# Test Project

Description.

# Status Updates

## Oz Shaked - 2026-02-17T11:04:21Z [onTrack]
<!-- update-id: u1-uuid -->

## Release 42

Deployed to production.

## Aviad Rozenhek - 2026-03-13T21:00:00Z [onTrack]
<!-- update-id: u2-uuid -->

Weekly report content here.

# Initiatives

- Community metrics
"""
    result = parse_markdown(md)
    assert result.frontmatter["name"] == "Test Project"
    assert "Description." in result.body
    assert len(result.updates) == 2
    assert result.updates[0].id == "u1-uuid"
    assert result.updates[0].author == "Oz Shaked"
    assert result.updates[0].health == "onTrack"
    assert "Deployed to production." in result.updates[0].body
    assert result.updates[1].id == "u2-uuid"
    assert result.updates[1].author == "Aviad Rozenhek"
    assert "Weekly report content" in result.updates[1].body
    # Initiatives section should be preserved in body, not in updates
    assert result.comments == []


def test_parse_project_without_updates():
    """INVARIANT: Parser works when no status updates section exists."""
    md = """---
id: "uuid-proj"
name: "Empty project"
---

# Empty project
"""
    result = parse_markdown(md)
    assert result.updates == []
    assert result.comments == []


def test_parse_update_with_multiline_body():
    """INVARIANT: Parser captures full multi-line update bodies."""
    md = """---
id: "uuid"
name: "Test"
---

Body.

# Status Updates

## Author - 2026-01-01T00:00:00Z [onTrack]
<!-- update-id: u1 -->

First paragraph.

| Column A | Column B |
|----------|----------|
| Data     | More     |

- Bullet point
"""
    result = parse_markdown(md)
    assert len(result.updates) == 1
    assert "First paragraph." in result.updates[0].body
    assert "Column A" in result.updates[0].body
    assert "- Bullet point" in result.updates[0].body


def test_parsed_comment_is_parsed_section():
    """INVARIANT: ParsedComment is an alias for ParsedSection (backward compat)."""
    assert ParsedComment is ParsedSection


def test_roundtrip_project_update_file():
    """INVARIANT: render_project_update -> parse_markdown preserves all fields."""
    from issueclaw.render import render_project_update

    update = {
        "id": "u1",
        "body": "Weekly update content.",
        "health": "onTrack",
        "createdAt": "2026-03-13T21:00:00Z",
        "user": {"name": "Aviad Rozenhek"},
    }
    md = render_project_update(update)
    parsed = parse_markdown(md)
    assert parsed.frontmatter["id"] == "u1"
    assert parsed.frontmatter["author"] == "Aviad Rozenhek"
    assert parsed.frontmatter["health"] == "onTrack"
    assert "Weekly update content." in parsed.body


def test_project_renders_update_refs_not_inline():
    """INVARIANT: render_project creates reference links, not inline update content."""
    project = LinearProject(
        id="uuid-proj",
        name="Test Project",
        slug="test-project",
        status="started",
        project_updates=[
            {
                "id": "u1",
                "body": "Should not appear inline.",
                "health": "onTrack",
                "createdAt": "2026-03-13T21:00:00Z",
                "user": {"name": "Aviad Rozenhek"},
            },
        ],
        created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
    )
    md = render_project(project)
    assert "updates/2026-03-13-aviad-rozenhek.md" in md
    assert "Should not appear inline." not in md
