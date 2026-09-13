# Incremental reconciliation acceptance

- [x] Hourly scheduler makes no Linear requests; idle inbox dispatches nothing.
- [x] Real D1 imports share capture, skip webhook-observed versions, preserve newer generations.
- [x] Filtered HTTP-boundary discovery covers all six sources and separate child timestamps.
- [x] Failed pages/uploads never advance the daily checkpoint; retries remain safe.
- [x] Matrix covers metadata validation, 25-record batches and checkpoint fencing.
- [x] Empty daily workflow skips mirror materialization/replay; preserves readiness gate.
- [x] Full Python/Worker tests, formatting, lint and types on candidate revision.
- [ ] Real Linear query smoke and staging D1 import/replay; record results outside Git.
- [ ] Hosted CI runs exact pinned revision. Production activation reported separately.

Invariants: durable capture before discovery checkpoint; publication before ACK;
zero per-webhook/idle-hour Actions runs; no deletion inferred from incremental absence.
