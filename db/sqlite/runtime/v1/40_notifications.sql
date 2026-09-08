-- 알림 전송 상태와 outbox는 실행 컴퓨터의 단일 원장에 둔다.
CREATE TABLE IF NOT EXISTS notification_delivery_state (
  producer TEXT NOT NULL,
  notification_key TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('claimed', 'sent', 'failed')),
  claimed_at TEXT NOT NULL,
  sent_at TEXT,
  error_message TEXT,
  PRIMARY KEY (producer, notification_key)
);

CREATE TABLE IF NOT EXISTS notification_outbox (
  producer TEXT NOT NULL,
  notification_key TEXT NOT NULL,
  kind TEXT NOT NULL,
  entity_key TEXT,
  period_end TEXT,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed', 'abandoned')),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  claimed_at TEXT NOT NULL,
  resolved_at TEXT,
  PRIMARY KEY (producer, notification_key)
);

CREATE TABLE IF NOT EXISTS notification_deliveries (
  delivery_id INTEGER PRIMARY KEY,
  producer TEXT NOT NULL,
  notification_key TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('sent', 'failed')),
  failure_reason TEXT,
  attempted_at TEXT NOT NULL,
  FOREIGN KEY (producer, notification_key)
    REFERENCES notification_outbox(producer, notification_key) ON DELETE RESTRICT
);
