-- 진입 조건과 재판단 이력. 원본 종목 판단은 수정하지 않는다.
CREATE TABLE IF NOT EXISTS entry_candidates (
 signal_id TEXT PRIMARY KEY,
 ticker TEXT NOT NULL,
 status TEXT NOT NULL,
 next_check_at TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entry_reviews (
 review_id TEXT PRIMARY KEY,
 signal_id TEXT NOT NULL,
 reviewed_at TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
