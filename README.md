# issueclaw

[![CI (main)](https://github.com/aviadr1/issueclaw/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/aviadr1/issueclaw/actions/workflows/ci.yml?query=branch%3Amain)
[![CodeQL (main)](https://github.com/aviadr1/issueclaw/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/aviadr1/issueclaw/actions/workflows/codeql.yml?query=branch%3Amain)
[![Coverage (main)](https://codecov.io/gh/aviadr1/issueclaw/branch/main/graph/badge.svg)](https://app.codecov.io/gh/aviadr1/issueclaw/tree/main)
[![Ruff](https://img.shields.io/badge/lint-ruff-46a2f1?logo=ruff&logoColor=white)](https://docs.astral.sh/ruff/)
[![Basedpyright](https://img.shields.io/badge/types-basedpyright-5a45ff)](https://github.com/DetachHead/basedpyright)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://pre-commit.com/)
[![pytest](https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest&logoColor=white)](https://docs.pytest.org/)
[![Dependabot](https://img.shields.io/badge/dependabot-enabled-025E8C?logo=dependabot)](https://github.com/aviadr1/issueclaw/security/dependabot)

Mirror Linear into local markdown so developers and agents can work against files, not slow paginated API calls.

## Why Developers Care

- `linear/**` gives you a full local mirror of Linear in `.md` files.
- Local grep and file reads are dramatically faster than repeated API requests.
- Requirement/status changes are reviewed in the same PR as code.
- One commit can update code and project state together.

## Why This Is Great For Claude/Codex

Agent systems are best with local files. `issueclaw` gives them all Linear context as markdown, so they can:

- search backlog context instantly with `rg`
- edit issues and code in one branch
- reason over issue history via git instead of remote-only state

## Low-Ops by Design

After setup, administration is minimal:

- workflow stubs + webhook hooks handle synchronization
- CI executes pull/push hooks automatically
- `issueclaw workflows doctor` detects drift when upgrading

## Setup Is Two Separate Steps

`issueclaw` has two different setup scopes:

1. Install the `issueclaw` CLI tool on your machine/CI runner.
2. Initialize a target repository that will hold the Linear markdown mirror (`linear/**`).

Installing the CLI does not create a mirror repo. `issueclaw init` does.

## Step 1: Install The CLI

### Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/aviadr1/issueclaw/main/install.sh | sh
```

### Manual install

```bash
uv tool install git+https://github.com/aviadr1/issueclaw.git
```

### Upgrade

```bash
issueclaw self update
```

## Step 2: Initialize A Mirror Repo

Choose or create the repository that should store your Linear mirror files.

```bash
# Example: create a dedicated mirror repo
mkdir -p /path/to/linear-git
cd /path/to/linear-git
git init
```

Then run `issueclaw init` against that repo:

```bash
export LINEAR_API_KEY=lin_api_...
issueclaw init --repo-dir /path/to/linear-git --webhook-url https://your-worker.workers.dev
```

What `init` sets up in that target repo:

- `linear/**` markdown mirror (issues/projects/documents/etc.)
- `.sync/**` sync metadata
- `.github/workflows/issueclaw-*.yaml` workflow stubs/hooks

## Quick Start (After Init)

```bash
# 1) API key
export LINEAR_API_KEY=lin_api_...

# 2) Verify hooks/workflow stubs after upgrades
issueclaw workflows doctor --repo-dir /path/to/linear-git

# 3) Day-to-day usage
issueclaw pull --repo-dir /path/to/linear-git
issueclaw diff --repo-dir /path/to/linear-git
issueclaw push --repo-dir /path/to/linear-git
```

## Common Commands

- `issueclaw pull`: sync Linear -> local markdown mirror.
- `issueclaw push`: sync markdown diffs -> Linear.
- `issueclaw diff`: preview what would be pushed.
- `issueclaw apply-webhook`: apply one webhook payload locally.
- `issueclaw workflows doctor|upgrade`: detect/repair workflow hook drift.
- `issueclaw create issue|comment|project|initiative|document`: create entities directly.

## Documentation

- Installation and setup: [docs/INSTALL.md](docs/INSTALL.md)
- Usage guide: [docs/USAGE.md](docs/USAGE.md)
- Why issueclaw: [docs/WHY_ISSUECLAW.md](docs/WHY_ISSUECLAW.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Sync protocol: [docs/SYNC_PROTOCOL.md](docs/SYNC_PROTOCOL.md)
- Markdown schema: [docs/MARKDOWN_FORMAT.md](docs/MARKDOWN_FORMAT.md)
- Workflow lifecycle and drift handling: [docs/WORKFLOW_LIFECYCLE.md](docs/WORKFLOW_LIFECYCLE.md)
- CI/quality/reporting: [docs/QUALITY.md](docs/QUALITY.md)
- Full technical legacy reference: [docs/REFERENCE_FULL.md](docs/REFERENCE_FULL.md)
