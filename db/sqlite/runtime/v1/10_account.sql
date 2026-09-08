-- 브로커에서 관측한 계좌 상태. 원본 응답은 artifact에 두고 위치와 hash만 보존한다.
-- 같은 날 여러 번 잡아도 (broker_account_hash, execution_mode, snapshot_date) 하나로
-- 압축한다 — paper/live가 같은 날짜에 덮어쓰지 않도록 execution_mode를 키에 넣는다.
-- 상세 이력은 runtime_records가 2일만 짧게 들고 있는다.
CREATE TABLE IF NOT EXISTS account_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  broker_account_hash TEXT NOT NULL,
  execution_mode TEXT NOT NULL CHECK (execution_mode IN ('paper', 'live')),
  snapshot_date TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  cash REAL NOT NULL,
  market_value REAL NOT NULL,
  equity REAL NOT NULL,
  buying_power REAL,
  source_artifact_path TEXT,
  source_artifact_sha256 TEXT,
  UNIQUE (broker_account_hash, execution_mode, snapshot_date)
);
