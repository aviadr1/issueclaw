# Workflow Lifecycle

This document defines how `issueclaw` workflow templates are managed across
tool releases and host repositories.

## Goals

- Single source of truth for workflow templates.
- Safe upgrades without manual YAML surgery.
- Deterministic drift detection and repair.
- Stable operational contract for host repos.

## Source Of Truth

- Bundled templates live in `src/issueclaw/workflows/`.
- Managed templates are discovered dynamically:
  - filename starts with `issueclaw-`
  - extension is `.yaml`
- `issueclaw init` and `issueclaw workflows upgrade` both write from this source.

## Host Repo Contract

`issueclaw` manages only these generated files under `.github/workflows/`:

- `issueclaw-push.yaml`
- `issueclaw-webhook.yaml`
- `issueclaw-sync.yaml`
- plus any future `issueclaw-*.yaml` bundled by the tool

The generated files are intentionally thin callers that delegate to reusable
workflows in this repository.

## Commands

- `issueclaw workflows doctor`
  - reports missing/unmanaged/drifted managed templates.
  - with `--strict`, exits non-zero if problems are found.
- `issueclaw workflows upgrade`
  - rewrites all managed templates from the bundled source of truth.

## Operational Guidance

1. Run `issueclaw init` once for new host repos.
2. After upgrading `issueclaw`, run:
   - `issueclaw workflows doctor`
   - `issueclaw workflows upgrade` when drift or new templates are detected
3. Keep branch protection requiring stable checks (`lint`, `types`, `test`, `CodeQL`).

## Failure Categories This Prevents

- Template drift across host repos.
- Missing scheduled sync template on init.
- Manual edits silently diverging from maintained stubs.
- Undetected contract mismatch after tool upgrades.
