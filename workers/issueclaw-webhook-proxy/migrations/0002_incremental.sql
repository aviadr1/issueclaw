CREATE TABLE source_versions (
  kind TEXT NOT NULL,
  id TEXT NOT NULL,
  parent_key TEXT NOT NULL,
  source_time INTEGER NOT NULL,
  PRIMARY KEY(kind,id)
);
ALTER TABLE consumer ADD COLUMN reconciliation_at INTEGER NOT NULL DEFAULT 0;
