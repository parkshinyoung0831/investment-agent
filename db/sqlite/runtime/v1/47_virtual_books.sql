-- Shadow·Paper 가상계좌. 실계좌 원장(account_snapshots·intents·orders·fills)과 표를 나눈다.
-- 가상 잔고가 실계좌 원장에 섞이면 실주문 게이트가 가짜 현금을 읽는다. Discord 승인·거절은
-- 이 표들에 어떤 흔적도 남기지 않는다 — 시스템 자신의 판단 성과를 사람의 선택과 분리해 잰다.
CREATE TABLE IF NOT EXISTS virtual_books (
 book_id TEXT PRIMARY KEY,
 stage TEXT NOT NULL CHECK (stage IN ('shadow','paper')),
 policy_kind TEXT NOT NULL CHECK (policy_kind IN ('optimizer','rl_policy')),
 initial_nav REAL NOT NULL CHECK (initial_nav > 0),
 cash REAL NOT NULL CHECK (cash >= 0),
 created_at TEXT NOT NULL,
 last_batch_id TEXT,
 last_decided_at TEXT,
 config_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS virtual_positions (
 book_id TEXT NOT NULL REFERENCES virtual_books(book_id),
 ticker TEXT NOT NULL,
 quantity REAL NOT NULL CHECK (quantity > 0),
 cost_basis REAL NOT NULL CHECK (cost_basis >= 0),
 PRIMARY KEY (book_id, ticker)
);
-- 가상계좌 하나가 신호 배치 하나를 보고 내린 판단. 승인되지 않은 판단도 사유와 함께 남는다.
CREATE TABLE IF NOT EXISTS virtual_decisions (
 decision_id TEXT PRIMARY KEY,
 book_id TEXT NOT NULL REFERENCES virtual_books(book_id),
 batch_id TEXT NOT NULL,
 decided_at TEXT NOT NULL,
 proposal_id TEXT,
 risk_decision_id TEXT,
 is_approved INTEGER NOT NULL CHECK (is_approved IN (0,1)),
 nav REAL NOT NULL,
 target_weights_json TEXT NOT NULL,
 detail_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS virtual_orders (
 order_id TEXT PRIMARY KEY,
 book_id TEXT NOT NULL REFERENCES virtual_books(book_id),
 decision_id TEXT NOT NULL REFERENCES virtual_decisions(decision_id),
 ticker TEXT NOT NULL,
 side TEXT NOT NULL CHECK (side IN ('buy','sell')),
 requested_quantity REAL NOT NULL CHECK (requested_quantity > 0),
 filled_quantity REAL NOT NULL DEFAULT 0 CHECK (filled_quantity >= 0),
 status TEXT NOT NULL CHECK (status IN ('pending','filled','partially_filled','cancelled')),
 reason_code TEXT NOT NULL,
 created_at TEXT NOT NULL,
 closed_at TEXT,
 close_reason TEXT
);
CREATE INDEX IF NOT EXISTS virtual_orders_pending_idx ON virtual_orders (book_id, status);
CREATE TABLE IF NOT EXISTS virtual_fills (
 fill_id TEXT PRIMARY KEY,
 order_id TEXT NOT NULL REFERENCES virtual_orders(order_id),
 book_id TEXT NOT NULL REFERENCES virtual_books(book_id),
 ticker TEXT NOT NULL,
 side TEXT NOT NULL CHECK (side IN ('buy','sell')),
 trade_date TEXT NOT NULL,
 quantity REAL NOT NULL CHECK (quantity > 0),
 reference_price REAL NOT NULL CHECK (reference_price > 0),
 fill_price REAL NOT NULL CHECK (fill_price > 0),
 spread_cost REAL NOT NULL CHECK (spread_cost >= 0),
 impact_cost REAL NOT NULL CHECK (impact_cost >= 0),
 commission REAL NOT NULL CHECK (commission >= 0)
);
-- 거래일마다 확정 종가로 잰 가상계좌 가치. 낙폭·회전율·비용은 이 시계열에서 계산한다.
CREATE TABLE IF NOT EXISTS virtual_nav (
 book_id TEXT NOT NULL REFERENCES virtual_books(book_id),
 trade_date TEXT NOT NULL,
 nav REAL NOT NULL CHECK (nav >= 0),
 cash REAL NOT NULL CHECK (cash >= 0),
 gross_exposure REAL NOT NULL CHECK (gross_exposure >= 0),
 traded_notional REAL NOT NULL CHECK (traded_notional >= 0),
 cost REAL NOT NULL CHECK (cost >= 0),
 PRIMARY KEY (book_id, trade_date)
);
