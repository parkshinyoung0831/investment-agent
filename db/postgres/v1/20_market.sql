-- market — 거래일 단위 시세와 corporate action.
--
-- 이 스키마는 **관측한 것만** 담는다. 조정가(adj_close)·수익률·이동평균처럼 계산으로
-- 나오는 값은 저장하지 않는다 — 저장하면 계산 규칙이 바뀔 때 과거 행이 조용히 옛 규칙을
-- 말하게 되고, 어느 행이 어느 규칙으로 만들어졌는지 아무도 알 수 없다.
--
-- **`security_id` 참조.** ticker 변경과 무관하게 한 종목의 가격 이력을 유지한다.
--
-- 일별 시장 가격은 그 거래일에 공개된 사실이다. 수집 시각은 시장 공개 시각이 아니므로
-- PIT 경계로 저장하지 않는다. 수집 변경은 로컬/Parquet 배치 manifest가 추적한다.
--
-- 분할·배당은 가격과 grain이 달라 각자 표를 갖는다. 가격 행에 컬럼으로 붙이면 그날
-- 이벤트가 없는 대다수 행에 NULL이 깔리고, 이벤트만 따로 세는 질문에 답할 수 없다.

CREATE SCHEMA IF NOT EXISTS market;

REVOKE ALL ON SCHEMA market FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA market TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA market
  REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA market GRANT ALL     ON TABLES    TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA market GRANT SELECT  ON TABLES    TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA market GRANT ALL     ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA market
  REVOKE ALL ON FUNCTIONS FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA market GRANT EXECUTE ON FUNCTIONS TO service_role;


-- ── 일별 시세 ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market.prices_daily (
  security_id integer     NOT NULL REFERENCES universe.securities(security_id) ON DELETE CASCADE,
  trade_date  date        NOT NULL,
  open        double precision NOT NULL,
  high        double precision NOT NULL,
  low         double precision NOT NULL,
  close       double precision NOT NULL,
  volume      bigint      NOT NULL CHECK (volume >= 0),
  is_repaired boolean     NOT NULL DEFAULT false,
  PRIMARY KEY (security_id, trade_date),
  -- OHLC가 서로 모순이면 그 봉은 어떤 계산에도 쓸 수 없다. 넣는 시점에 막는다.
  CONSTRAINT prices_daily_ohlc_check CHECK (
    open > 0 AND high > 0 AND low > 0 AND close > 0
    AND high >= greatest(open, low, close)
    AND low <= least(open, high, close)
  ),
  -- NaN/Infinity는 float8에 들어간다. 들어오면 이후 모든 집계가 조용히 NaN이 된다.
  CONSTRAINT prices_daily_finite_check CHECK (
    NOT coalesce(
      ARRAY[open, high, low, close]
        && ARRAY['NaN'::double precision, 'Infinity'::double precision, '-Infinity'::double precision],
      false
    )
  )
);

-- 횡단면 조회("그날 전 종목 종가")가 주 질문이라 trade_date를 앞에 둔다.
CREATE INDEX IF NOT EXISTS prices_daily_trade_date_idx
  ON market.prices_daily (trade_date, security_id);


-- ── 주식분할 ──────────────────────────────────────────────────────────────
-- 비율 1은 분할이 아니다. 그런 행이 들어오면 조정 계산이 아무것도 안 하면서
-- "분할이 있었다"고 말하게 된다.
CREATE TABLE IF NOT EXISTS market.split_events (
  security_id integer     NOT NULL REFERENCES universe.securities(security_id) ON DELETE CASCADE,
  action_date date        NOT NULL,
  split_ratio double precision NOT NULL CHECK (split_ratio > 0 AND split_ratio <> 1),
  PRIMARY KEY (security_id, action_date)
);
-- 날짜만으로 훑는 조회가 없다. 모든 읽기가 security_id로 먼저 좁히므로 PK가
-- 그대로 그 인덱스다 — 느린 쿼리가 실제로 나오기 전에는 더 만들지 않는다.


-- ── 배당 ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market.dividend_events (
  security_id integer     NOT NULL REFERENCES universe.securities(security_id) ON DELETE CASCADE,
  ex_date     date        NOT NULL,
  div_amount  double precision NOT NULL CHECK (div_amount >= 0),
  PRIMARY KEY (security_id, ex_date)
);
-- split_events와 같은 이유로 날짜 단독 인덱스를 두지 않는다.


-- ── RLS ───────────────────────────────────────────────────────────────────
ALTER TABLE market.prices_daily    ENABLE ROW LEVEL SECURITY;
ALTER TABLE market.split_events    ENABLE ROW LEVEL SECURITY;
ALTER TABLE market.dividend_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS prices_daily_read    ON market.prices_daily;
DROP POLICY IF EXISTS split_events_read    ON market.split_events;
DROP POLICY IF EXISTS dividend_events_read ON market.dividend_events;

CREATE POLICY prices_daily_read    ON market.prices_daily    FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY split_events_read    ON market.split_events    FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY dividend_events_read ON market.dividend_events FOR SELECT TO anon, authenticated USING (true);
