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

## Loop Prevention

- bot-author gating for push-trigger workflows
- no-op commit avoidance when rendered content is unchanged
- shared concurrency group across push/sync/webhook stubs

## Conflict Model

- Git handles merge conflicts.
- Resolved markdown is pushed back on next sync cycle.
