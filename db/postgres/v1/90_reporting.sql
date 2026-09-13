-- reporting — 사실 스키마를 조합하는 읽기 전용 뷰.
--
-- 두 층이 있다.
--   * 사람이 여는 6개 뷰: security_overview · financial_statements · earnings_outlook ·
--     earnings_surprises · economic_calendar · institutional_holdings. 한 행의 뜻과
--     기본 칼럼만 보여 준다.
--   * 코드 계약 뷰: 화면·알림·AI evidence가 `reporting/readers/financial.py`의 VIEWS 선언
--     그대로 읽는다. 컬럼을 바꾸면 그 선언도 함께 바꾼다.
-- 뷰는 값을 저장하지 않는다. 계산 규칙이 바뀌면 과거 행도 새 규칙으로 읽힌다.

CREATE SCHEMA IF NOT EXISTS reporting;

REVOKE ALL ON SCHEMA reporting FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA reporting TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA reporting REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA reporting GRANT SELECT ON TABLES TO service_role;


-- ════════════════════════════════════════════════════════════════════════
-- 코드 계약 뷰
-- ════════════════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW reporting.securities WITH (security_invoker = true) AS
SELECT
  s.security_id,
  s.ticker,
  s.cik,
  e.company_name,
  e.company_name_ko,
  e.sic_industry_name,
  e.sic_division_name,
  s.exchange_code,
  s.security_type,
  s.is_active_listing,
  s.is_identity_verified,
  s.is_tracked,
  COALESCE(e.is_watchlisted, false) AS is_watchlisted,
  COALESCE(e.watchlist_sources, ARRAY[]::text[]) AS watchlist_sources,
  e.watch_from
FROM universe.securities s
LEFT JOIN universe.entities e ON e.cik = s.cik;
COMMENT ON VIEW reporting.securities IS '종목 하나 = 한 행. 수집 게이트(is_tracked)와 관심 기업(is_watchlisted)은 다른 개념이라 둘 다 낸다.';

CREATE OR REPLACE VIEW reporting.prices_daily WITH (security_invoker = true) AS
SELECT
  p.security_id,
  s.ticker,
  p.trade_date,
  p.open, p.high, p.low, p.close, p.volume,
  p.is_repaired
FROM market.prices_daily p
JOIN universe.securities s ON s.security_id = p.security_id;
COMMENT ON VIEW reporting.prices_daily IS '종목·거래일 일봉 = 한 행. ticker는 현재 표기다 — 과거 날짜 행에도 지금 이름이 붙는다.';

CREATE OR REPLACE VIEW reporting.company_financials_latest WITH (security_invoker = true) AS
SELECT
  f.cik,
  f.period_end,
  f.fiscal_year,
  f.fiscal_period,
  f.accession_no,
  f.filing_date,
  f.form_type,
  f.available_at,
  f.revenue,
  f.operating_income_loss,
  f.net_income,
  f.eps_diluted_gaap,
  f.mapping_version
FROM fundamentals.financials f;
COMMENT ON VIEW reporting.company_financials_latest IS '회사·회계기간마다 최신 공시 버전의 핵심 재무 한 행. PIT 조회에 쓰지 않는다.';

CREATE OR REPLACE VIEW reporting.earnings_schedule WITH (security_invoker = true) AS
SELECT DISTINCT ON (v.security_id, v.target_fiscal_year, v.target_fiscal_period)
  v.security_id,
  s.ticker,
  v.target_fiscal_year,
  v.target_fiscal_period,
  v.target_period_end,
  v.expected_report_at,
  v.expected_report_date,
  v.expected_session,
  v.is_estimated,
  v.snapshot_date,
  v.last_seen_at,
  -- 직전 상태의 예정 시각. 버전은 바뀔 때만 생기므로 NULL이 아니면 일정이 움직인 것이다.
  lag(v.expected_report_at) OVER (
    PARTITION BY v.security_id, v.target_fiscal_year, v.target_fiscal_period
    ORDER BY v.snapshot_date, v.collected_at
  ) AS previous_report_at
FROM fundamentals.earnings_schedule_versions v
JOIN universe.securities s ON s.security_id = v.security_id
ORDER BY v.security_id, v.target_fiscal_year, v.target_fiscal_period, v.snapshot_date DESC, v.collected_at DESC;
COMMENT ON VIEW reporting.earnings_schedule IS '종목·대상 분기마다 현재 발표 예정 한 행과 직전 예정 시각.';

-- 발표 전에 알려져 있던 컨센서스와 실제치를 비교한다.
--   * 대상 예상: captured_live(직접 수집)·vendor_pit(당시 값 보장)만. reconstructed와
--     latest_history는 발표 뒤에 만든 값일 수 있어 쓰지 않는다.
--   * 발표 전: 공시일보다 앞선 상태, 또는 공시일 당일에 공시를 손에 넣기 전에 수집한 상태.
--   * 비율은 분수다(0.05 = +5%). 이름에 ratio를 붙여 %로 오해하지 않게 한다.
--   * EPS 정의가 서로 다르면(GAAP vs adjusted) EPS 서프라이즈를 내지 않고, 한쪽이라도
--     unknown이면 값을 내되 eps_basis_match='unknown'으로 드러낸다.
CREATE OR REPLACE VIEW reporting.earnings_surprise WITH (security_invoker = true) AS
SELECT
  s.security_id,
  s.ticker,
  r.cik,
  r.fiscal_year,
  r.fiscal_period,
  r.period_end,
  f.filing_date,
  f.available_at,
  r.accession_no,
  r.revenue_actual,
  r.eps_actual,
  r.eps_basis AS eps_actual_basis,
  e.eps_avg      AS eps_estimate,
  e.revenue_avg  AS revenue_estimate,
  e.eps_basis    AS eps_estimate_basis,
  e.snapshot_kind AS estimate_kind,
  e.snapshot_date AS estimate_snapshot_date,
  e.collected_at AS estimate_collected_at,
  e.eps_analysts,
  CASE
    WHEN e.security_id IS NULL THEN NULL
    WHEN r.eps_basis = 'unknown' OR e.eps_basis = 'unknown' THEN 'unknown'
    WHEN r.eps_basis = e.eps_basis THEN 'match'
    ELSE 'mismatch'
  END AS eps_basis_match,
  CASE WHEN e.eps_avg IS NOT NULL AND e.eps_avg <> 0 AND r.eps_actual IS NOT NULL
            AND NOT (r.eps_basis <> 'unknown' AND e.eps_basis <> 'unknown' AND r.eps_basis <> e.eps_basis)
       THEN (r.eps_actual - e.eps_avg) / abs(e.eps_avg) END AS eps_surprise_ratio,
  CASE WHEN e.revenue_avg IS NOT NULL AND e.revenue_avg <> 0 AND r.revenue_actual IS NOT NULL
       THEN (r.revenue_actual - e.revenue_avg) / abs(e.revenue_avg) END AS revenue_surprise_ratio,
  r.guidance_summary,
  r.operating_income_actual,
  r.net_income_actual,
  r.press_release_url
FROM fundamentals.earnings_results r
JOIN fundamentals.filings f ON f.accession_no = r.accession_no
JOIN universe.securities s ON s.cik = r.cik AND s.is_active_listing
LEFT JOIN LATERAL (
  SELECT est.security_id, est.eps_avg, est.revenue_avg, est.eps_basis, est.snapshot_kind,
         est.snapshot_date, est.collected_at, est.eps_analysts
  FROM fundamentals.earnings_estimates est
  WHERE est.security_id = s.security_id
    AND est.target_fiscal_year = r.fiscal_year
    AND est.target_fiscal_period = r.fiscal_period
    AND est.snapshot_kind IN ('captured_live', 'vendor_pit')
    AND (est.snapshot_date < f.filing_date
         OR (est.snapshot_date = f.filing_date AND est.collected_at < f.available_at))
  ORDER BY est.snapshot_date DESC, est.collected_at DESC,
           CASE est.snapshot_kind WHEN 'captured_live' THEN 0 ELSE 1 END
  LIMIT 1
) e ON true;
COMMENT ON VIEW reporting.earnings_surprise IS '실적 발표(8-K) 하나·상장 종목 하나 = 한 행. 발표 전에 알려진 컨센서스만 비교한다. *_surprise_ratio는 분수(0.05=+5%).';

CREATE OR REPLACE VIEW reporting.institutional_filings WITH (security_invoker = true) AS
SELECT f.accession_no, f.manager_cik, f.period_end, f.form_type, f.report_type, f.filing_date, f.accepted_at,
       f.amendment_type, f.amendment_no, f.reported_value_usd, f.reported_line_count,
       f.confidential_omitted, f.source_url, f.content_sha256
FROM institutional.filings f;
COMMENT ON VIEW reporting.institutional_filings IS '13F 보고서 하나 = 한 행.';

-- 보유 줄의 종목은 보고 분기말을 기준일로 식별한다. 제출일의 현재 ticker를 붙이지 않는다.
CREATE OR REPLACE VIEW reporting.institutional_positions WITH (security_invoker = true) AS
SELECT p.accession_no, p.source_row_no, p.issuer_name, p.identifier AS cusip,
       p.identifier_type, p.value_usd, p.quantity, p.quantity_type,
       p.position_kind, s.security_id, s.ticker
FROM institutional.positions p
JOIN institutional.filings f ON f.accession_no = p.accession_no
LEFT JOIN universe.securities s
  ON s.security_id = universe.security_on(p.identifier_type, 'cgs', p.identifier, f.period_end);
COMMENT ON VIEW reporting.institutional_positions IS '13F 보유 줄 하나 = 한 행. security_id·ticker가 NULL이면 분기말 기준으로 확인된 종목 연결이 없다.';

CREATE OR REPLACE VIEW reporting.macro_observation_history WITH (security_invoker = true) AS
SELECT s.series_code AS series_id, o.observation_date AS ref_period, o.value,
       (o.observation_date + time '23:59:59.999999') AT TIME ZONE 'UTC' AS effective_at,
       NULL::timestamptz AS collected_at, 'date_only'::text AS time_precision, s.source_code
FROM macro.market_observations o JOIN macro.series s USING(series_key)
UNION ALL
SELECT s.series_code, o.observation_date, o.value, o.vintage_at, o.available_at,
       o.time_precision, o.source_code
FROM macro.economic_observations o JOIN macro.series s USING(series_key);
COMMENT ON VIEW reporting.macro_observation_history IS '지표 원값의 관측·빈티지 하나 = 한 행. 시장 지표의 effective_at은 실제 공개 시각이 아니라 그날의 끝(UTC)이다.';

CREATE OR REPLACE VIEW reporting.macro_latest WITH (security_invoker = true) AS
SELECT DISTINCT ON (o.series_id)
  o.series_id,
  s.name_ko,
  s.domain,
  s.frequency,
  s.unit,
  o.ref_period,
  o.value,
  o.effective_at,
  o.collected_at
FROM reporting.macro_observation_history o
JOIN macro.series s ON s.series_code = o.series_id
ORDER BY o.series_id, o.ref_period DESC, o.effective_at DESC, o.collected_at DESC NULLS LAST;
COMMENT ON VIEW reporting.macro_latest IS '지표마다 가장 최근 기간의 최신 원값 한 행.';

CREATE OR REPLACE VIEW reporting.macro_series WITH (security_invoker = true) AS
SELECT
  s.series_code AS series_id,
  s.name_ko,
  s.description,
  s.country,
  s.category,
  s.frequency,
  s.unit AS base_unit,
  s.timezone,
  s.source_code AS source,
  s.domain,
  s.series_kind
FROM macro.series s;
COMMENT ON VIEW reporting.macro_series IS '지표 정의 한 행. base_unit은 원값 단위다.';

CREATE OR REPLACE VIEW reporting.macro_observations WITH (security_invoker = true) AS
SELECT DISTINCT ON (o.series_id, o.ref_period)
  o.series_id,
  o.ref_period AS obs_date,
  o.value,
  o.effective_at,
  o.collected_at
FROM reporting.macro_observation_history o
ORDER BY o.series_id, o.ref_period, o.effective_at DESC, o.collected_at DESC NULLS LAST;
COMMENT ON VIEW reporting.macro_observations IS '지표·기간마다 최신 빈티지 원값 한 행. 개정이 반영된 현재 값이라 PIT 조회에 쓰지 않는다.';

CREATE OR REPLACE VIEW reporting.macro_measures WITH (security_invoker = true) AS
SELECT
  m.measure_id,
  s.series_code AS series_id,
  m.name_ko,
  m.unit,
  m.transform,
  m.is_primary,
  m.rollup_method
FROM macro.measures m JOIN macro.series s USING(series_key);
COMMENT ON VIEW reporting.macro_measures IS 'measure 정의 한 행.';

-- 빈티지마다 대표 measure 값을 그 빈티지 시점까지 공개된 원값으로 계산한다.
CREATE OR REPLACE VIEW reporting.macro_release_actuals WITH (security_invoker = true) AS
SELECT
  s.series_code AS series_id,
  o.observation_date AS ref_period,
  m.measure_id,
  macro.measure_value(m.measure_id, o.observation_date, o.vintage_at) AS value,
  o.value AS raw_value,
  o.vintage_at AS effective_at,
  o.available_at AS collected_at,
  o.time_precision,
  o.source_code AS source
FROM macro.economic_observations o
JOIN macro.series s ON s.series_key = o.series_key
JOIN macro.measures m ON m.series_key = o.series_key AND m.is_primary;
COMMENT ON VIEW reporting.macro_release_actuals IS '경제지표 빈티지 하나 = 한 행. value는 대표 measure 단위(예: 전월비 %), raw_value는 원값(예: 지수).';

CREATE OR REPLACE VIEW reporting.macro_release_forecasts WITH (security_invoker = true) AS
SELECT
  s.series_code AS series_id,
  fv.ref_period,
  fv.measure_id,
  fv.forecast_kind,
  fv.source_code AS source,
  fv.value,
  fv.effective_at AS as_of,
  fv.collected_at,
  lag(fv.value) OVER (
    PARTITION BY fv.series_key, fv.ref_period, fv.measure_id, fv.forecast_kind, fv.source_code
    ORDER BY fv.effective_at, fv.collected_at
  ) AS previous_value,
  fv.value - lag(fv.value) OVER (
    PARTITION BY fv.series_key, fv.ref_period, fv.measure_id, fv.forecast_kind, fv.source_code
    ORDER BY fv.effective_at, fv.collected_at
  ) AS change_amount
FROM macro.forecast_snapshots fv
JOIN macro.series s ON s.series_key = fv.series_key;
COMMENT ON VIEW reporting.macro_release_forecasts IS '예상값 확인 상태 하나 = 한 행과 같은 원천의 직전 값 대비 변화. 값은 measure 단위.';

-- 발표 하나 = 한 행. 비교는 전부 대표 measure 단위다.
--   first_actual_*  최초 빈티지(시장이 처음 받은 값)
--   latest_actual_* 개정이 반영된 현재 값
--   closing_*       최초 발표 시점까지 공개된 마지막 예상(원천 시점 effective_at 기준)
--   market_surprise = 최초 실제 - closing survey, revision = 현재 실제 - 최초 실제
-- 실제치가 없으면 closing과 서프라이즈는 NULL이다 — 발표 전 cutoff 없이 최신 예상을 closing으로
-- 부르지 않는다.
CREATE OR REPLACE VIEW reporting.macro_release_summary WITH (security_invoker = true) AS
SELECT
  x.series_code || ':' || x.ref_period::text AS event_key,
  x.series_code AS series_id,
  x.name_ko AS series_name_ko,
  x.country,
  x.category,
  x.frequency,
  x.timezone,
  x.ref_period,
  x.scheduled_at,
  x.schedule_source,
  x.schedule_precision AS schedule_confidence,
  CASE
    WHEN x.is_cancelled THEN 'cancelled'
    WHEN x.first_vintage_at IS NOT NULL THEN 'released'
    WHEN x.scheduled_at <= now() THEN 'not_available_yet'
    ELSE 'scheduled'
  END AS status,
  x.first_vintage_at AS first_actual_at,
  x.first_precision AS first_actual_precision,
  x.measure_id,
  split_part(x.measure_id, '.', 2) AS measure_code,
  x.measure_name_ko,
  x.unit,
  x.decimal_places,
  (x.first_value IS NOT NULL AND x.closing_survey_value IS NOT NULL) AS is_surprise_eligible,
  x.first_value AS first_actual_value,
  x.latest_value AS latest_actual_value,
  x.latest_vintage_at AS latest_actual_effective_at,
  x.survey_value,
  x.nowcast_value,
  x.own_model_value,
  x.closing_survey_value,
  x.closing_nowcast_value,
  x.closing_own_model_value,
  x.first_value - x.closing_survey_value AS market_surprise,
  x.first_value - x.closing_nowcast_value AS nowcast_error,
  x.first_value - x.closing_own_model_value AS model_error,
  x.latest_value - x.first_value AS revision
FROM (
  SELECT
    v.*,
    (SELECT fv.value FROM macro.forecast_snapshots fv
      WHERE fv.series_key = v.series_key AND fv.ref_period = v.ref_period
        AND fv.measure_id = v.measure_id AND fv.forecast_kind = 'survey'
      ORDER BY fv.effective_at DESC, fv.collected_at DESC, fv.source_code LIMIT 1) AS survey_value,
    (SELECT fv.value FROM macro.forecast_snapshots fv
      WHERE fv.series_key = v.series_key AND fv.ref_period = v.ref_period
        AND fv.measure_id = v.measure_id AND fv.forecast_kind = 'nowcast'
      ORDER BY fv.effective_at DESC, fv.collected_at DESC, fv.source_code LIMIT 1) AS nowcast_value,
    (SELECT fv.value FROM macro.forecast_snapshots fv
      WHERE fv.series_key = v.series_key AND fv.ref_period = v.ref_period
        AND fv.measure_id = v.measure_id AND fv.forecast_kind = 'own_model'
      ORDER BY fv.effective_at DESC, fv.collected_at DESC, fv.source_code LIMIT 1) AS own_model_value,
    (SELECT fv.value FROM macro.forecast_snapshots fv
      WHERE v.first_vintage_at IS NOT NULL
        AND fv.series_key = v.series_key AND fv.ref_period = v.ref_period
        AND fv.measure_id = v.measure_id AND fv.forecast_kind = 'survey'
        AND fv.effective_at <= v.first_vintage_at
      ORDER BY fv.effective_at DESC, fv.collected_at DESC, fv.source_code LIMIT 1) AS closing_survey_value,
    (SELECT fv.value FROM macro.forecast_snapshots fv
      WHERE v.first_vintage_at IS NOT NULL
        AND fv.series_key = v.series_key AND fv.ref_period = v.ref_period
        AND fv.measure_id = v.measure_id AND fv.forecast_kind = 'nowcast'
        AND fv.effective_at <= v.first_vintage_at
      ORDER BY fv.effective_at DESC, fv.collected_at DESC, fv.source_code LIMIT 1) AS closing_nowcast_value,
    (SELECT fv.value FROM macro.forecast_snapshots fv
      WHERE v.first_vintage_at IS NOT NULL
        AND fv.series_key = v.series_key AND fv.ref_period = v.ref_period
        AND fv.measure_id = v.measure_id AND fv.forecast_kind = 'own_model'
        AND fv.effective_at <= v.first_vintage_at
      ORDER BY fv.effective_at DESC, fv.collected_at DESC, fv.source_code LIMIT 1) AS closing_own_model_value
  FROM (
  SELECT
    b.*,
    CASE WHEN b.first_vintage_at IS NOT NULL
         THEN macro.measure_value(b.measure_id, b.ref_period, b.first_vintage_at) END AS first_value,
    CASE WHEN b.latest_vintage_at IS NOT NULL
         THEN macro.measure_value(b.measure_id, b.ref_period, 'infinity'::timestamptz) END AS latest_value
  FROM (
  SELECT
    e.series_key,
    e.ref_period,
    s.series_code,
    s.name_ko,
    s.country,
    s.category,
    s.frequency,
    s.timezone,
    m.measure_id,
    m.name_ko AS measure_name_ko,
    m.unit,
    m.decimal_places,
    schedule.scheduled_at,
    schedule.schedule_precision,
    schedule.is_cancelled,
    schedule.source AS schedule_source,
    first_raw.vintage_at AS first_vintage_at,
    first_raw.time_precision AS first_precision,
    latest_raw.vintage_at AS latest_vintage_at
  FROM macro.release_events e
  JOIN macro.series s ON s.series_key = e.series_key
  JOIN macro.measures m ON m.series_key = e.series_key AND m.is_primary
  JOIN LATERAL (
    SELECT sv.scheduled_at, sv.schedule_precision, sv.is_cancelled, sv.source_code AS source
    FROM macro.release_schedule_versions sv
    WHERE sv.series_key = e.series_key AND sv.ref_period = e.ref_period
    ORDER BY sv.collected_at DESC
    LIMIT 1
  ) schedule ON true
  LEFT JOIN LATERAL (
    SELECT o.vintage_at, o.time_precision
    FROM macro.economic_observations o
    WHERE o.series_key = e.series_key AND o.observation_date = e.ref_period
    ORDER BY o.vintage_at, o.available_at
    LIMIT 1
  ) first_raw ON true
  LEFT JOIN LATERAL (
    SELECT o.vintage_at
    FROM macro.economic_observations o
    WHERE o.series_key = e.series_key AND o.observation_date = e.ref_period
    ORDER BY o.vintage_at DESC, o.available_at DESC
    LIMIT 1
  ) latest_raw ON true
  ) b
  ) v
) x;

COMMENT ON VIEW reporting.macro_release_summary IS '경제지표 발표 하나 = 한 행. 실제·예상·서프라이즈는 모두 대표 measure 단위이며, 서프라이즈는 최초 발표 값과 발표 전 마지막 예상의 차이다.';


-- ════════════════════════════════════════════════════════════════════════
-- 사람이 여는 뷰
-- ════════════════════════════════════════════════════════════════════════
-- 컬럼 이름은 영문 snake_case, 뜻은 한국어 COMMENT로 적는다. 한국어 식별자는 SQL마다 따옴표가
-- 필요해 직접 조회를 오히려 어렵게 만든다.

CREATE OR REPLACE VIEW reporting.security_overview WITH (security_invoker = true) AS
SELECT
  s.ticker,
  e.company_name,
  e.company_name_ko,
  e.sic_division_name,
  s.exchange_code,
  s.security_type,
  s.is_active_listing,
  EXISTS (
    SELECT 1 FROM universe.index_memberships im
    WHERE im.security_id = s.security_id AND im.index_code = 'SP500' AND im.valid_to IS NULL
  ) AS is_sp500_member,
  s.is_tracked,
  s.is_identity_verified,
  COALESCE(e.is_watchlisted, false) AS is_watchlisted,
  s.security_id,
  s.cik
FROM universe.securities s
LEFT JOIN universe.entities e ON e.cik = s.cik;
COMMENT ON VIEW reporting.security_overview IS '[1. 종목] 종목 하나 = 한 행. 지금 무엇을 수집하고 있고 신원이 확인됐는지 본다.';
COMMENT ON COLUMN reporting.security_overview.ticker IS '현재 티커.';
COMMENT ON COLUMN reporting.security_overview.company_name IS '발행사 법인명.';
COMMENT ON COLUMN reporting.security_overview.company_name_ko IS '발행사 한국어 이름.';
COMMENT ON COLUMN reporting.security_overview.sic_division_name IS 'SIC 산업 대분류(GICS 섹터 아님).';
COMMENT ON COLUMN reporting.security_overview.exchange_code IS '상장 거래소.';
COMMENT ON COLUMN reporting.security_overview.security_type IS '증권 종류.';
COMMENT ON COLUMN reporting.security_overview.is_active_listing IS '상장 중인가.';
COMMENT ON COLUMN reporting.security_overview.is_sp500_member IS '지금 S&P 500에 편입돼 있는가.';
COMMENT ON COLUMN reporting.security_overview.is_tracked IS '수집 대상인가.';
COMMENT ON COLUMN reporting.security_overview.is_identity_verified IS 'SEC 거래소 목록으로 신원을 확인했는가.';
COMMENT ON COLUMN reporting.security_overview.is_watchlisted IS '관심 기업인가.';
COMMENT ON COLUMN reporting.security_overview.security_id IS '내부 종목 ID.';
COMMENT ON COLUMN reporting.security_overview.cik IS '발행사 CIK.';

CREATE OR REPLACE VIEW reporting.financial_statements WITH (security_invoker = true) AS
SELECT
  (SELECT string_agg(s.ticker, '/' ORDER BY s.ticker) FROM universe.securities s
    WHERE s.cik = f.cik AND s.is_active_listing) AS tickers,
  e.company_name,
  f.fiscal_year,
  f.fiscal_period,
  f.period_end,
  f.revenue,
  f.operating_income_loss,
  f.net_income,
  f.eps_diluted_gaap,
  f.net_cash_from_operating_activities,
  f.capital_expenses,
  f.filing_date,
  f.form_type,
  f.accession_no,
  f.cik
FROM fundamentals.financials f
JOIN universe.entities e ON e.cik = f.cik;
COMMENT ON VIEW reporting.financial_statements IS '[2. 재무] 회사·회계기간마다 최신 공시 기준 핵심 재무 한 행. 금액은 USD 원 단위.';
COMMENT ON COLUMN reporting.financial_statements.tickers IS '이 회사의 상장 티커(여럿이면 /로 연결).';
COMMENT ON COLUMN reporting.financial_statements.company_name IS '법인명.';
COMMENT ON COLUMN reporting.financial_statements.fiscal_year IS '회사 회계연도.';
COMMENT ON COLUMN reporting.financial_statements.fiscal_period IS 'FY 또는 Q1~Q4.';
COMMENT ON COLUMN reporting.financial_statements.period_end IS '회계기간 말일.';
COMMENT ON COLUMN reporting.financial_statements.revenue IS '매출(USD).';
COMMENT ON COLUMN reporting.financial_statements.operating_income_loss IS '영업이익(USD).';
COMMENT ON COLUMN reporting.financial_statements.net_income IS '순이익(USD).';
COMMENT ON COLUMN reporting.financial_statements.eps_diluted_gaap IS 'GAAP 희석 EPS(USD/주).';
COMMENT ON COLUMN reporting.financial_statements.net_cash_from_operating_activities IS '영업활동 현금흐름(USD).';
COMMENT ON COLUMN reporting.financial_statements.capital_expenses IS '설비투자(USD).';
COMMENT ON COLUMN reporting.financial_statements.filing_date IS '이 값을 보고한 공시의 제출일.';
COMMENT ON COLUMN reporting.financial_statements.form_type IS '공시 양식.';
COMMENT ON COLUMN reporting.financial_statements.accession_no IS '공시 접수번호(원문 연결).';
COMMENT ON COLUMN reporting.financial_statements.cik IS '발행사 CIK.';

CREATE OR REPLACE VIEW reporting.earnings_outlook WITH (security_invoker = true) AS
SELECT
  s.ticker,
  e.company_name,
  est.target_fiscal_year,
  est.target_fiscal_period,
  est.target_period_end,
  sch.expected_report_at,
  sch.expected_session,
  sch.is_estimated AS is_report_date_estimated,
  est.eps_avg,
  est.eps_basis,
  est.eps_analysts,
  est.revenue_avg,
  est.revenue_analysts,
  est.source,
  est.snapshot_kind,
  est.snapshot_date,
  est.last_seen_at,
  s.security_id
FROM universe.securities s
JOIN universe.entities e ON e.cik = s.cik
JOIN LATERAL (
  SELECT x.*
  FROM fundamentals.earnings_estimates x
  WHERE x.security_id = s.security_id
    AND x.snapshot_kind IN ('captured_live', 'vendor_pit')
    AND x.target_fiscal_period <> 'FY'
    AND NOT EXISTS (
      SELECT 1 FROM fundamentals.earnings_results r
      WHERE r.cik = s.cik AND r.fiscal_year = x.target_fiscal_year AND r.fiscal_period = x.target_fiscal_period)
  ORDER BY x.target_period_end, x.snapshot_date DESC, x.collected_at DESC
  LIMIT 1
) est ON true
LEFT JOIN LATERAL (
  SELECT v.expected_report_at, v.expected_session, v.is_estimated
  FROM fundamentals.earnings_schedule_versions v
  WHERE v.security_id = s.security_id
    AND v.target_fiscal_year = est.target_fiscal_year
    AND v.target_fiscal_period = est.target_fiscal_period
  ORDER BY v.snapshot_date DESC, v.collected_at DESC
  LIMIT 1
) sch ON true
WHERE s.is_tracked;
COMMENT ON VIEW reporting.earnings_outlook IS '[3. 실적 예상] 수집 중인 종목마다 아직 발표되지 않은 가장 가까운 분기의 현재 컨센서스와 발표 예정 한 행.';
COMMENT ON COLUMN reporting.earnings_outlook.ticker IS '티커.';
COMMENT ON COLUMN reporting.earnings_outlook.company_name IS '법인명.';
COMMENT ON COLUMN reporting.earnings_outlook.target_fiscal_year IS '예상 대상 회계연도.';
COMMENT ON COLUMN reporting.earnings_outlook.target_fiscal_period IS '예상 대상 분기.';
COMMENT ON COLUMN reporting.earnings_outlook.target_period_end IS '대상 분기 말일(추정일 수 있음).';
COMMENT ON COLUMN reporting.earnings_outlook.expected_report_at IS '발표 예정 시각(UTC). 일정이 없으면 NULL.';
COMMENT ON COLUMN reporting.earnings_outlook.expected_session IS '장전(bmo)/장후(amc)/장중(dmh)/미상.';
COMMENT ON COLUMN reporting.earnings_outlook.is_report_date_estimated IS '예정일이 추정인가.';
COMMENT ON COLUMN reporting.earnings_outlook.eps_avg IS 'EPS 예상 평균.';
COMMENT ON COLUMN reporting.earnings_outlook.eps_basis IS 'EPS 예상의 정의(unknown=공급자 미공개).';
COMMENT ON COLUMN reporting.earnings_outlook.eps_analysts IS 'EPS 예상 애널리스트 수.';
COMMENT ON COLUMN reporting.earnings_outlook.revenue_avg IS '매출 예상 평균.';
COMMENT ON COLUMN reporting.earnings_outlook.revenue_analysts IS '매출 예상 애널리스트 수.';
COMMENT ON COLUMN reporting.earnings_outlook.source IS '예상치 출처.';
COMMENT ON COLUMN reporting.earnings_outlook.snapshot_kind IS '수집 성격(captured_live=직접 수집).';
COMMENT ON COLUMN reporting.earnings_outlook.snapshot_date IS '이 예상 상태가 시작된 날짜.';
COMMENT ON COLUMN reporting.earnings_outlook.last_seen_at IS '이 상태를 마지막으로 확인한 시각. 오래됐으면 수집이 멈춘 것이다.';
COMMENT ON COLUMN reporting.earnings_outlook.security_id IS '내부 종목 ID.';

CREATE OR REPLACE VIEW reporting.earnings_surprises WITH (security_invoker = true) AS
SELECT
  x.ticker,
  x.fiscal_year,
  x.fiscal_period,
  x.filing_date,
  x.eps_actual,
  x.eps_estimate,
  round((x.eps_surprise_ratio * 100)::numeric, 2) AS eps_surprise_percent,
  x.eps_basis_match,
  x.revenue_actual,
  x.revenue_estimate,
  round((x.revenue_surprise_ratio * 100)::numeric, 2) AS revenue_surprise_percent,
  x.estimate_kind,
  x.estimate_snapshot_date,
  CASE
    WHEN x.eps_estimate IS NULL AND x.revenue_estimate IS NULL THEN '발표 전 수집한 예상 없음'
    WHEN x.eps_basis_match = 'mismatch' THEN 'EPS 정의 불일치로 EPS 비교 제외'
    WHEN x.eps_basis_match = 'unknown' THEN 'EPS 정의 미확인'
  END AS comparability_note,
  x.accession_no,
  x.security_id
FROM reporting.earnings_surprise x;
COMMENT ON VIEW reporting.earnings_surprises IS '[4. 실적 비교] 실적 발표 하나·종목 하나 = 한 행. 서프라이즈를 %로 보여 주고 비교할 수 없는 이유를 적는다.';
COMMENT ON COLUMN reporting.earnings_surprises.ticker IS '티커.';
COMMENT ON COLUMN reporting.earnings_surprises.fiscal_year IS '발표 대상 회계연도.';
COMMENT ON COLUMN reporting.earnings_surprises.fiscal_period IS '발표 대상 기간.';
COMMENT ON COLUMN reporting.earnings_surprises.filing_date IS '실적 8-K 제출일.';
COMMENT ON COLUMN reporting.earnings_surprises.eps_actual IS '발표 EPS.';
COMMENT ON COLUMN reporting.earnings_surprises.eps_estimate IS '발표 전 마지막 EPS 컨센서스.';
COMMENT ON COLUMN reporting.earnings_surprises.eps_surprise_percent IS 'EPS 서프라이즈(%). 정의가 다르면 NULL.';
COMMENT ON COLUMN reporting.earnings_surprises.eps_basis_match IS 'match=같은 정의, unknown=한쪽 정의 미확인, mismatch=정의 다름.';
COMMENT ON COLUMN reporting.earnings_surprises.revenue_actual IS '발표 매출.';
COMMENT ON COLUMN reporting.earnings_surprises.revenue_estimate IS '발표 전 마지막 매출 컨센서스.';
COMMENT ON COLUMN reporting.earnings_surprises.revenue_surprise_percent IS '매출 서프라이즈(%).';
COMMENT ON COLUMN reporting.earnings_surprises.estimate_kind IS '비교에 쓴 예상의 수집 성격.';
COMMENT ON COLUMN reporting.earnings_surprises.estimate_snapshot_date IS '비교에 쓴 예상 상태의 시작일.';
COMMENT ON COLUMN reporting.earnings_surprises.comparability_note IS '비교할 수 없거나 조심해야 하는 이유. 문제 없으면 NULL.';
COMMENT ON COLUMN reporting.earnings_surprises.accession_no IS '실적 8-K 접수번호.';
COMMENT ON COLUMN reporting.earnings_surprises.security_id IS '내부 종목 ID.';

CREATE OR REPLACE VIEW reporting.economic_calendar WITH (security_invoker = true) AS
SELECT
  x.scheduled_at AT TIME ZONE 'Asia/Seoul' AS scheduled_at_kst,
  x.scheduled_at AT TIME ZONE 'America/New_York' AS scheduled_at_et,
  x.series_name_ko,
  x.ref_period,
  x.status,
  x.measure_name_ko,
  x.unit,
  x.first_actual_value,
  x.closing_survey_value,
  x.market_surprise,
  x.closing_nowcast_value,
  x.closing_own_model_value,
  x.latest_actual_value,
  x.revision,
  x.series_id,
  x.measure_id
FROM reporting.macro_release_summary x;
COMMENT ON VIEW reporting.economic_calendar IS '[5. 경제 일정] 경제지표 발표 하나 = 한 행. 모든 값은 비교 단위(measure) 기준이고 서프라이즈는 최초발표-시장예상이다.';
COMMENT ON COLUMN reporting.economic_calendar.scheduled_at_kst IS '발표 예정 시각(한국 시간).';
COMMENT ON COLUMN reporting.economic_calendar.scheduled_at_et IS '발표 예정 시각(미국 동부 시간).';
COMMENT ON COLUMN reporting.economic_calendar.series_name_ko IS '지표 이름.';
COMMENT ON COLUMN reporting.economic_calendar.ref_period IS '발표 대상 기간.';
COMMENT ON COLUMN reporting.economic_calendar.status IS 'scheduled=예정, not_available_yet=시각이 지났으나 값 없음, released=발표됨, cancelled=취소.';
COMMENT ON COLUMN reporting.economic_calendar.measure_name_ko IS '비교 단위 이름(전월비 등).';
COMMENT ON COLUMN reporting.economic_calendar.unit IS '비교 단위의 단위.';
COMMENT ON COLUMN reporting.economic_calendar.first_actual_value IS '최초 발표 값.';
COMMENT ON COLUMN reporting.economic_calendar.closing_survey_value IS '발표 전 마지막 시장 컨센서스.';
COMMENT ON COLUMN reporting.economic_calendar.market_surprise IS '최초 발표 값 - 시장 컨센서스.';
COMMENT ON COLUMN reporting.economic_calendar.closing_nowcast_value IS '발표 전 마지막 나우캐스트(GDPNow 등).';
COMMENT ON COLUMN reporting.economic_calendar.closing_own_model_value IS '발표 전 마지막 자체 모델 예상.';
COMMENT ON COLUMN reporting.economic_calendar.latest_actual_value IS '개정이 반영된 현재 값.';
COMMENT ON COLUMN reporting.economic_calendar.revision IS '현재 값 - 최초 발표 값.';
COMMENT ON COLUMN reporting.economic_calendar.series_id IS '지표 코드.';
COMMENT ON COLUMN reporting.economic_calendar.measure_id IS '비교 단위 ID.';

CREATE OR REPLACE VIEW reporting.institutional_holdings WITH (security_invoker = true) AS
SELECT
  f.manager_cik,
  f.period_end,
  f.filing_date,
  f.form_type,
  p.ticker,
  p.issuer_name,
  p.cusip,
  p.value_usd,
  p.quantity,
  p.quantity_type,
  p.position_kind,
  (p.security_id IS NOT NULL) AS is_security_mapped,
  p.accession_no,
  p.security_id
FROM reporting.institutional_positions p
JOIN institutional.filings f ON f.accession_no = p.accession_no;
COMMENT ON VIEW reporting.institutional_holdings IS '[6. 기관 보유] 13F 보유 줄 하나 = 한 행. 종목 연결은 보고 분기말 기준이며 연결되지 않은 줄도 남긴다.';
COMMENT ON COLUMN reporting.institutional_holdings.manager_cik IS '보고 운용사 CIK.';
COMMENT ON COLUMN reporting.institutional_holdings.period_end IS '보고 분기말.';
COMMENT ON COLUMN reporting.institutional_holdings.filing_date IS '제출일.';
COMMENT ON COLUMN reporting.institutional_holdings.form_type IS '13F-HR 또는 정정 13F-HR/A.';
COMMENT ON COLUMN reporting.institutional_holdings.ticker IS '분기말 기준으로 연결된 종목의 현재 티커. 연결 없으면 NULL.';
COMMENT ON COLUMN reporting.institutional_holdings.issuer_name IS '원문 발행사명.';
COMMENT ON COLUMN reporting.institutional_holdings.cusip IS '원문 CUSIP/CINS.';
COMMENT ON COLUMN reporting.institutional_holdings.value_usd IS '보유 가치(USD, 원문 표 기준).';
COMMENT ON COLUMN reporting.institutional_holdings.quantity IS '보유 수량.';
COMMENT ON COLUMN reporting.institutional_holdings.quantity_type IS 'SH=주식, PRN=채권 원금.';
COMMENT ON COLUMN reporting.institutional_holdings.position_kind IS 'SHARES=현물, PUT/CALL=옵션.';
COMMENT ON COLUMN reporting.institutional_holdings.is_security_mapped IS '종목에 연결됐는가.';
COMMENT ON COLUMN reporting.institutional_holdings.accession_no IS '13F 접수번호.';
COMMENT ON COLUMN reporting.institutional_holdings.security_id IS '연결된 내부 종목 ID.';


GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO service_role;
