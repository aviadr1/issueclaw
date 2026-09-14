# Hourly replay and daily incremental reconciliation

Webhooks persist signed events in D1 and coalesce dirty entity keys. The hourly
Cloudflare Worker checks D1 only: **empty inbox means no GitHub runner**.
Due work dispatches `linear-inbox-ready`. The Worker never queries Linear.

Daily CI runs `issueclaw-inbox-reconcile` then the existing replay consumer in
the same job, under the caller's shared writer lock.

## Fast path

Discovery checks organization identity and six independently filtered sources:
issues, issue comments, projects, documents, initiatives and project updates.
Queries fetch only identity, updatedAt and parent identity where needed. They
include archived records, order by updatedAt and use an inclusive fixed window
from the previous successful watermark minus five minutes to scan start.
Connections paginate at 100 records/page with a 1,000-page safety limit.

An unchanged window uses seven Linear requests, no full-content fetches, no
metadata imports and no replay. Checkout initially contains only .sync and root
files; mirrored content is materialized only when pending work exists.
Runner startup/install still costs time: daily scheduling means about 30 discovery
jobs/month even when idle. There is no hourly Actions cron or per-webhook dispatch.
No paid Cloudflare upgrade is required by this architecture; Worker/D1 quotas remain.

Cost scales with changed metadata/pages, not all historical content. First use
requires an explicit `--bootstrap-since` or the trusted mirror
`.sync/state.json:last_sync`; it never silently starts at now. A stale baseline
can require substantial one-time catch-up. If this cannot finish within the
five-minute CI job, run the same CLI in a controlled environment with sufficient
time and the same credentials. Repeated failed bootstraps are safe but not cheap.

## Durable ownership

`captureStatements` is the single transaction for webhook and metadata capture.
Webhooks record source versions when updatedAt is available. Metadata equal to or
older than a captured version queues no new work, including already processed
webhook edits. Missing webhook timestamps cause safe extra refreshes.

Within each metadata import, observations are grouped by mirrored owner: several
comments on one issue produce one event and one work-row update, while retaining
every individual source version. Any unseen member queues the owner, even if the
newest member was already observed. Event, work and all source versions commit
atomically; regrouped retries of known versions perform no row writes. Grouping
does not span requests, so savings depend on how many sources share an owner in
each batch. It does not eliminate the per-source cost of an initial bootstrap.

All six scans must succeed before imports. Imports are atomic batches of at most
25 records. Only after every import succeeds does the scanner compare-and-swap
the D1 watermark. Cursor advancement before replay is safe because D1 owns all
processing obligations. Failed scans/uploads and stale completions cannot erase
pending work. An idle daily run does not need a new Git commit.

Comments refresh their owning issue, project, initiative or document, resolving
direct, document-content and update relationships; project updates refresh their project. Children are
queried separately because their edits need not change parent timestamps.
Unresolved parent relationships still fail discovery rather than silently skip work.
This refreshes the existing owner representation; it does not introduce standalone
document-comment artifacts or change which fields the owner renderer includes.

Replay reuses existing isolated entity preparation/rendering. It requires clean,
remote-aligned Git and pushes files plus generation receipts before ACK.
Edits during a lease remain pending; lost ACK responses recover from remote
receipts. Failures retry independently. Limits remain 100 keys/claim,
ten-minute leases, bounded preparation and a five-minute CI job.

## Freshness and limits

Captured edits target hourly processing, with a two-hour pending-age warning.
Missed create/update webhooks recover on the next daily scan: roughly 24 hours
plus scheduling and processing delay, not the old two-hour target.
`reconciliation_stale` warns after 48 hours without successful daily discovery.
Provider outages, delayed GitHub schedules and overload prevent hard deadlines.

**Incremental absence never proves deletion.** Signed delete webhooks still work;
missed hard deletions and deleted comments are not guaranteed to be discovered.
Historical deletion recovery needs an explicitly scheduled visibility-audited
inventory comparison or a proven provider deletion feed. The old Worker census
and its deletion inference have been removed. Permission visibility must be audited.

## Deployment and rollback

Company account names, ownership, secrets and deployment inventory belong in the
private consumer repository, not this public runtime.

1. Apply all SQL migrations in filename order, including 0002_incremental.sql.
   Existing events, work generations and legacy census tables remain intact.
2. Deploy the tested runtime with D1, organization and database-incarnation stream
   bindings, signing/inbox secrets and scoped GitHub dispatch credentials.
   Linear read credentials belong in CI, not the hourly Worker.
3. Pin reusable workflow and runtime to the same commit. The caller handles
   linear-inbox-ready and one daily schedule, passes reconcile=true for discovery,
   and shares linear-git-sync concurrency with every other writer.
4. Verify bootstrap, live staging and hosted publication before production cron.
   Never deploy placeholder identifiers over production.

Rollback must coordinate producer and consumer: legacy linear-webhook dispatch
does not match the durable caller. Preserve D1 and Git receipts. Git revert does
not restore deleted infrastructure. A new database needs a new stream and an
explicit baseline; configuration alone cannot recover pending events.

## Verification

Run `uv run pytest -q`, `uv run ruff check .`,
`uv run ruff format --check .`, `uv run basedpyright`, and `npm test`
in workers/issueclaw-webhook-proxy. Tests exercise production discovery through
external HTTP transports, real Miniflare/D1 migrations and real local/bare Git.

Before activation, exercise live Linear queries and deployed D1 imports, rapid
edits, edit-during-claim, lost ACK, daily retry and idle no-dispatch behavior.
Measure hosted runner duration separately from local API latency. Keep run
evidence in PR comments or CI artifacts, not committed date-stamped result files.
