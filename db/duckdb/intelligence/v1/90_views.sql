-- 화면이 90일 전체를 스캔하지 않도록 집계는 뷰가 미리 좁힌다.
-- observed_date는 발행 시각 축(화면 기본 동작), first_seen_date는 PIT 축이다 —
-- 이 규칙을 어기면 backtest가 미래를 본다. 화면은 계속 observed_date로 조회한다.
CREATE OR REPLACE VIEW ticker_mention_daily AS
SELECT
    ticker,
    source_kind,
    match_kind,
    CAST(observed_at AS DATE) AS observed_date,
    CAST(first_seen_at AS DATE) AS first_seen_date,
    count(*) AS mention_count
FROM entity_mentions
GROUP BY 1, 2, 3, 4, 5;

-- news_articles/social_posts view는 repository가 현재 Parquet file 목록으로 만든다.
-- 이 view는 작은 DuckDB metadata만 읽으므로 Parquet 전체를 세지 않는다.
-- 한 종류가 아직 비어 있어도 행은 나와야 한다. GROUP BY만 쓰면 그 종류가 통째로
-- 사라져 "수집이 멈췄다"와 "표에 없다"를 구분할 수 없다.
CREATE OR REPLACE VIEW intelligence_freshness AS
SELECT
    kinds.domain AS domain,
    count(c.content_id) AS row_count,
    min(c.observed_at) AS oldest_at,
    max(c.observed_at) AS newest_at,
    max(c.collected_at) AS last_collected_at
FROM (SELECT 'news' AS domain UNION ALL SELECT 'social') AS kinds
LEFT JOIN content_index c ON c.content_kind = kinds.domain
GROUP BY kinds.domain;
