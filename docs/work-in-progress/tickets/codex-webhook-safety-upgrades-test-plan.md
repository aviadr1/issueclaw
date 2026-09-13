# Webhook safety loop

- [x] CLI upgrade → real caller files: parameterize schedule, concurrency and pinned dependency customizations; refusal leaves all files byte-for-byte unchanged, with no partial installation.
- [x] Explicit force → bundled files: destructive replacement is opt-in.
- [x] Parsed template matrix across webhook, sync, push and queue sweep: one non-canceling writer group. This is a workflow contract test, not a scheduler simulation or proof of durable delivery.
- [x] Document routing and no per-event sleep; preserve existing queue-sweep guard test.

Red: 10 failing cases, 4 passing before implementation. Old tests affirming cancellation/isolated writer locks were replaced, not kept as contradictory requirements.

Remaining blocker for lossless delivery: ingress acknowledges repository_dispatch without durable storage, and GitHub only queues 100 pending runs. Provisioning persistent ingress plus acknowledgement-after-processing/replay needs a separate design and deployment. Incremental polling alone cannot repair missed deletes. No schedule is re-enabled in the caller by this change.
