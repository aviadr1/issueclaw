CREATE TABLE events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  digest TEXT NOT NULL UNIQUE,
  work_key TEXT NOT NULL,
  payload TEXT NOT NULL,
  received_at INTEGER NOT NULL
);
CREATE INDEX events_work_seq ON events(work_key, seq);
CREATE INDEX events_retention ON events(received_at) WHERE payload != '';
CREATE TABLE work (
  key TEXT PRIMARY KEY,
  generation INTEGER NOT NULL,
  acked_generation INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL,
  source_time INTEGER NOT NULL,
  first_pending_at INTEGER,
  token TEXT,
  lease_until INTEGER NOT NULL DEFAULT 0,
  lease_generation INTEGER,
  lease_payload TEXT,
  retry_at INTEGER NOT NULL DEFAULT 0,
  failures INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX work_due ON work(retry_at, lease_until, first_pending_at);
CREATE TABLE consumer (id INTEGER PRIMARY KEY CHECK (id = 1), next_wakeup_at INTEGER NOT NULL DEFAULT 0, next_census_at INTEGER NOT NULL DEFAULT 0, census_at INTEGER NOT NULL DEFAULT 0, census_error TEXT);
INSERT INTO consumer (id) VALUES (1);
CREATE TABLE census (kind TEXT NOT NULL, id TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, missing_since INTEGER, PRIMARY KEY(kind,id));
