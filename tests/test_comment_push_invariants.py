"""TDD red-phase tests: invariants for the correct comment push model.

These tests encode the fundamental rule:

    A <!-- comment-id: UUID --> marker means the comment ALREADY EXISTS in Linear.
    Never call create_comment for it.
    Only call create_comment for human-authored sections WITHOUT a comment-id.

Each test is an invariant that should always hold, not a test for a specific bug.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from issueclaw.commands import push as push_mod
from issueclaw.diff import diff_markdown
from issueclaw.parse import parse_markdown
from issueclaw.sync_state import SyncState


# Helpers


def _issue_md(
    identifier="AI-1",
    title="Fix bug",
    status="Todo",
    body="Description.",
    comments_section="",
) -> str:
    """Build a minimal issue markdown string."""
    md = f"""---
id: uuid-{identifier.lower()}
identifier: {identifier}
title: {title}
status: {status}
priority: 2
created: '2026-01-01T00:00:00Z'
updated: '2026-01-01T00:00:00Z'
url: https://linear.app/test
---

# {identifier}: {title}

{body}
"""
    if comments_section:
        md += comments_section
    return md


def _setup_state(tmp_path: Path, rel_path: str, uuid: str) -> None:
    """Write a SyncState mapping for a file."""
    state = SyncState(tmp_path)
    state.load()
    state.add_mapping(rel_path, uuid)
    state.save()


def _mock_linear_client(**overrides) -> AsyncMock:
    """Build a mock LinearClient with sensible defaults."""
    client = AsyncMock()
    client.update_issue.return_value = {"id": "uuid-ai-1"}
    client.create_comment.return_value = {"id": "newly-created-uuid"}
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    for k, v in overrides.items():
        setattr(client, k, v)
    return client


# parse.py invariants


class TestParseSectionsPendingComments:
    """Invariants for _parse_sections handling of ID-less sections."""

    def test_idless_section_is_captured(self):
        """INVARIANT: A comment section without a comment-id IS captured by the parser.

        Human-authored comments don't have IDs yet. The parser must not silently
        drop them — they are the mechanism for humans to post comments from git.
        """
        md = """---
id: uuid-1
identifier: AI-1
title: Test
---

Description.

# Comments

## Aviad - 2026-04-09T10:00:00Z

This is a human-written comment with no ID.
"""
        result = parse_markdown(md)
        assert len(result.pending_comments) == 1
        assert result.pending_comments[0].author == "Aviad"
        assert "human-written comment" in result.pending_comments[0].body

    def test_idless_section_has_empty_id(self):
        """INVARIANT: A pending comment has an empty-string id, distinguishing it
        from Linear-synced comments that have UUIDs."""
        md = """---
id: uuid-1
identifier: AI-1
title: Test
---

Body.

# Comments

## Author - 2026-04-09T10:00:00Z

Pending comment.
"""
        result = parse_markdown(md)
        assert len(result.pending_comments) == 1
        assert result.pending_comments[0].id == ""

    def test_mixed_id_and_idless_sections_are_separated(self):
        """INVARIANT: Sections with IDs go into .comments; sections without IDs
        go into .pending_comments. They never cross-contaminate."""
        md = """---
id: uuid-1
identifier: AI-1
title: Test
---

Body.

# Comments

## Bot - 2026-04-08T12:00:00Z
<!-- comment-id: existing-uuid -->

Already in Linear.

## Human - 2026-04-09T14:00:00Z

Not yet in Linear.
"""
        result = parse_markdown(md)
        assert len(result.comments) == 1
        assert result.comments[0].id == "existing-uuid"
        assert len(result.pending_comments) == 1
        assert result.pending_comments[0].author == "Human"
        assert result.pending_comments[0].id == ""

    def test_multiple_pending_comments_all_captured(self):
        """INVARIANT: Multiple human-authored comments are each captured independently."""
        md = """---
id: uuid-1
identifier: AI-1
title: Test
---

Body.

# Comments

## Alice - 2026-04-09T10:00:00Z

First pending.

## Bob - 2026-04-09T11:00:00Z

Second pending.
"""
        result = parse_markdown(md)
        assert len(result.pending_comments) == 2
        assert result.pending_comments[0].author == "Alice"
        assert result.pending_comments[1].author == "Bob"


# diff.py invariants


class TestDiffPendingComments:
    """Invariants for diff_markdown surfacing pending comments."""

    def test_pending_comment_appears_in_comments_pending(self):
        """INVARIANT: An ID-less comment in new content appears in diff.comments_pending,
        not in diff.comments_added."""
        old = _issue_md()
        comments = """
# Comments

## Aviad - 2026-04-09T10:00:00Z

Brand new human comment.
"""
        new = _issue_md(comments_section=comments)
        diff = diff_markdown(old, new)
        assert len(diff.comments_pending) == 1
        assert "Brand new human comment" in diff.comments_pending[0].body
        # Must NOT appear in comments_added (that's for ID'd sections from Linear)
        assert diff.comments_added == []

    def test_idd_comment_does_not_appear_in_pending(self):
        """INVARIANT: A comment WITH a comment-id appears in comments_added,
        never in comments_pending."""
        old = _issue_md()
        comments = """
# Comments

## Oz - 2026-04-08T12:00:00Z
<!-- comment-id: from-linear-uuid -->

Pulled from Linear.
"""
        new = _issue_md(comments_section=comments)
        diff = diff_markdown(old, new)
        assert len(diff.comments_added) == 1
        assert diff.comments_added[0].id == "from-linear-uuid"
        assert diff.comments_pending == []

    def test_pending_comment_triggers_has_changes(self):
        """INVARIANT: A pending comment counts as a change for has_changes."""
        old = _issue_md()
        comments = """
# Comments

## Aviad - 2026-04-09T10:00:00Z

New comment.
"""
        new = _issue_md(comments_section=comments)
        diff = diff_markdown(old, new)
        assert diff.has_changes is True


# push.py invariants — the core category-eliminating tests


class TestPushNeverDuplicatesLinearComments:
    """The fundamental invariant: a section with a comment-id already exists
    in Linear and must NEVER trigger create_comment."""

    @pytest.mark.asyncio
    async def test_comment_with_id_is_never_created(self, tmp_path):
        """INVARIANT: A comment WITH a <!-- comment-id: UUID --> is NEVER passed to
        create_comment, regardless of how it entered the diff.

        This is the category-eliminating invariant. It doesn't matter whether the
        comment-id appeared via a merge commit, cherry-pick, manual copy, or any
        other git operation. If it has an ID, it exists in Linear.
        """
        rel_path = "linear/teams/AI/issues/AI-1-fix-bug.md"
        _setup_state(tmp_path, rel_path, "uuid-ai-1")

        old_content = _issue_md()
        comments_from_linear = """
# Comments

## Oz Shaked - 2026-04-08T12:48:30Z
<!-- comment-id: 8e0e2f99-bc65-4860-97da-1554e87e703d -->

but this method resulted the really long ids

## Jakub Drozdek - 2026-04-08T12:45:40Z
<!-- comment-id: 3c559bdb-7885-4b28-bdef-21e652db8122 -->

I'd rather have slugs, similar to what our Django BE generates.
"""
        new_content = _issue_md(comments_section=comments_from_linear)

        changes = [
            push_mod.FileChange(
                path=rel_path,
                change_type="modified",
                old_content=old_content,
                new_content=new_content,
            )
        ]

        mock_client = _mock_linear_client()
        with patch.object(push_mod, "LinearClient", return_value=mock_client):
            await push_mod.push_changes(changes, "test-key", tmp_path)

        # The core invariant: NEVER create_comment for sections with IDs
        mock_client.create_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_only_pending_comments_are_created(self, tmp_path):
        """INVARIANT: Only comments WITHOUT a comment-id are passed to create_comment.

        A human writes a comment section without an ID. The push creates it in
        Linear and writes back the UUID so future pushes recognize it.
        """
        rel_path = "linear/teams/AI/issues/AI-1-fix-bug.md"
        _setup_state(tmp_path, rel_path, "uuid-ai-1")

        # Write the file on disk (push.py reads it for write-back)
        issue_dir = tmp_path / "linear" / "teams" / "AI" / "issues"
        issue_dir.mkdir(parents=True, exist_ok=True)

        old_content = _issue_md()
        human_comment = """
# Comments

## Aviad Rozenhek - 2026-04-09T15:00:00Z

This comment was written by a human in the markdown file.
"""
        new_content = _issue_md(comments_section=human_comment)
        (issue_dir / "AI-1-fix-bug.md").write_text(new_content)

        changes = [
            push_mod.FileChange(
                path=rel_path,
                change_type="modified",
                old_content=old_content,
                new_content=new_content,
            )
        ]

        mock_client = _mock_linear_client()
        with patch.object(push_mod, "LinearClient", return_value=mock_client):
            await push_mod.push_changes(changes, "test-key", tmp_path)

        # Human comment SHOULD be created
        mock_client.create_comment.assert_called_once()
        call_args = mock_client.create_comment.call_args[0]
        assert call_args[0] == "uuid-ai-1"
        assert "written by a human" in call_args[1]

    @pytest.mark.asyncio
    async def test_mixed_id_and_pending_only_pending_is_created(self, tmp_path):
        """INVARIANT: When both ID'd (from Linear) and ID-less (human) comments appear
        in the same diff, only the ID-less one triggers create_comment."""
        rel_path = "linear/teams/AI/issues/AI-1-fix-bug.md"
        _setup_state(tmp_path, rel_path, "uuid-ai-1")

        issue_dir = tmp_path / "linear" / "teams" / "AI" / "issues"
        issue_dir.mkdir(parents=True, exist_ok=True)

        old_content = _issue_md()
        mixed_comments = """
# Comments

## Bot-synced Author - 2026-04-08T12:00:00Z
<!-- comment-id: already-in-linear -->

This was pulled from Linear — must NOT be re-created.

## Human Author - 2026-04-09T15:00:00Z

This is new — SHOULD be created in Linear.
"""
        new_content = _issue_md(comments_section=mixed_comments)
        (issue_dir / "AI-1-fix-bug.md").write_text(new_content)

        changes = [
            push_mod.FileChange(
                path=rel_path,
                change_type="modified",
                old_content=old_content,
                new_content=new_content,
            )
        ]

        mock_client = _mock_linear_client()
        with patch.object(push_mod, "LinearClient", return_value=mock_client):
            await push_mod.push_changes(changes, "test-key", tmp_path)

        # Exactly 1 create_comment — the human one
        mock_client.create_comment.assert_called_once()
        body = mock_client.create_comment.call_args[0][1]
        assert "SHOULD be created" in body
        assert "must NOT be re-created" not in body


class TestPushWritesBackCommentId:
    """After creating a pending comment in Linear, the UUID must be written
    back to the file so the next push recognizes it as existing."""

    @pytest.mark.asyncio
    async def test_writeback_inserts_comment_id_marker(self, tmp_path):
        """INVARIANT: After creating a pending comment, the file on disk contains
        the new <!-- comment-id: UUID --> marker for that comment."""
        rel_path = "linear/teams/AI/issues/AI-1-fix-bug.md"
        _setup_state(tmp_path, rel_path, "uuid-ai-1")

        issue_dir = tmp_path / "linear" / "teams" / "AI" / "issues"
        issue_dir.mkdir(parents=True, exist_ok=True)
        file_path = issue_dir / "AI-1-fix-bug.md"

        old_content = _issue_md()
        human_comment = """
# Comments

## Aviad Rozenhek - 2026-04-09T15:00:00Z

My new comment.
"""
        new_content = _issue_md(comments_section=human_comment)
        file_path.write_text(new_content)

        changes = [
            push_mod.FileChange(
                path=rel_path,
                change_type="modified",
                old_content=old_content,
                new_content=new_content,
            )
        ]

        mock_client = _mock_linear_client()
        mock_client.create_comment.return_value = {"id": "linear-assigned-uuid-123"}

        with patch.object(push_mod, "LinearClient", return_value=mock_client):
            await push_mod.push_changes(changes, "test-key", tmp_path)

        # After push, the file should have the comment-id written back
        updated_content = file_path.read_text()
        assert "<!-- comment-id: linear-assigned-uuid-123 -->" in updated_content

    @pytest.mark.asyncio
    async def test_writeback_makes_comment_idempotent(self, tmp_path):
        """INVARIANT: After write-back, re-parsing the file produces the comment in
        .comments (with ID), not in .pending_comments. This means a second push
        will not re-create it."""
        rel_path = "linear/teams/AI/issues/AI-1-fix-bug.md"
        _setup_state(tmp_path, rel_path, "uuid-ai-1")

        issue_dir = tmp_path / "linear" / "teams" / "AI" / "issues"
        issue_dir.mkdir(parents=True, exist_ok=True)
        file_path = issue_dir / "AI-1-fix-bug.md"

        old_content = _issue_md()
        human_comment = """
# Comments

## Aviad Rozenhek - 2026-04-09T15:00:00Z

My new comment.
"""
        new_content = _issue_md(comments_section=human_comment)
        file_path.write_text(new_content)

        changes = [
            push_mod.FileChange(
                path=rel_path,
                change_type="modified",
                old_content=old_content,
                new_content=new_content,
            )
        ]

        mock_client = _mock_linear_client()
        mock_client.create_comment.return_value = {"id": "written-back-uuid"}

        with patch.object(push_mod, "LinearClient", return_value=mock_client):
            await push_mod.push_changes(changes, "test-key", tmp_path)

        # Re-parse the file after write-back
        updated_content = file_path.read_text()
        result = parse_markdown(updated_content)

        # Comment should now be in .comments (with ID), not in .pending_comments
        assert len(result.comments) >= 1
        ids = [c.id for c in result.comments]
        assert "written-back-uuid" in ids
        assert len(result.pending_comments) == 0
