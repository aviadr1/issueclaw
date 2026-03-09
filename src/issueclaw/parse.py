"""Parse markdown files with YAML frontmatter back into structured data."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml


@dataclass
class ParsedComment:
    """A comment extracted from a markdown file."""

    id: str
    author: str
    timestamp: str
    body: str


@dataclass
class ParsedMarkdown:
    """Result of parsing a markdown file with frontmatter."""

    frontmatter: dict
    body: str
    comments: list[ParsedComment] = field(default_factory=list)


_COMMENT_HEADER_RE = re.compile(r"^## (.+?) - (\S+)$")
_COMMENT_ID_RE = re.compile(r"<!-- comment-id: (.+?) -->")


def parse_markdown(content: str) -> ParsedMarkdown:
    """Parse a markdown file into frontmatter, body, and comments.

    Expected format:
        ---
        key: value
        ---

        Body text.

        # Comments

        ## author - timestamp
        <!-- comment-id: uuid -->

        Comment body.
    """
    # Split frontmatter
    if not content.startswith("---"):
        return ParsedMarkdown(frontmatter={}, body=content, comments=[])

    parts = content.split("---\n", 2)
    if len(parts) < 3:
        return ParsedMarkdown(frontmatter={}, body=content, comments=[])

    frontmatter = yaml.safe_load(parts[1]) or {}
    rest = parts[2]

    # Split body from comments section
    comments_split = re.split(r"\n# Comments\n", rest, maxsplit=1)
    body = comments_split[0]
    comments: list[ParsedComment] = []

    if len(comments_split) > 1:
        comments = _parse_comments(comments_split[1])

    return ParsedMarkdown(frontmatter=frontmatter, body=body, comments=comments)


def _parse_comments(comments_text: str) -> list[ParsedComment]:
    """Parse the ## Comments section into individual comments."""
    comments: list[ParsedComment] = []
    lines = comments_text.split("\n")

    current_author = ""
    current_timestamp = ""
    current_id = ""
    current_body_lines: list[str] = []
    in_comment = False

    for line in lines:
        header_match = _COMMENT_HEADER_RE.match(line)
        if header_match:
            # Save previous comment if exists
            if in_comment and current_id:
                comments.append(
                    ParsedComment(
                        id=current_id,
                        author=current_author,
                        timestamp=current_timestamp,
                        body="\n".join(current_body_lines).strip(),
                    )
                )
            # Start new comment
            current_author = header_match.group(1)
            current_timestamp = header_match.group(2)
            current_id = ""
            current_body_lines = []
            in_comment = True
            continue

        if in_comment:
            id_match = _COMMENT_ID_RE.match(line)
            if id_match:
                current_id = id_match.group(1)
                continue
            current_body_lines.append(line)

    # Save last comment
    if in_comment and current_id:
        comments.append(
            ParsedComment(
                id=current_id,
                author=current_author,
                timestamp=current_timestamp,
                body="\n".join(current_body_lines).strip(),
            )
        )

    return comments
