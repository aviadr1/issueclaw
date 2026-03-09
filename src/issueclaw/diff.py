"""Field-level diff between old and new markdown files."""

from __future__ import annotations

from dataclasses import dataclass, field

from issueclaw.parse import ParsedComment, parse_markdown


@dataclass
class FieldDiff:
    """A single field change."""

    old: object
    new: object


@dataclass
class MarkdownDiff:
    """Result of diffing two markdown files."""

    frontmatter_changes: dict[str, FieldDiff] = field(default_factory=dict)
    body_changed: bool = False
    new_body: str = ""
    comments_added: list[ParsedComment] = field(default_factory=list)
    comments_removed: list[ParsedComment] = field(default_factory=list)
    comments_edited: list[ParsedComment] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.frontmatter_changes
            or self.body_changed
            or self.comments_added
            or self.comments_removed
            or self.comments_edited
        )


def diff_markdown(old_content: str, new_content: str) -> MarkdownDiff:
    """Compute field-level diff between two markdown files.

    Parses both files, compares frontmatter field by field,
    detects body changes, and diffs comments by comment-id.
    """
    old = parse_markdown(old_content)
    new = parse_markdown(new_content)

    result = MarkdownDiff()

    # Diff frontmatter
    all_keys = set(old.frontmatter) | set(new.frontmatter)
    for key in all_keys:
        old_val = old.frontmatter.get(key)
        new_val = new.frontmatter.get(key)
        if old_val != new_val:
            result.frontmatter_changes[key] = FieldDiff(old=old_val, new=new_val)

    # Diff body (strip to avoid whitespace-only diffs)
    if old.body.strip() != new.body.strip():
        result.body_changed = True
        result.new_body = new.body

    # Diff comments by ID
    old_by_id = {c.id: c for c in old.comments}
    new_by_id = {c.id: c for c in new.comments}

    for cid, comment in new_by_id.items():
        if cid not in old_by_id:
            result.comments_added.append(comment)
        elif comment.body.strip() != old_by_id[cid].body.strip():
            result.comments_edited.append(comment)

    for cid, comment in old_by_id.items():
        if cid not in new_by_id:
            result.comments_removed.append(comment)

    return result
