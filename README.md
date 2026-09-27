# issueclaw

[![CI (main)](https://github.com/aviadr1/issueclaw/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/aviadr1/issueclaw/actions/workflows/ci.yml?query=branch%3Amain)
[![CodeQL (main)](https://github.com/aviadr1/issueclaw/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/aviadr1/issueclaw/actions/workflows/codeql.yml?query=branch%3Amain)
[![Coverage (main)](https://codecov.io/gh/aviadr1/issueclaw/branch/main/graph/badge.svg)](https://app.codecov.io/gh/aviadr1/issueclaw/tree/main)
[![License: MIT](https://img.shields.io/github/license/aviadr1/issueclaw)](https://github.com/aviadr1/issueclaw/blob/main/LICENSE)
[![Ruff](https://img.shields.io/badge/lint-ruff-46a2f1?logo=ruff&logoColor=white)](https://docs.astral.sh/ruff/)
[![Basedpyright](https://img.shields.io/badge/types-basedpyright-5a45ff)](https://github.com/DetachHead/basedpyright)

**Your Linear workspace as markdown files in a git repo, synced in both directions.**

Linear lives behind a paginated API, so every search is a request, AI agents can't just read the backlog, and issue changes never show up in code review. issueclaw mirrors issues, projects, initiatives, and documents into `linear/**/*.md`. You search the backlog with `rg` instead of the API, and agents read and edit issues as plain files. Edits you commit go back to Linear, field by field.

![issueclaw status, rg over the mirror, an edited issue, and issueclaw diff previewing the push to Linear](https://raw.githubusercontent.com/aviadr1/issueclaw/main/docs/demo.gif)

<sub>The demo runs on a fixture mirror of three issues (seeded by [`docs/demo_mirror.py`](https://github.com/aviadr1/issueclaw/blob/main/docs/demo_mirror.py) with issueclaw's own renderer), so it needs no Linear account. The `issueclaw status`, `rg`, and `issueclaw diff` output is real. Re-record it with `vhs docs/demo.tape`.</sub>

## Install

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install git+https://github.com/aviadr1/issueclaw.git
issueclaw --version
```

issueclaw is not on PyPI yet. After the first release, `uv tool install issueclaw` or `pip install issueclaw` will work too.

## Quick start

Mirror your workspace into a new git repo. This only reads from Linear:

```bash
export LINEAR_API_KEY=lin_api_...   # https://linear.app/settings/api
mkdir linear-git && cd linear-git && git init
issueclaw pull                      # add --teams ENG to mirror one team
git add -A && git commit -m "issueclaw pull"
issueclaw status
```

Search it like code:

```bash
rg -l "^status: In Progress" linear/teams/*/issues/
```

Change an issue by editing its file, then commit. `issueclaw diff` shows what would be sent, and `issueclaw push` sends it:

```bash
sed -i 's/^status: Todo/status: In Progress/' linear/teams/ENG/issues/ENG-31-*.md
git commit -am "Start ENG-31"
issueclaw diff
issueclaw push
```

`diff` and `push` compare the last commit with its parent, so commit your edits first.

## What you get

Each Linear entity is one markdown file with YAML frontmatter:

```
linear/
  teams/{TEAM}/issues/{ID}-{slug}.md       issues, with their comments
  projects/{slug}/_project.md              projects
  projects/{slug}/milestones/{name}.md     project milestones
  projects/{slug}/updates/{date-author}.md project status updates
  initiatives/{slug}.md
  documents/{slug}.md
  new/{TEAM}/{slug}.md                     drop a file here to create an issue
.sync/                                     path <-> Linear ID map, sync state
```

This is one issue from the demo, with its first 12 lines shown (`head -12`):

```markdown
---
id: fixture-eng-31
identifier: ENG-31
title: Retry failed webhook deliveries
status: Todo
priority: 3
assignee: dev
labels:
- reliability
created: '2026-09-12T09:00:00Z'
updated: '2026-09-18T11:00:00Z'
url: https://linear.app/example/issue/ENG-31
```

After the one-line edit and commit above, `issueclaw diff` prints:

```
1 file(s) changed:

  MODIFIED   linear/teams/ENG/issues/ENG-31-retry-failed-webhook-deliveries.md
             status: Todo → In Progress
```

## Why issueclaw

- **Files, not API calls.** `rg`, `cat`, and your editor work on the whole backlog offline, with no pagination and no rate limits on reads.
- **Built for AI agents.** Claude Code, Codex, and other agents read and edit issues with the file tools they already use. `issueclaw self skill` prints a bundled agent guide, and `--json` gives machine-readable output.
- **Field-level push.** `push` sends only the fields that changed in the commit. An issue's title, status, priority, assignee, estimate, and due date, its description, and new comments all sync. A status edit does not overwrite a description someone changed in Linear.
- **Issues change in the same PR as the code.** One commit can fix the bug and move the issue to Done. Reviewers see both, and git history becomes the audit log.
- **Create from git.** Drop `linear/new/ENG/my-idea.md`, push, and CI creates the issue and moves the file to its canonical path. Deleting an issue file archives the issue.
- **Runs itself.** `issueclaw init` installs GitHub Actions workflows: webhook-driven updates from Linear, a catch-up `issueclaw pull` every 10 minutes, and `issueclaw push` on every push to `main` that touches `linear/**`. `issueclaw workflows doctor` reports drift after upgrades.

## Automate it with `issueclaw init`

`init` turns a mirror repo into a synced one. It saves `LINEAR_API_KEY` to a gitignored `.env`, copies the workflow stubs to `.github/workflows/`, sets the `LINEAR_API_KEY` repo secret if the `gh` CLI is available, and runs the first pull. With `--webhook-url` it also registers a Linear webhook that points at your webhook proxy ([`workers/issueclaw-webhook-proxy`](https://github.com/aviadr1/issueclaw/tree/main/workers/issueclaw-webhook-proxy), a Cloudflare Worker).

```bash
export LINEAR_API_KEY=lin_api_...
issueclaw init --repo-dir /path/to/linear-git --webhook-url https://your-worker.workers.dev
```

After upgrading issueclaw, check the workflow stubs:

```bash
issueclaw workflows doctor --repo-dir /path/to/linear-git
```

## Commands

- `issueclaw pull`: sync Linear to the local markdown mirror.
- `issueclaw push`: sync committed markdown changes to Linear.
- `issueclaw diff`: preview what `push` would send.
- `issueclaw status`: entity counts and last sync time.
- `issueclaw create issue|comment|project|initiative|document`: create entities directly through the API.
- `issueclaw guard`: fail fast on new `linear/**` files in unsupported locations.
- `issueclaw apply-webhook`: apply one Linear webhook payload locally.
- `issueclaw workflows doctor|upgrade`: detect or repair workflow stub drift.
- `issueclaw self detect|update|skill`: installation info, upgrade, and the agent guide.

## Upgrade

A git install upgrades with `issueclaw self update`, which reinstalls from GitHub `main` using uv. Once issueclaw is on PyPI, upgrade a PyPI install with `uv tool upgrade issueclaw` or `pip install -U issueclaw` instead, because `self update` would switch it to the git version.

## Documentation

- Installation and setup: [docs/INSTALL.md](https://github.com/aviadr1/issueclaw/blob/main/docs/INSTALL.md)
- Usage guide: [docs/USAGE.md](https://github.com/aviadr1/issueclaw/blob/main/docs/USAGE.md)
- Why issueclaw: [docs/WHY_ISSUECLAW.md](https://github.com/aviadr1/issueclaw/blob/main/docs/WHY_ISSUECLAW.md)
- Architecture: [docs/ARCHITECTURE.md](https://github.com/aviadr1/issueclaw/blob/main/docs/ARCHITECTURE.md)
- Sync protocol: [docs/SYNC_PROTOCOL.md](https://github.com/aviadr1/issueclaw/blob/main/docs/SYNC_PROTOCOL.md)
- Markdown schema: [docs/MARKDOWN_FORMAT.md](https://github.com/aviadr1/issueclaw/blob/main/docs/MARKDOWN_FORMAT.md)
- Workflow lifecycle and drift handling: [docs/WORKFLOW_LIFECYCLE.md](https://github.com/aviadr1/issueclaw/blob/main/docs/WORKFLOW_LIFECYCLE.md)
- CI, quality, and reporting: [docs/QUALITY.md](https://github.com/aviadr1/issueclaw/blob/main/docs/QUALITY.md)
- Full technical reference: [docs/REFERENCE_FULL.md](https://github.com/aviadr1/issueclaw/blob/main/docs/REFERENCE_FULL.md)

## License

MIT
