# Durable hourly Linear inbox

Today, dispatching CI for each ticket edit creates many short jobs and makes queue loss a correctness risk. This implementation records edits durably and refreshes dirty entities in hourly batches, so repeated edits do not each start a billable runner.

Readiness: implementation for review, not deployed. Requires one new staging D1 database, a separately named staging Worker, credentials, an opt-in caller, visibility/capacity tests and an alert owner before production. No live resource, permission or webhook has been changed. Do not deploy the placeholder configuration over the existing endpoint.

The whole change (terms defined below):

```text
Linear webhook -> signed capture -> D1 evidence + dirty entity
Linear API ----> hourly census ---> D1 evidence + dirty entity
                                          |
                        hourly check: any due work?
                            no: stop      | yes
                                     one CI wakeup
                                          |
                         claim generations -> fetch current state
                                          |
                           Git commit + push files and receipts
                                          |
                              ACK only published generations
```

## 1. Why

Ingress never calls GitHub. Rapid issue edits and issue-comment create/edit/delete events converge on one parent-issue key. Raw event evidence and retry digests remain separate from refresh work. Scheduled GitHub jobs are not used to check whether work exists.

This synchronizes current state, not every intermediate ticket revision. It is not a replacement for the weekly report evidence collector.

## 2. Glossary

| Term | Plain meaning | Role | Status |
| --- | --- | --- | --- |
| Worker | Cloudflare-hosted request handler | Authenticate and persist webhooks; hourly reconciliation | Modified code, separate staging deployment required |
| D1 | Cloudflare SQL database | Evidence, dirty keys, leases, scan metadata | New, not provisioned |
| Cron Trigger | Cloudflare hourly timer | Scan and dispatch only when work is due | New configuration |
| Generation | Durable per-entity sequence | Distinguish edits arriving during processing | New |
| Lease | Temporary claim on a generation | Prevent concurrent processing of the same key | New, ten minutes |
| Receipt | Generation recorded in remote Git | Prove files were published before ACK | New |
| Repository dispatch | GitHub API event | Wake one reusable consumer workflow | Modified event name |
| Bearer secret | Independent replay credential | Restrict claim, ACK and status endpoints | New |
| Opt-in caller | Company-owned workflow | Pin runtime and share the existing writer lock | Requires coordinated rollout |

## 3. Correctness and ownership

`store.js` owns identity, compaction, lease and ACK transitions. There is no second Python coalescer or global cursor. Evidence and dirty generation are one transaction. A later delivery with an older source timestamp cannot replace newer entity state.

The consumer reuses the existing parser/rendering path in a small temporary workspace per entity. Failed preparation cannot leak partial writes into another entity's publication. Disk, commit or push failure aborts publication without ACK. A failed entity gets a failed outcome and hourly backoff; healthy entities can publish. An accepted push with a lost ACK is recovered by reading receipts from remote `main` on the next clean runner.

```text
claim generation 7 -> edit advances key to 8 -> publish receipt 7 -> ACK 7
                                                    key 8 stays pending
```

The hourly census paginates issues, issue comments, projects, documents and initiatives with archived records included. All provider pages must succeed before absence is considered. New/changed metadata queues refreshes; unchanged records are not rewritten. Two missing observations at least an hour apart are required for a synthetic deletion. Duplicate cron invocations do not count twice. A visibility drop of at least ten records and more than 20% stops reconciliation for review. Evidence and each metadata transition commit together in bounded D1 batches.

## 4. Changes, cost and rollback

| Environment | Added / modified / destroyed | Roles changed | Plan |
| --- | --- | --- | --- |
| Local tests | Ephemeral D1 and Git test repositories | None | Tests only |
| Staging proposal | One D1 database; one separately named Worker with hourly trigger | None provisioned | No provisioning plan run |
| Production | Nothing applied | None | Blocked on staging approval/results |

| Object | Enables | Restricts |
| --- | --- | --- |
| Ingress | Durable receipt before HTTP 200 | HMAC, organization/type validation, 512 KiB body limit; no CI dispatch |
| D1 work row | Independent retry of each entity | Token/generation fenced ACK; old ACK cannot clear a new edit |
| Timer | Work-only wakeups | One reservation per UTC hour slot; idle hours launch no runner |
| Consumer | Current-state rendering and Git receipts | Five-minute job timeout, 100 keys per claim, at most ten claims per invocation |
| Retention | Reduce old body storage | Strip only ACKed bodies older than 30 days; never pending evidence |

Permissions: the Worker needs read access to the complete mirrored Linear organization, D1 binding access and a GitHub credential scoped to repository dispatch on the mirror repository. GitHub documents repository dispatch as requiring repository Contents write for a fine-grained token; validate that exact repository scope during provisioning. The consumer needs Linear read, its independent inbox bearer token, and `GITHUB_TOKEN` Contents write for the mirror. No Linear write is added. Existing push-to-Linear credentials, other repositories and AWS roles are unaffected. Broad legacy PAT permissions are not silently revoked by this code.

Estimated cost, not a measured bill:

| Item | Unit / volume | Monthly estimate |
| --- | --- | --- |
| CI ingress / idle check | Zero jobs | Zero Actions minutes |
| Busy hourly consumer | At most 24 scheduled starts/day, five-minute timeout | Up to 3,600 runner minutes per 30 days, excluding manual reruns/other workflows |
| Linux two-core list price | $0.006/minute before included allowances | Up to $21.60 for that ceiling; actual short batches lower |
| Worker paid plan | $5 base if a new paid plan is required | Account/usage dependent; not provisioned |
| D1 | Reads, writes, storage including indexes | Measure staging; no credible total without organization size |
| Compact digests and Git receipts | Retained, not TTL-deleted | Grow with history; monitor storage |

Sources: [GitHub runner pricing](https://docs.github.com/en/billing/reference/actions-runner-pricing), [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/), [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/). GitHub rounds billable jobs to whole minutes. Cancellation is not a dependable cost optimization. At 10x/100x edits of one issue, evidence writes increase but it still has one dirty key; at 10x/100x distinct entities, throughput and scan limits must be remeasured.

Setup, only after separate provisioning approval:

1. Create a dedicated staging database and separately named Worker; replace database ID, organization ID and a fresh database-incarnation stream UUID in `wrangler.toml`. Never share the production stream UUID with a new database.
2. Apply `migrations/0001_inbox.sql` to staging, set `LINEAR_WEBHOOK_SECRET`, `LINEAR_API_KEY`, `GITHUB_TOKEN`, `GITHUB_REPO` and independent random `INBOX_TOKEN`. Store replay URL/token in the caller repository secrets. Do not print secrets.
3. Install an explicitly pinned `inbox.yml` caller for `linear-inbox-ready`, with the same `linear-git-sync` concurrency group as every other writer. Do not enable an Actions cron. The legacy `issueclaw init` webhook template is not this caller.
4. Validate a complete initial metadata census against an audited mirror baseline. Previously lost deletions before that baseline are not magically discoverable from this new database.
5. Run staging acceptance below. Only then coordinate switching the Linear endpoint and retiring the old `linear-webhook` caller. Do not leave both dispatch paths active.

Rollback: disable the new timer/caller and switch ingress back deliberately. Keep D1 and Git receipts for replay; reverting code does not delete either. Destroying D1 loses pending work and its evidence. Restoring a database to an older sequence or replacing it requires a new stream UUID and explicit baseline/receipt reconciliation, never blindly reusing the old identity.

Blast radius: incorrect cutover can stop mirror updates or reintroduce duplicate CI cost. It does not modify Linear tickets. Mis-scoped read credentials can misclassify small visibility losses as deletions; the two-observation guard is not proof against permission changes.

## 5. Reviewer walkthrough

- `auth.js`, `worker.js`: authentication, durable HTTP 200 and the only GitHub dispatch call in the scheduled handler.
- `store.js`, migration: atomic generations, oldest-pending age, leases, per-key ACK, hourly reservation and retention.
- `census.js`: full pagination before comparison, separate issue-comment fingerprints, absence interval, mass-drop guard and batched writes.
- `inbox_contract.py`: typed wire identities; shared fixture verified against the actual Worker response.
- `entity_changes.py`: reuse the existing production renderer in an isolated entity workspace; reject escaping paths and foreign ownership.
- `inbox_replay.py`: require clean remote-aligned Git, prepare independent outcomes, commit receipts, push, then ACK. Entity preparation times out; a bounded preparation budget preserves time to publish.
- `.github/workflows/inbox.yml`: opt-in pinned reusable consumer and five-minute timeout. Existing reusable webhook workflow is unchanged for legacy callers.
- Worker tests and CI job: actual Miniflare/workerd/D1; Python replay tests use real local and bare remote Git repositories.

## 6. Verification and staging gate

Local commands:

Latest local verification: 218 Python and 22 Worker tests passed; Ruff formatting/lint and basedpyright passed; packaged CLI help ran successfully. Worker tests use real D1 and cover storms, race/ACK recovery, wire compatibility, census and retention. The dependency audit reported zero Worker dependency vulnerabilities. No live-provider or deployment test is claimed.

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
cd workers/issueclaw-webhook-proxy
npm ci --ignore-scripts
npm test
npm audit
```

Before production, Aviad or an explicitly designated rollout owner must run these checks in staging and attach evidence to the PR:

- Send 200 signed edits/comments for one issue: 200 durable HTTP responses, one dirty parent, zero per-event Actions starts. Trigger one scheduled scan: one consumer run, final file matches current Linear.
- Suppress a test webhook, then update/delete a test entity and remove a test comment. Compare the rendered file after hourly scans; record actual maximum staleness.
- Interrupt before push, reject a push, lose the ACK response, and edit during the lease. Verify remote receipts and pending generations with authenticated `POST /inbox/status`; no edit may disappear.
- Verify an idle scheduled scan causes no Actions run. Measure actual Actions billable minutes, Linear API requests, Worker duration/subrequests and D1 rows read/written at observed peak plus a 10x replay.
- Configure and demonstrate an alert outside Actions for `freshness_breached`, `census_stale`, non-null `census_error`, dispatch failures and database limits. Alert routing is not provisioned by this PR.

## 7. Limits

Production blockers: provisioning approval, complete visibility/baseline audit, alert routing and capacity/cost acceptance. No hard correctness deadline is possible during indefinite provider/credential outages or a sustained backlog beyond processing capacity.

Operating targets to validate: captured changes and missed creates/updates within two hours; missed deletions within four hours, allowing two separated scans and cron jitter. The status endpoint reports oldest pending age separately from scan health; constant edits do not reset that age. These are staging targets, not measured production guarantees.

Caveats: provider pagination is not a transaction; small visibility changes remain ambiguous. Only issue-parent comments are supported. A metadata census only sees changes reflected in the provider's timestamps (comments are scanned separately). Initial census, large organizations, payloads exceeding 512 KiB and long-running entities require explicit capacity review. One failed wakeup is retried in the next hourly slot; there is no immediate CI retry storm.

Related: [complete-snapshot prerequisite #27](https://github.com/aviadr1/issueclaw/pull/27), [workflow safety #26](https://github.com/aviadr1/issueclaw/pull/26), [company caller #34](https://github.com/gigaverse-app/linear-git/pull/34). This implementation is stacked on #27; merge that prerequisite first and retarget this PR to main before merging.
