# issueclaw: Issues as Code for AI-Native Development

[![CI (main)](https://github.com/aviadr1/issueclaw/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/aviadr1/issueclaw/actions/workflows/ci.yml?query=branch%3Amain)
[![CodeQL (main)](https://github.com/aviadr1/issueclaw/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/aviadr1/issueclaw/actions/workflows/codeql.yml?query=branch%3Amain)
[![Coverage (main)](https://codecov.io/gh/aviadr1/issueclaw/branch/main/graph/badge.svg)](https://app.codecov.io/gh/aviadr1/issueclaw/tree/main)
[![Dependabot](https://img.shields.io/badge/dependabot-enabled-025E8C?logo=dependabot)](https://github.com/aviadr1/issueclaw/security/dependabot)
[![Ruff](https://img.shields.io/badge/lint-ruff-46a2f1?logo=ruff&logoColor=white)](https://docs.astral.sh/ruff/)
[![Basedpyright](https://img.shields.io/badge/types-basedpyright-5a45ff)](https://github.com/DetachHead/basedpyright)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://pre-commit.com/)
[![pytest](https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest&logoColor=white)](https://docs.pytest.org/)

`issueclaw` syncs Linear <-> Git using Markdown files and git diffs.

You edit issues like code, review them in PRs, and let CI push the changes back to Linear.

## Why This Is Awesome For AI Developers

AI coding agents are best with local files, fast grep, and versioned context.

With `issueclaw`, your backlog becomes local Markdown in your repo:

- Agents can `rg` your issues instantly.
- Agents can propose code + issue updates in one PR.
- Reviewers can see product intent and code changes together.
- Git history gives full traceability of requirement changes.

In short: your project management stops being an API silo and becomes first-class repo context for humans and agents.

## What issueclaw Does

- Pulls Linear entities into Markdown files (`issueclaw pull`).
- Applies Linear webhooks into Git commits (`issueclaw apply-webhook`).
- Pushes Markdown diffs back to Linear (`issueclaw push`).
- Keeps workflow stubs healthy (`issueclaw workflows doctor|upgrade`).

Supported entities include issues, comments, projects, initiatives, and documents.

## Install

### Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/aviadr1/issueclaw/main/install.sh | sh
```

### Manual Install

```bash
uv tool install git+https://github.com/aviadr1/issueclaw.git
```

### Upgrade

```bash
issueclaw self update
```

## Quick Start

```bash
# 1) Set Linear API key
export LINEAR_API_KEY=lin_api_...

# 2) Initialize a target repo (installs workflow stubs + sets up pull bootstrap)
issueclaw init --repo-dir /path/to/linear-git --webhook-url https://your-worker.workers.dev

# 3) Validate workflow stubs after upgrades
issueclaw workflows doctor --repo-dir /path/to/linear-git
issueclaw workflows upgrade --repo-dir /path/to/linear-git

# 4) Pull / diff / push loop
issueclaw pull --repo-dir /path/to/linear-git
issueclaw diff --repo-dir /path/to/linear-git
issueclaw push --repo-dir /path/to/linear-git
```

## Deep Docs

- Install and operational setup: [docs/INSTALL.md](docs/INSTALL.md)
- Workflow lifecycle and drift prevention: [docs/WORKFLOW_LIFECYCLE.md](docs/WORKFLOW_LIFECYCLE.md)
- Full technical reference (architecture, protocol, mappings, tradeoffs): [docs/REFERENCE_FULL.md](docs/REFERENCE_FULL.md)
- Original implementation plan: [docs/plans/2026-03-09-issueclaw-implementation.md](docs/plans/2026-03-09-issueclaw-implementation.md)

## CI And Reports

- CI runs on `main`: <https://github.com/aviadr1/issueclaw/actions/workflows/ci.yml?query=branch%3Amain>
- CodeQL runs on `main`: <https://github.com/aviadr1/issueclaw/actions/workflows/codeql.yml?query=branch%3Amain>
- Coverage dashboard: <https://app.codecov.io/gh/aviadr1/issueclaw/tree/main>
- Dependabot alerts/PRs: <https://github.com/aviadr1/issueclaw/security/dependabot>
