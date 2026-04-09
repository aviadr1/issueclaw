# Sync Protocol

## Directions

## Git -> Linear (`push`)

1. Detect changed files under `linear/**` using git diff.
2. Parse markdown frontmatter/body/comments.
3. Compute minimal field-level diff.
4. Call targeted Linear mutations.
5. Write back generated IDs when needed (for example new comments).

## Linear -> Git (`pull` and webhook)

1. Fetch changed entities from Linear API.
2. Render canonical markdown.
3. Update files + mapping/state in repo.
4. Commit only when content actually changed.

## Delivery Guarantees And Event Routing

- Realtime path (webhook): `Issue`, `Project`, `Initiative`, and `Comment` events with `data.issueId`.
- Batched path (incremental pull every 10 minutes): `Document` events.
- Ignored in webhook by design: `Comment` events without `data.issueId` (not representable in issue markdown; would be no-op in `apply-webhook`).
- Queue recovery path: scheduled queue sweep retries `linear/new/**` creation via `issueclaw push` every 10 minutes.
- Correctness backstop: scheduled `issueclaw pull` always runs with `cancel-in-progress: false` and uses `updated_after=last_sync`.
- Data-loss guardrail: `last_sync` is recorded at pull run start, not run end, so mid-run updates are included by the next incremental pull.

## Loop Prevention

- bot-author gating for push-trigger workflows
- no-op commit avoidance when rendered content is unchanged
- isolated concurrency domains:
  - push + queue sweep: `linear-git-push`
  - webhook debounce: `linear-git-webhook`
  - scheduled pull: `linear-git-sync-pull`

## Conflict Model

- Git handles merge conflicts.
- Resolved markdown is pushed back on next sync cycle.
