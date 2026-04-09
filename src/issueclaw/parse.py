"""Parse markdown files with YAML frontmatter back into structured data."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml


@dataclass
class ParsedSection:
    """A section extracted from a markdown ## block (comment or project update)."""

    id: str
    author: str
    timestamp: str
    body: str
    health: str = ""


# Backward-compatible alias
ParsedComment = ParsedSection


@dataclass
class ParsedMarkdown:
    """Result of parsing a markdown file with frontmatter."""

    frontmatter: dict
    body: str
    comments: list[ParsedSection] = field(default_factory=list)
    updates: list[ParsedSection] = field(default_factory=list)
    pending_comments: list[ParsedSection] = field(default_factory=list)
    pending_updates: list[ParsedSection] = field(default_factory=list)


# Matches: ## Author - Timestamp  or  ## Author - Timestamp [health]
_SECTION_HEADER_RE = re.compile(r"^## (.+?) - (\S+?)(?:\s+\[(.+?)\])?$")
_SECTION_ID_RE = re.compile(r"<!-- (?:comment-id|update-id): (.+?) -->")


def _parse_sections(text: str) -> tuple[list[ParsedSection], list[ParsedSection]]:
    """Parse ## Author - timestamp [health] sections with ID markers.

    Returns (id_sections, pending_sections):
    - id_sections: sections WITH a <!-- comment-id/update-id: UUID --> marker
      (already exist in Linear)
    - pending_sections: sections WITHOUT an ID marker (human-authored, pending push)
    """
    id_sections: list[ParsedSection] = []
    pending_sections: list[ParsedSection] = []
    lines = text.split("\n")

    current_author = ""
    current_timestamp = ""
    current_id = ""
    current_health = ""
    current_body_lines: list[str] = []
    in_section = False

    def _save_current_section() -> None:
        section = ParsedSection(
            id=current_id,
            author=current_author,
            timestamp=current_timestamp,
            body="\n".join(current_body_lines).strip(),
            health=current_health,
        )
        if current_id:
            id_sections.append(section)
        else:
            pending_sections.append(section)

    for line in lines:
        header_match = _SECTION_HEADER_RE.match(line)
        if header_match:
            # Save previous section if exists
            if in_section:
                _save_current_section()
            # Start new section
            current_author = header_match.group(1)
            current_timestamp = header_match.group(2)
            current_health = header_match.group(3) or ""
            current_id = ""
            current_body_lines = []
            in_section = True
            continue

        if in_section:
            id_match = _SECTION_ID_RE.match(line)
            if id_match:
                current_id = id_match.group(1)
                continue
            current_body_lines.append(line)

    # Save last section
    if in_section:
        _save_current_section()

    return id_sections, pending_sections


def _extract_named_section(text: str, section_name: str) -> tuple[str, str]:
    """Extract a named # section from text.

    Returns (remaining_text, section_content).
    Section content is everything between the header and the next # header or end of text.
    """
    pattern = re.compile(rf"\n# {re.escape(section_name)}\n")
    match = pattern.search(text)
    if not match:
        return text, ""

    start = match.start()
    after = text[match.end() :]

    # Find the next H1 heading
    next_h1 = re.search(r"\n# ", after)
    if next_h1:
        section_content = after[: next_h1.start()]
        remaining = text[:start] + after[next_h1.start() :]
    else:
        section_content = after
        remaining = text[:start]

    return remaining, section_content


def parse_markdown(content: str) -> ParsedMarkdown:
    """Parse a markdown file into frontmatter, body, comments, and updates.

    Expected format:
        ---
        key: value
        ---

        Body text.

        # Comments

        ## author - timestamp
        <!-- comment-id: uuid -->

        Comment body.

        # Status Updates

        ## author - timestamp [health]
        <!-- update-id: uuid -->

        Update body.
    """
    # Split frontmatter
    if not content.startswith("---"):
        return ParsedMarkdown(frontmatter={}, body=content, comments=[], updates=[])

    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return ParsedMarkdown(frontmatter={}, body=content, comments=[], updates=[])

    frontmatter = yaml.safe_load(parts[1]) or {}
    rest = parts[2]

    # Extract named sections, leaving everything else as body
    rest, comments_text = _extract_named_section(rest, "Comments")
    rest, updates_text = _extract_named_section(rest, "Status Updates")

    comments, pending_comments = (
        _parse_sections(comments_text) if comments_text else ([], [])
    )
    updates, pending_updates = (
        _parse_sections(updates_text) if updates_text else ([], [])
    )

    return ParsedMarkdown(
        frontmatter=frontmatter,
        body=rest,
        comments=comments,
        updates=updates,
        pending_comments=pending_comments,
        pending_updates=pending_updates,
    )
