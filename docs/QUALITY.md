# Quality And CI

## What Runs On PRs And Main

- CI workflow (`.github/workflows/ci.yml`):
  - Ruff lint + format checks
  - Basedpyright type checking
  - pytest test suite
  - coverage upload to Codecov
- CodeQL workflow (`.github/workflows/codeql.yml`): Python static security analysis.

## Reports

- CI runs: <https://github.com/aviadr1/issueclaw/actions/workflows/ci.yml?query=branch%3Amain>
- CodeQL runs: <https://github.com/aviadr1/issueclaw/actions/workflows/codeql.yml?query=branch%3Amain>
- Coverage: <https://app.codecov.io/gh/aviadr1/issueclaw/tree/main>
- Dependabot: <https://github.com/aviadr1/issueclaw/security/dependabot>

## Local Developer Guardrails

- Pre-commit hooks enforce Ruff and Basedpyright checks.
- Run before commit:

```bash
pre-commit run --all-files
```

## Dependency Updates

Dependabot checks Python dependencies with the `uv` ecosystem so updates keep
`pyproject.toml` and `uv.lock` together. CI installs with `uv sync --locked` and
rejects an out-of-date lockfile. After changing dependencies locally, run `uv lock`
and commit both files.

The Dependabot Auto Merge workflow enables squash auto-merge for non-draft PRs
authored by `dependabot[bot]`, from this repository, targeting `main`. It also runs
when a maintainer updates or labels a Dependabot PR. It never checks out PR code
and does not require permission to approve reviews.

Version updates remain grouped into patch and minor updates; major version
updates are ignored by `.github/dependabot.yml`. Security PRs created by
Dependabot are also eligible for auto-merge.

## Required Repo Settings

- Branch protection on `main` requiring CI + CodeQL checks.
- Dependabot alerts/security updates enabled.
- Allow auto-merge. Required checks (`lint`, `types`, `test`, and `CodeQL`) and
  conversation resolution must pass before GitHub merges a PR. Keep these branch
  protections enabled, including enforcement for administrators.
- GitHub Actions approval permission can remain disabled: this repository does
  not require approving reviews. If that policy changes, arrange an approval
  before expecting auto-merge to complete.
