-- 실제 주문의 로컬 원장. 원격 DB 장애와 무관하게 승인·주문 재시도 상태를 복원한다.

CREATE TABLE IF NOT EXISTS execution_control (
  control_key TEXT PRIMARY KEY,
  control_value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_records (
  record_type TEXT NOT NULL,
  record_key TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (record_type, record_key)
);
CREATE INDEX IF NOT EXISTS runtime_records_type_updated_idx
  ON runtime_records (record_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS intents (
  intent_id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL,
  risk_decision_id TEXT NOT NULL UNIQUE,
  execution_mode TEXT NOT NULL CHECK (execution_mode IN ('paper', 'live')),
  status TEXT NOT NULL CHECK (status IN ('approved', 'claimed', 'executing', 'completed', 'failed', 'expired', 'cancelled')),
  not_before TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS intents_pending_idx ON intents (status, not_before, expires_at);

CREATE TABLE IF NOT EXISTS approvals (
  approval_id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL UNIQUE REFERENCES intents(intent_id) ON DELETE RESTRICT,
  status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'consumed')),
  manifest_hash TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS approvals_status_expiry_idx ON approvals (status, expires_at);

CREATE TABLE IF NOT EXISTS order_manifests (
  manifest_hash TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL UNIQUE REFERENCES intents(intent_id) ON DELETE RESTRICT,
  account_seq INTEGER NOT NULL CHECK (account_seq > 0),
  payload_json TEXT NOT NULL,
  captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_attempts (
  attempt_id TEXT PRIMARY KEY,
  client_order_id TEXT NOT NULL UNIQUE,
  intent_id TEXT NOT NULL REFERENCES intents(intent_id) ON DELETE RESTRICT,
  approval_id TEXT NOT NULL REFERENCES approvals(approval_id) ON DELETE RESTRICT,
  state TEXT NOT NULL CHECK (state IN ('reserved', 'submitted', 'unknown', 'failed')),
  payload_json TEXT NOT NULL,
  reserved_at TEXT NOT NULL,
  raw_artifact_path TEXT,
  raw_artifact_sha256 TEXT
);

CREATE TABLE IF NOT EXISTS order_events (
  event_id INTEGER PRIMARY KEY,
  attempt_id TEXT NOT NULL REFERENCES order_attempts(attempt_id) ON DELETE RESTRICT,
  occurred_at TEXT NOT NULL,
  event_type TEXT NOT NULL,
  detail_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS order_events_attempt_idx ON order_events (attempt_id, occurred_at, event_id);

CREATE TABLE IF NOT EXISTS orders (
  client_order_id TEXT PRIMARY KEY,
  broker_order_id TEXT UNIQUE,
  intent_id TEXT NOT NULL REFERENCES intents(intent_id) ON DELETE RESTRICT,
  status TEXT NOT NULL,
  account_seq INTEGER NOT NULL CHECK (account_seq > 0),
  submitted_at TEXT,
  updated_at TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_reconciliation_idx ON orders (account_seq, status, updated_at);

CREATE TABLE IF NOT EXISTS fills (
  fill_id TEXT PRIMARY KEY,
  broker_order_id TEXT NOT NULL,
  filled_at TEXT NOT NULL,
  quantity REAL NOT NULL CHECK (quantity > 0),
  price REAL NOT NULL CHECK (price > 0),
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconciliation_runs (
  reconciliation_id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('running', 'ok', 'mismatch', 'failed')),
  raw_artifact_path TEXT,
  raw_artifact_sha256 TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}'
);
