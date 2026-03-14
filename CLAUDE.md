# issueclaw

Bidirectional sync between Linear and Git. Issues, projects, initiatives, and documents live as `.md` files in a git repo.

## Project structure

```
src/issueclaw/
  main.py              # Click CLI entry point
  models.py            # Pydantic models for all Linear entity types
  render.py            # Entity → markdown renderer
  parse.py             # Markdown → parsed entity parser
  diff.py              # Field-level markdown diffing
  paths.py             # File path conventions and slugification
  linear_client.py     # Async GraphQL client (fetch + mutations)
  sync_state.py        # .sync/id-map.json and state.json management
  image_sync.py        # URL rewriting for Linear image uploads
  commands/
    init.py            # Repo setup: workflows, secrets, webhook, initial pull
    pull.py            # Full pull sync from Linear
    apply_webhook.py   # Webhook-driven single entity sync
    push.py            # Push local changes to Linear via git diff
    status.py          # Sync state summary
    diff_cmd.py        # Preview changes that would be pushed
  workflows/           # Bundled GitHub Actions YAML templates
```

## Dev commands

```bash
uv run pytest                           # Run all tests (parallel by default)
uv run pytest tests/test_render.py -v   # Run specific test file
uv run pytest --cov=src --cov-report=term-missing  # With coverage
uv run ruff check src tests             # Lint
uv run ruff format src tests            # Format
uv run pyright                          # Type check
```

## Key patterns

- **Click CLI**: All commands are Click commands registered in `main.py`
- **Pydantic models**: All Linear entities are typed models in `models.py`. Always use model instances for test data, never naked dicts.
- **Async httpx**: `LinearClient` uses `httpx.AsyncClient` with connection pooling. GraphQL complexity limit is 10000 (projects need page size 5).
- **Round-trip safety**: Renderer adds `# AI-123: Title` heading. Parser strips it before pushing to avoid duplication.
- **Field resolution**: Status → stateId and assignee → assigneeId are resolved via lazy-cached API lookups in `linear_client.py`.
- **Project updates as separate files**: Status updates live in `linear/projects/{slug}/updates/{date-author}.md`, not inline in the project file. The project file lists references. New update files pushed to git are synced to Linear via `create_project_update`.
- **New issue queue**: Files in `linear/new/{TEAM}/{slug}.md` are created as new Linear issues by `issueclaw push`. The queue is always fully drained (scanned from disk, not just from git diff) so retries work if CI fails mid-run. After creation, the file is moved to `linear/teams/{TEAM}/issues/{ID}-{slug}.md` and the queue file is deleted.
- **Direct entity creation via CLI**: `issueclaw create issue/project/initiative/document/comment` calls the Linear API directly, writes canonical files, and updates id-map — no git push needed. Comments re-fetch and re-render the issue file immediately.
- **DRY section parsing**: Comments and project updates share generic `_parse_sections()` and `_render_sections()` infrastructure in parse.py and render.py.

## Testing conventions

- 151 tests, all passing
- Use `patch.object`, never `patch` with string paths
- Never mock Pydantic models — create real instances
- Tests use Click's `CliRunner` for command testing
- Check `tests/conftest.py` for shared fixtures before creating new ones

## Linear API notes

- Rate limits return HTTP 400 with "RATELIMITED" in body (not 429)
- Webhook payloads use IDs for relationships (stateId, teamId), not nested objects — must re-fetch full entity
- `content` field is richer than `description` for projects/initiatives
