/* Capture uses the unique digest index. Retention uses events_retention.
   No runtime query uses (work_key, seq). Remove its per-event write cost
   without deleting event records or changing monotonic generation IDs. */
DROP INDEX IF EXISTS events_work_seq;
