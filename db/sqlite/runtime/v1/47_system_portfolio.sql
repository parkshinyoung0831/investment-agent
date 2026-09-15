-- System Portfolio: 프로그램 판단을 100% 따랐다면의 목표비중과 비중 기반 NAV.
-- 실계좌 원장(account_snapshots·intents·orders·fills)과 승인 표를 참조하지 않는다. Discord 승인·거절은
-- 이 표들에 어떤 흔적도 남기지 않는다 — 시스템 자신의 판단 성과를 사람의 선택과 분리해 잰다.

-- 목표 한 건. RiskGate가 거절한 목표도 사유와 함께 남긴다(같은 횡단면으로 다시 판단하지 않게).
CREATE TABLE IF NOT EXISTS system_targets (
 target_id TEXT PRIMARY KEY,
 decided_at TEXT NOT NULL,
 factor_snapshot_as_of TEXT NOT NULL,
 proposal_id TEXT NOT NULL,
 risk_decision_id TEXT NOT NULL,
 model_artifact_id TEXT NOT NULL,
 is_approved INTEGER NOT NULL CHECK (is_approved IN (0,1)),
 -- 승인된 목표비중(CASH 포함). 거절이면 빈 객체다.
 weights_json TEXT NOT NULL,
 -- 이 목표가 NAV에 반영된 거래일. 판단 다음 정규장 종가에 적용되기 전까지 비어 있다.
 applied_session TEXT,
 detail_json TEXT NOT NULL,
 CHECK ((is_approved = 1) OR (applied_session IS NULL))
);
CREATE INDEX IF NOT EXISTS system_targets_decided_idx ON system_targets (decided_at);

-- 거래일마다 확정 종가로 잰 System 상태. 비중은 그날 재조정까지 반영한 값이고, 종가는 다음 날
-- 수익률의 기준이다(가격 이력이 분할 뒤 다시 수집돼도 수익률이 두 번 보정되지 않게).
CREATE TABLE IF NOT EXISTS system_nav (
 trade_date TEXT PRIMARY KEY,
 nav REAL NOT NULL CHECK (nav > 0),
 daily_return REAL NOT NULL,
 benchmark_nav REAL NOT NULL CHECK (benchmark_nav > 0),
 benchmark_close REAL NOT NULL CHECK (benchmark_close > 0),
 turnover REAL NOT NULL CHECK (turnover >= 0),
 cost REAL NOT NULL CHECK (cost >= 0),
 weights_json TEXT NOT NULL,
 closes_json TEXT NOT NULL,
 applied_target_id TEXT REFERENCES system_targets(target_id),
 -- 그날 종가가 없어 전날 종가로 잰 종목(거래정지 등). 신선한 평가처럼 보이지 않게 남긴다.
 stale_price_tickers_json TEXT NOT NULL DEFAULT '[]'
);
