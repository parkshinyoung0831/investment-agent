-- reporting — 사실 스키마를 조합하는 읽기 전용 뷰.
--
-- 주제마다 뷰 하나를 둔다. 코드 계약 뷰는 화면·알림·AI evidence·prompts가
-- `reporting/readers/financial.py`의 VIEWS 선언 그대로 읽는다 — 컬럼을 바꾸면 그 선언도 함께
-- 바꾼다. 같은 주제를 사람용으로 한 번 더 감싼 뷰는 두지 않는다(두 벌이 서로 다른 뜻으로
-- 흘러간다). 계약 뷰가 없는 주제(실적 예상)만 사람이 여는 뷰로 둔다.
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
  fl.filing_date,
  fl.form_type,
  fl.available_at,
  f.revenue,
  f.operating_income_loss,
  f.net_income,
  f.eps_diluted_gaap
FROM fundamentals.financials f
JOIN fundamentals.filings fl ON fl.accession_no = f.accession_no;
COMMENT ON VIEW reporting.company_financials_latest IS '회사·회계 분기마다 지금 알고 있는 핵심 재무 한 행. filing_date는 값을 마지막으로 반영한 공시(정정이면 /A)의 날짜다. PIT 조회에 쓰지 않는다.';

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
--   * 대상 예상: captured_live(직접 수집)·vendor_pit(당시 값 보장)를 먼저 쓴다.
--     발표 전: 공시일보다 앞선 상태, 또는 공시일 당일에 공시를 손에 넣기 전에 수집한 상태.
--   * 그런 예상이 없는 과거 발표만 reconstructed(공급자 발표 이력의 그 분기 예상)로 채운다.
--     당시 값이라는 보장이 없으므로 estimate_kind로 드러내고, 발표일 허용 오차(3일)를
--     넘겨 만든 상태는 쓰지 않는다. latest_history는 어느 발표의 예상인지 몰라 쓰지 않는다.
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
-- 회사 실적은 보통주에만 붙인다. 같은 CIK의 우선주·채권·워런트는 다른 증권이다.
JOIN universe.securities s ON s.cik = r.cik AND s.is_active_listing AND s.security_type = 'common_stock'
LEFT JOIN LATERAL (
  SELECT est.security_id, est.eps_avg, est.revenue_avg, est.eps_basis, est.snapshot_kind,
         est.snapshot_date, est.collected_at, est.eps_analysts
  FROM fundamentals.earnings_estimates est
  WHERE est.security_id = s.security_id
    AND est.target_fiscal_year = r.fiscal_year
    AND est.target_fiscal_period = r.fiscal_period
    AND (
      (est.snapshot_kind IN ('captured_live', 'vendor_pit')
       AND (est.snapshot_date < f.filing_date
            OR (est.snapshot_date = f.filing_date AND est.collected_at < f.available_at)))
      OR (est.snapshot_kind = 'reconstructed' AND est.snapshot_date <= f.filing_date + 3)
    )
  ORDER BY CASE est.snapshot_kind WHEN 'reconstructed' THEN 1 ELSE 0 END,
           est.snapshot_date DESC, est.collected_at DESC,
           CASE est.snapshot_kind WHEN 'captured_live' THEN 0 ELSE 1 END
  LIMIT 1
) e ON true
-- 같은 분기를 알린 8-K가 여럿이면(재발행·보충 자료) 시장이 처음 받은 발표 하나만 쓴다.
WHERE NOT EXISTS (
  SELECT 1
  FROM fundamentals.earnings_results r2
  JOIN fundamentals.filings f2 ON f2.accession_no = r2.accession_no
  WHERE r2.cik = r.cik AND r2.fiscal_year = r.fiscal_year AND r2.fiscal_period = r.fiscal_period
    AND (f2.filing_date, r2.accession_no) < (f.filing_date, r.accession_no)
);
COMMENT ON VIEW reporting.earnings_surprise IS '회계기간마다 첫 실적 발표(8-K) 하나·상장 종목 하나 = 한 행. 발표 전에 수집한 컨센서스를 먼저 쓰고, 없으면 공급자 발표 이력 재구성값(estimate_kind=reconstructed)으로 채운다. *_surprise_ratio는 분수(0.05=+5%).';

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
COMMENT ON VIEW reporting.earnings_outlook IS '[실적 예상] 수집 중인 종목마다 아직 발표되지 않은 가장 가까운 분기의 현재 컨센서스와 발표 예정 한 행.';
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

GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO service_role;
