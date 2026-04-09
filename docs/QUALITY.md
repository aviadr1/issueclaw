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

## Recommended Repo Settings

- Branch protection on `main` requiring CI + CodeQL checks.
- Dependabot alerts/security updates enabled.
- Auto-merge allowed for low-risk dependency update PRs after checks pass.
