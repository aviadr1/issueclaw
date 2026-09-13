# Report evidence red-team loop

Invariant: moving latest PR metadata beyond the cutoff must not erase retained in-window discussion. Enforced by unbounded updated-candidate discovery and event enrichment before classification. Metadata is explicitly a current snapshot; `activity` does not assert historical open/closed state.

- [x] `test_activity_window_is_independent_of_latest_metadata` — real collector through JSON files; GitHub transport only replaced; three discussion channels, four cutoff positions, same-day and later-day updates.
- [x] `test_comment_edits_preserve_activity_without_backdating_text` — older comments edited in-window and in-window comments edited later, across discussion/inline channels. Post-cutoff bodies withheld.
- [x] `test_event_endpoint_failure_never_claims_complete` — failure on each discussion endpoint fails the source manifest.
- [x] Existing merge, linked CI work, identity, query saturation, access failure tests remain green.

Red: 31 failures / 7 passes before implementation. Green: 38 collector tests. Limitations: deleted events and historical mutable text cannot be reconstructed; no complete historical push/state event log. Live validation must be read-only and is not a claim of deployed report quality.
