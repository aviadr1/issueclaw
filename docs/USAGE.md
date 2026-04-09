# Usage Guide

## The Real Day-to-Day Usage

`issueclaw` is primarily a local Linear mirror.

You pull once and get `linear/**` markdown files for issues/projects/documents/comments, then work against files (fast grep, local edits, git diffs) instead of live API pagination.

## Core Loop

```bash
issueclaw pull --repo-dir /path/to/linear-git
# inspect/edit files under linear/**
issueclaw diff --repo-dir /path/to/linear-git
issueclaw push --repo-dir /path/to/linear-git
```

## Admin Overhead Is Minimal

After initial setup (`init` + webhook/workflow hooks), ongoing administration is mostly automatic:

- webhook-triggered sync keeps local mirror fresh
- push workflows sync markdown changes back to Linear
- `workflows doctor` catches drift after upgrades

## Typical Workflow

1. Pull latest Linear state into local markdown.
2. Edit code and related `linear/**` files in one branch.
3. Review all changes in one PR.
4. Merge; CI/hooks sync changes safely.

## Agent Workflow (Claude/Codex)

1. Pull all project context to local files.
2. Agent searches and reasons using `rg` + markdown files.
3. Agent proposes code + issue changes in same PR.
4. Team reviews and merges as normal.

## Useful Commands

```bash
issueclaw status --repo-dir /path/to/linear-git
issueclaw diff --repo-dir /path/to/linear-git
issueclaw pull --repo-dir /path/to/linear-git --teams AI,ENG
issueclaw --json status --repo-dir /path/to/linear-git
```

## See Also

- Install/setup: [INSTALL.md](INSTALL.md)
- Sync details: [SYNC_PROTOCOL.md](SYNC_PROTOCOL.md)
- Markdown format: [MARKDOWN_FORMAT.md](MARKDOWN_FORMAT.md)
