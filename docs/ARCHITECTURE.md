# Architecture

## High-Level Model

- Source of truth for editable artifacts: git repo (`linear/**` markdown).
- Sync engine runs in CI and webhook handlers.
- Linear remains the PM system of record externally; git is the editable operational surface.

## Main Components

- `issueclaw pull`: fetches from Linear and renders markdown.
- `issueclaw push`: parses git diffs and sends minimal field updates to Linear.
- `issueclaw apply-webhook`: applies a webhook payload to local markdown.
- `.sync/id-map.json`: path <-> UUID mapping.
- `.sync/state.json`: incremental sync state.

## Workflow Layout

- Reusable workflow logic lives in this repo under `.github/workflows/*.yml`.
- Host repos use thin stubs under `.github/workflows/issueclaw-*.yaml`.
- `issueclaw workflows doctor|upgrade` keeps host stubs healthy.

See also: [WORKFLOW_LIFECYCLE.md](WORKFLOW_LIFECYCLE.md)
