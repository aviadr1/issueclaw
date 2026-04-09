# Why issueclaw

## Problem

Linear is excellent for planning, but for engineers and agent tooling it is usually:

- remote API state
- hard to grep at scale
- disconnected from code review and git history

## Solution

`issueclaw` mirrors Linear entities into markdown files in git and syncs both directions.

This gives you:

- full local `linear/**` markdown mirror for fast grep/search/edit workflows
- product changes reviewed in PRs
- one commit can atomically change code + issue state
- full auditability through git history
- local-first context for AI agents

## Operations Cost

After `init` and webhook/workflow hook setup, ongoing administration is minimal:

- sync is driven by hooks and CI automation
- day-to-day use is mostly `pull`/edit/`push`
- `workflows doctor` catches stub drift on upgrades

## Who Benefits Most

- teams already using PR-centric engineering workflows
- teams using agent systems (Claude Code, Codex, etc.)
- orgs that want issue-state change visibility at code-review time

## What issueclaw Is Not

- not a replacement for Linear UI collaboration features
- not a real-time shared text editor
- not an attachment binary sync system

## Next Docs

- setup: [INSTALL.md](INSTALL.md)
- architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
- sync behavior: [SYNC_PROTOCOL.md](SYNC_PROTOCOL.md)
