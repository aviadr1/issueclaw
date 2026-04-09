# Markdown Format

issueclaw renders Linear entities as markdown with YAML frontmatter.

## Issue (example)

```md
---
id: uuid
identifier: AI-123
title: Fix login bug
status: Todo
priority: 2
assignee: Aviad
labels:
- Bug
url: https://linear.app/...
created: '2026-01-01T00:00:00Z'
updated: '2026-01-02T00:00:00Z'
---

# AI-123: Fix login bug

Issue description body.

# Comments

## Aviad - 2026-01-02T10:00:00Z
<!-- comment-id: comment-uuid -->

Comment body.
```

## Notes

- Frontmatter fields map to Linear API fields.
- `comment-id` markers make comment sync idempotent.
- Project updates and other entity files follow similar conventions.

For full mappings and long examples, see [REFERENCE_FULL.md](REFERENCE_FULL.md).
