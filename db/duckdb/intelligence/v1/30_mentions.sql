-- match_kind가 "이 종목이 화제다"와 "이 종목을 내가 조회했다"를 가른다.
-- 이것이 없으면 두 성격이 섞여 언급량 집계가 거짓이 된다.
-- observed_at은 발행 시각 축(retention 키)이고, first_seen_at은 PIT 축이다.
-- PIT 집계는 항상 COALESCE(available_at, first_seen_at)를 써야 하므로, 부모
-- 레코드의 first_seen_at을 그대로 들고 있지 않으면 이 표만으로는 PIT-safe 집계를
-- 만들 수 없다.
CREATE TABLE IF NOT EXISTS entity_mentions (
    mention_id VARCHAR PRIMARY KEY,
    source_kind VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    ticker VARCHAR NOT NULL,
    match_kind VARCHAR NOT NULL,
    confidence DOUBLE NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    UNIQUE (source_kind, source_id, ticker, match_kind)
);
