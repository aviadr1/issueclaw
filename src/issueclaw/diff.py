"""Field-level diff between old and new markdown files."""

from __future__ import annotations

from dataclasses import dataclass, field

from issueclaw.parse import ParsedSection, parse_markdown


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
    comments_added: list[ParsedSection] = field(default_factory=list)
    comments_removed: list[ParsedSection] = field(default_factory=list)
    comments_edited: list[ParsedSection] = field(default_factory=list)
    updates_added: list[ParsedSection] = field(default_factory=list)
    updates_removed: list[ParsedSection] = field(default_factory=list)
    updates_edited: list[ParsedSection] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.frontmatter_changes
            or self.body_changed
            or self.comments_added
            or self.comments_removed
            or self.comments_edited
            or self.updates_added
            or self.updates_removed
            or self.updates_edited
        )


def _diff_sections(
    old_sections: list[ParsedSection],
    new_sections: list[ParsedSection],
) -> tuple[list[ParsedSection], list[ParsedSection], list[ParsedSection]]:
    """Diff two lists of sections by ID. Returns (added, removed, edited)."""
    old_by_id = {s.id: s for s in old_sections}
    new_by_id = {s.id: s for s in new_sections}

    added = [s for sid, s in new_by_id.items() if sid not in old_by_id]
    edited = [
        s for sid, s in new_by_id.items()
        if sid in old_by_id and s.body.strip() != old_by_id[sid].body.strip()
    ]
    removed = [s for sid, s in old_by_id.items() if sid not in new_by_id]

    return added, removed, edited


def diff_markdown(old_content: str, new_content: str) -> MarkdownDiff:
    """Compute field-level diff between two markdown files.

    Parses both files, compares frontmatter field by field,
    detects body changes, and diffs comments and updates by ID.
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

    # Diff comments and updates using shared logic
    result.comments_added, result.comments_removed, result.comments_edited = _diff_sections(
        old.comments, new.comments
    )
    result.updates_added, result.updates_removed, result.updates_edited = _diff_sections(
        old.updates, new.updates
    )

    return result
