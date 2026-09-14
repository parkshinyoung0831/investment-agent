-- 성과는 원천 체결을 바꾸지 않는 내용 기반 보고서와 근거 있는 보정 사건을 소유한다.
CREATE TABLE IF NOT EXISTS performance_reports (
  report_id TEXT PRIMARY KEY,
  broker_account_hash TEXT NOT NULL,
  execution_mode TEXT NOT NULL CHECK (execution_mode IN ('paper','live')),
  report_kind TEXT NOT NULL CHECK (report_kind IN ('daily','realized')),
  occurrence TEXT NOT NULL,
  as_of_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS performance_reports_latest ON performance_reports(as_of_at, report_kind);
CREATE TABLE IF NOT EXISTS performance_events (
  event_id TEXT PRIMARY KEY,
  broker_account_hash TEXT NOT NULL,
  execution_mode TEXT NOT NULL CHECK (execution_mode IN ('paper','live')),
  occurred_at TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
