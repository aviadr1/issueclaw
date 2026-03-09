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
