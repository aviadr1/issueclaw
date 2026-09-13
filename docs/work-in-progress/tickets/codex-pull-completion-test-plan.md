# Pull completion cursor

Invariant: the global last_sync value certifies completion of all teams and entity phases. Partial mapping persistence is not completion evidence.

- [x] Existing materialization smoke remains green.
- [x] Fail at second team, projects, initiatives, documents: keep old cursor, retry from old external-query window, materialize final document, advance only on successful unfiltered retry. Four cases failed before correction.
- [x] Team-filtered run retains global cursor: failed before correction.
- [ ] Full suite, lint/types, hosted CI on the candidate commit.
- [ ] Live fault/recovery test after authorized rollout. No production outage injected; this finding is locally reproduced, not a claim of an observed live missed update.

Reuse existing entity payload factories and production _run_pull; substitute only the external Linear client. Keep this fix independent from identity alias and CI readiness changes.
