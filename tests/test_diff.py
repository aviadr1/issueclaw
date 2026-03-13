"""Tests for field-level diff between old and new markdown files."""

from issueclaw.diff import diff_markdown, FieldDiff


def _issue_md(
    status="Todo",
    title="Fix bug",
    body="Description.",
    comments_section="",
) -> str:
    """Helper to build a minimal issue markdown file."""
    md = f"""---
id: uuid-1
identifier: AI-1
title: {title}
status: {status}
priority: 2
created: '2026-01-01T00:00:00Z'
updated: '2026-01-01T00:00:00Z'
url: https://linear.app/test
---

# AI-1: {title}

{body}
"""
    if comments_section:
        md += comments_section
    return md


def test_diff_no_changes():
    """INVARIANT: Identical files produce an empty diff."""
    md = _issue_md()
    result = diff_markdown(md, md)
    assert result.frontmatter_changes == {}
    assert result.body_changed is False
    assert result.comments_added == []
    assert result.comments_removed == []
    assert result.comments_edited == []
    assert result.has_changes is False


def test_diff_frontmatter_field_change():
    """INVARIANT: Changed frontmatter fields are detected."""
    old = _issue_md(status="Todo")
    new = _issue_md(status="In Progress")
    result = diff_markdown(old, new)
    assert "status" in result.frontmatter_changes
    assert result.frontmatter_changes["status"] == FieldDiff(old="Todo", new="In Progress")
    assert result.has_changes is True


def test_diff_frontmatter_field_added():
    """INVARIANT: New frontmatter fields are detected."""
    old = _issue_md()
    new = old.replace("priority: 2", "priority: 2\nassignee: Aviad")
    result = diff_markdown(old, new)
    assert "assignee" in result.frontmatter_changes
    assert result.frontmatter_changes["assignee"] == FieldDiff(old=None, new="Aviad")


def test_diff_frontmatter_field_removed():
    """INVARIANT: Removed frontmatter fields are detected."""
    old = _issue_md()
    new = old.replace("priority: 2\n", "")
    result = diff_markdown(old, new)
    assert "priority" in result.frontmatter_changes
    assert result.frontmatter_changes["priority"] == FieldDiff(old=2, new=None)


def test_diff_body_changed():
    """INVARIANT: Body text changes are detected."""
    old = _issue_md(body="Original description.")
    new = _issue_md(body="Updated description with more detail.")
    result = diff_markdown(old, new)
    assert result.body_changed is True
    assert "Updated description" in result.new_body


def test_diff_body_unchanged():
    """INVARIANT: Identical body text is not flagged as changed."""
    old = _issue_md(body="Same text.")
    new = _issue_md(body="Same text.")
    result = diff_markdown(old, new)
    assert result.body_changed is False


def test_diff_comment_added():
    """INVARIANT: New comments are detected."""
    old = _issue_md()
    comments = """
# Comments

## Aviad - 2026-03-09T10:00:00Z
<!-- comment-id: c1 -->

New comment here.
"""
    new = _issue_md(comments_section=comments)
    result = diff_markdown(old, new)
    assert len(result.comments_added) == 1
    assert result.comments_added[0].id == "c1"
    assert "New comment here." in result.comments_added[0].body


def test_diff_comment_removed():
    """INVARIANT: Removed comments are detected."""
    comments = """
# Comments

## Aviad - 2026-03-09T10:00:00Z
<!-- comment-id: c1 -->

Old comment.
"""
    old = _issue_md(comments_section=comments)
    new = _issue_md()
    result = diff_markdown(old, new)
    assert len(result.comments_removed) == 1
    assert result.comments_removed[0].id == "c1"


def test_diff_comment_edited():
    """INVARIANT: Comments with same ID but different body are detected as edited."""
    old_comments = """
# Comments

## Aviad - 2026-03-09T10:00:00Z
<!-- comment-id: c1 -->

Original text.
"""
    new_comments = """
# Comments

## Aviad - 2026-03-09T10:00:00Z
<!-- comment-id: c1 -->

Edited text.
"""
    old = _issue_md(comments_section=old_comments)
    new = _issue_md(comments_section=new_comments)
    result = diff_markdown(old, new)
    assert len(result.comments_edited) == 1
    assert result.comments_edited[0].id == "c1"
    assert "Edited text." in result.comments_edited[0].body


def test_diff_multiple_changes():
    """INVARIANT: Multiple simultaneous changes are all detected."""
    old = _issue_md(status="Todo", body="Original.")
    new_comments = """
# Comments

## Aviad - 2026-03-09T10:00:00Z
<!-- comment-id: c1 -->

New comment.
"""
    new = _issue_md(status="Done", body="Updated.", comments_section=new_comments)
    result = diff_markdown(old, new)
    assert "status" in result.frontmatter_changes
    assert result.body_changed is True
    assert len(result.comments_added) == 1
    assert result.has_changes is True


def _project_md(
    name="Test Project",
    status="started",
    body="Description.",
    updates_section="",
) -> str:
    """Helper to build a minimal project markdown file."""
    md = f"""---
id: uuid-proj
name: {name}
status: {status}
created: '2026-01-01T00:00:00Z'
updated: '2026-01-01T00:00:00Z'
---

# {name}

{body}
"""
    if updates_section:
        md += updates_section
    return md


def test_diff_update_added():
    """INVARIANT: New project status updates are detected."""
    old = _project_md()
    updates = """
# Status Updates

## Aviad - 2026-03-13T21:00:00Z [onTrack]
<!-- update-id: u1 -->

Weekly report.
"""
    new = _project_md(updates_section=updates)
    result = diff_markdown(old, new)
    assert len(result.updates_added) == 1
    assert result.updates_added[0].id == "u1"
    assert result.updates_added[0].health == "onTrack"
    assert "Weekly report." in result.updates_added[0].body
    assert result.has_changes is True


def test_diff_update_removed():
    """INVARIANT: Removed project status updates are detected."""
    updates = """
# Status Updates

## Aviad - 2026-03-13T21:00:00Z [onTrack]
<!-- update-id: u1 -->

Old update.
"""
    old = _project_md(updates_section=updates)
    new = _project_md()
    result = diff_markdown(old, new)
    assert len(result.updates_removed) == 1
    assert result.updates_removed[0].id == "u1"


def test_diff_update_edited():
    """INVARIANT: Updates with same ID but different body are detected as edited."""
    old_updates = """
# Status Updates

## Aviad - 2026-03-13T21:00:00Z [onTrack]
<!-- update-id: u1 -->

Original text.
"""
    new_updates = """
# Status Updates

## Aviad - 2026-03-13T21:00:00Z [onTrack]
<!-- update-id: u1 -->

Edited text.
"""
    old = _project_md(updates_section=old_updates)
    new = _project_md(updates_section=new_updates)
    result = diff_markdown(old, new)
    assert len(result.updates_edited) == 1
    assert "Edited text." in result.updates_edited[0].body


def test_diff_no_update_changes():
    """INVARIANT: Identical updates produce no update diff."""
    updates = """
# Status Updates

## Aviad - 2026-03-13T21:00:00Z [onTrack]
<!-- update-id: u1 -->

Same text.
"""
    md = _project_md(updates_section=updates)
    result = diff_markdown(md, md)
    assert result.updates_added == []
    assert result.updates_removed == []
    assert result.updates_edited == []
