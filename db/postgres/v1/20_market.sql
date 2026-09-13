-- market — 거래일 단위 시세와 기업행위.
--
-- 이 스키마는 **관측한 것만** 담는다. 조정가·수익률·이동평균처럼 계산으로 나오는 값은
-- 저장하지 않는다 — 계산 규칙이 바뀔 때 과거 행이 조용히 옛 규칙을 말하게 되기 때문이다.
--
-- 가격은 공급자의 현재 정정 기준 값 하나만 둔다. 누락·오류는 종목·기간 단위로 다시 받아
-- 같은 키를 갱신해 복구한다. 공급자 원문 일봉은 security_id별 Parquet archive가 보관한다.
--
-- 분할과 배당은 "그날 무슨 기업행위가 있었나"라는 같은 질문이라 한 표로 둔다. 가격과는
-- 존재하는 날짜가 달라 합치지 않는다 — 기업행위만 있는 날 가짜 봉을 만들지 않는다.

CREATE SCHEMA IF NOT EXISTS market;

REVOKE ALL ON SCHEMA market FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA market TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA market REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA market GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA market GRANT USAGE, SELECT ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA market REVOKE ALL ON FUNCTIONS FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA market GRANT EXECUTE ON FUNCTIONS TO service_role;


-- ── 일별 시세 ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market.prices_daily (
  security_id integer     NOT NULL REFERENCES universe.securities(security_id) ON DELETE RESTRICT,
  trade_date  date        NOT NULL,
  open        double precision NOT NULL,
  high        double precision NOT NULL,
  low         double precision NOT NULL,
  close       double precision NOT NULL,
  volume      bigint      NOT NULL CHECK (volume >= 0),
  is_repaired boolean     NOT NULL DEFAULT false,
  PRIMARY KEY (security_id, trade_date),
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

-- 종목 시계열은 PK가, "그날 전 종목"이라는 횡단면 질문은 이 인덱스가 받는다.
CREATE INDEX IF NOT EXISTS prices_daily_trade_date_idx
  ON market.prices_daily (trade_date, security_id);

COMMENT ON TABLE market.prices_daily IS
  '종목 하나의 거래일 하나 일봉 = 한 행. 공급자(Yahoo)의 현재 정정 기준 값이며 분할만 반영되고 배당 조정은 하지 않은 가격이다(auto_adjust=False).';
COMMENT ON COLUMN market.prices_daily.security_id IS '종목 ID. 수집 시작 때 고정한 요청 주소로 받은 자료만 이 ID에 쓴다.';
COMMENT ON COLUMN market.prices_daily.trade_date IS '미국 거래일(ET).';
COMMENT ON COLUMN market.prices_daily.open IS '시가(USD, 분할 조정).';
COMMENT ON COLUMN market.prices_daily.high IS '고가(USD, 분할 조정).';
COMMENT ON COLUMN market.prices_daily.low IS '저가(USD, 분할 조정).';
COMMENT ON COLUMN market.prices_daily.close IS '종가(USD, 분할 조정, 배당 미조정).';
COMMENT ON COLUMN market.prices_daily.volume IS '거래량(주, 분할 조정).';
COMMENT ON COLUMN market.prices_daily.is_repaired IS '공급자 원값의 명백한 단위·분할 오류를 수집기가 보정한 봉인가.';


-- ── 기업행위 ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market.actions_daily (
  security_id       integer NOT NULL REFERENCES universe.securities(security_id) ON DELETE RESTRICT,
  action_date       date    NOT NULL,
  split_ratio       double precision
                    CHECK (split_ratio IS NULL OR (split_ratio > 0 AND split_ratio <> 1
                           AND split_ratio < 'Infinity'::double precision)),
  dividend_amount   double precision
                    CHECK (dividend_amount IS NULL OR (dividend_amount > 0
                           AND dividend_amount < 'Infinity'::double precision)),
  dividend_currency text CHECK (dividend_currency IS NULL OR dividend_currency ~ '^[A-Z]{3}$'),
  source            text NOT NULL CHECK (btrim(source) <> ''),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (security_id, action_date),
  CONSTRAINT actions_daily_has_action_check
    CHECK (split_ratio IS NOT NULL OR dividend_amount IS NOT NULL),
  CONSTRAINT actions_daily_currency_pairing_check
    CHECK ((dividend_amount IS NULL) = (dividend_currency IS NULL))
);

COMMENT ON TABLE market.actions_daily IS
  '종목 하나의 날짜 하나에 있었던 기업행위 요약 = 한 행. 같은 날 분할과 배당이 있으면 한 행에 둘 다 담는다. 개별 배당 지급·합병 원장은 아니다.';
COMMENT ON COLUMN market.actions_daily.security_id IS '종목 ID.';
COMMENT ON COLUMN market.actions_daily.action_date IS '효력일: 분할은 적용일, 배당은 배당락일(ex-date).';
COMMENT ON COLUMN market.actions_daily.split_ratio IS '분할 비율(새 주식 수/옛 주식 수, 2:1 분할=2). 그날 분할이 없으면 NULL.';
COMMENT ON COLUMN market.actions_daily.dividend_amount IS '주당 현금 배당(dividend_currency 단위). 그날 배당락이 없으면 NULL.';
COMMENT ON COLUMN market.actions_daily.dividend_currency IS '배당 통화(ISO 4217). 배당이 없으면 NULL.';
COMMENT ON COLUMN market.actions_daily.source IS '마지막으로 값을 알려 준 원천(yfinance).';
COMMENT ON COLUMN market.actions_daily.updated_at IS '값이 마지막으로 바뀐 시각.';

-- 부분 응답이 기존 기업행위를 지우지 않게 병합한다. 배당만 다시 받아도 그날 분할은 남고,
-- 같은 배당을 두 번 받아도 더하지 않는다 — 재실행은 같은 결과가 된다.
-- 공급자가 실제로 취소·정정한 기업행위는 이 경로가 아니라 명시적인 정정으로 고친다.
CREATE OR REPLACE FUNCTION market.merge_actions(p_rows jsonb)
RETURNS integer LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE changed integer;
BEGIN
  IF p_rows IS NULL OR jsonb_typeof(p_rows) <> 'array' THEN
    RAISE EXCEPTION 'merge_actions expects a json array';
  END IF;
  WITH incoming AS (
    SELECT (r->>'security_id')::integer AS security_id,
           (r->>'action_date')::date AS action_date,
           (r->>'split_ratio')::double precision AS split_ratio,
           (r->>'dividend_amount')::double precision AS dividend_amount,
           nullif(r->>'dividend_currency', '') AS dividend_currency,
           coalesce(nullif(r->>'source', ''), 'yfinance') AS source
    FROM jsonb_array_elements(p_rows) r
  ), written AS (
    INSERT INTO market.actions_daily AS a
      (security_id, action_date, split_ratio, dividend_amount, dividend_currency, source)
    SELECT security_id, action_date, split_ratio, dividend_amount,
           CASE WHEN dividend_amount IS NULL THEN NULL ELSE coalesce(dividend_currency, 'USD') END,
           source
    FROM incoming
    ON CONFLICT (security_id, action_date) DO UPDATE SET
      split_ratio = coalesce(EXCLUDED.split_ratio, a.split_ratio),
      dividend_amount = coalesce(EXCLUDED.dividend_amount, a.dividend_amount),
      dividend_currency = CASE WHEN EXCLUDED.dividend_amount IS NULL THEN a.dividend_currency
                               ELSE EXCLUDED.dividend_currency END,
      source = EXCLUDED.source,
      updated_at = pg_catalog.now()
    WHERE (a.split_ratio, a.dividend_amount, a.dividend_currency) IS DISTINCT FROM
          (coalesce(EXCLUDED.split_ratio, a.split_ratio),
           coalesce(EXCLUDED.dividend_amount, a.dividend_amount),
           CASE WHEN EXCLUDED.dividend_amount IS NULL THEN a.dividend_currency
                ELSE EXCLUDED.dividend_currency END)
    RETURNING 1
  )
  SELECT count(*) INTO changed FROM written;
  RETURN changed;
END;
$fn$;
COMMENT ON FUNCTION market.merge_actions(jsonb) IS
  '기업행위 행 배열([{security_id, action_date, split_ratio?, dividend_amount?, dividend_currency?, source}])을 병합한다. 응답에 없는 값은 지우지 않고, 실제로 바뀐 행 수를 돌려준다.';


-- ── 권한 ──────────────────────────────────────────────────────────────────
GRANT ALL ON ALL TABLES IN SCHEMA market TO service_role;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA market FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA market TO service_role;

ALTER TABLE market.prices_daily  ENABLE ROW LEVEL SECURITY;
ALTER TABLE market.actions_daily ENABLE ROW LEVEL SECURITY;
