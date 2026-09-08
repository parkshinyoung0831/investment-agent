PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS local_job_state (
  job_name TEXT PRIMARY KEY,
  last_started_at TEXT,
  last_finished_at TEXT,
  last_status TEXT NOT NULL CHECK (last_status IN ('ok', 'failed', 'running')),
  detail TEXT
);
