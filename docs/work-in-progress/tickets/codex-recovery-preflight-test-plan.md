# Recovery preflight checks

- [x] Remote D1 migration compatibility: read-only SELECT reproduces error 7500 with semicolon-bearing block comment; punctuation-only correction succeeds. Checked-in migration guard fails before correction, passes after.
- [x] Staging migration and deployed ProjectUpdate flow: actual Worker/D1/Linear, disposable Git publication, deferral/resume, duplicate delivery, empty final inbox. No Linear mutations.
- [x] Existing identity matrix: divergent aliases are rejected before source fetching; identical aliases and authoritative removal remain supported. Uses real preparation and SyncState, only Linear boundary mocked.
- [x] Preview integration: real renderer produces changes or no-op, leaves input mirror unchanged, bounds selected owners, classifies conflicts before network I/O. No queue client is present.
- [x] Preview failure matrix: source timeout and error produce safe categories without content disclosure.
- [x] Real production read-only sample: source snapshots and current mirror, no claims/ACK/publication; sample results are not a guarantee for all pending owners.
- [x] Explicit approved recovery: real Git backup branch, source success/failure and changed-since-backup matrix, full/shallow checkouts. Original bytes restored before returning edits; unpreserved bytes rejected before source fetching.
- [x] First three real conflicting identities prepared successfully in a separate recovery checkout, with originals preserved on a verified GitHub branch; no production publication or ACK.
- [ ] Final revision CI and staging pin verification.
- [ ] Production deployment/drain: deliberately gated on preparation and historical conflict resolution; not part of a dry run.
