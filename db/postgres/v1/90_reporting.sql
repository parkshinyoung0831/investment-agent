-- reporting — canonical 금융 사실만 조합하는 읽기 전용 view.
-- 실행·알림·대용량 분석은 각각 local SQLite와 Parquet/DuckDB reader가 조합한다.

CREATE SCHEMA IF NOT EXISTS reporting;

REVOKE ALL ON SCHEMA reporting FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA reporting TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA reporting
  REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA reporting GRANT SELECT ON TABLES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA reporting GRANT ALL ON TABLES TO service_role;

CREATE OR REPLACE VIEW reporting.institutional_filings WITH (security_invoker = true) AS
SELECT f.accession_no, f.manager_cik, f.period_end, f.form_type, f.report_type, f.filing_date, f.accepted_at,
       f.amendment_type, f.amendment_no, f.reported_value_usd, f.reported_line_count,
       f.confidential_omitted, f.source_url, f.content_sha256
FROM institutional.filings f;

CREATE OR REPLACE VIEW reporting.institutional_positions WITH (security_invoker = true) AS
SELECT p.accession_no, p.source_row_no, p.issuer_name, p.identifier AS cusip,
       p.identifier_type, p.value_usd, p.quantity, p.quantity_type,
       p.position_kind, s.ticker
FROM institutional.positions p
JOIN institutional.filings f ON f.accession_no = p.accession_no
LEFT JOIN LATERAL (
  SELECT i.security_id FROM universe.security_identifiers i
  WHERE i.identifier = lower(p.identifier) AND i.identifier_type = lower(p.identifier_type)
    AND i.valid_from <= f.period_end
    AND (i.valid_to IS NULL OR f.period_end < i.valid_to)
  ORDER BY i.valid_from DESC LIMIT 1
) i ON true
LEFT JOIN universe.securities s ON s.security_id = i.security_id;

CREATE OR REPLACE VIEW reporting.securities WITH (security_invoker = true) AS
SELECT
  s.ticker,
  e.company_name,
  e.company_name_ko,
  -- SIC는 GICS 섹터가 아니다. 이름으로 그것을 분명히 한다.
  e.sic_industry_name,
  e.sic_division_name,
  s.exchange_code,
  s.security_type,
  s.is_active_listing,
  s.is_tracked,
  -- 관심 기업은 기업 단위 사실이라 entities가 소유한다. 추적(S&P 500) 여부와
  -- 다른 개념이므로 둘 다 내보낸다 — 하나로 접으면 화면이 tracked를 관심으로
  -- 잘못 읽는다.
  COALESCE(e.is_watchlisted, false) AS is_watchlisted,
  COALESCE(e.watchlist_sources, ARRAY[]::text[]) AS watchlist_sources,
  e.watch_from
FROM universe.securities s
LEFT JOIN universe.entities e ON e.cik = s.cik;

CREATE OR REPLACE VIEW reporting.prices_daily WITH (security_invoker = true) AS
SELECT
  s.ticker,
  p.trade_date,
  p.open, p.high, p.low, p.close, p.volume,
  p.is_repaired
FROM market.prices_daily p
JOIN universe.securities s ON s.security_id = p.security_id;

CREATE OR REPLACE VIEW reporting.company_financials_latest WITH (security_invoker = true) AS
SELECT
  fv.cik,
  fv.period_end,
  fv.fiscal_year,
  fv.fiscal_period,
  fv.source_accession_no AS accession_no,
  f.filing_date,
  f.form_type,
  f.available_at,
  fv.revenue,
  fv.operating_income_loss,
  fv.net_income,
  fv.eps_diluted_gaap,
  fv.mapping_version
FROM fundamentals.financials fv
JOIN fundamentals.filings f ON f.accession_no = fv.source_accession_no;

CREATE OR REPLACE VIEW reporting.earnings_schedule WITH (security_invoker = true) AS
SELECT DISTINCT ON (v.security_id, v.target_fiscal_year, v.target_fiscal_period)
  s.ticker,
  v.target_fiscal_year,
  v.target_fiscal_period,
  v.target_period_end,
  v.expected_report_at,
  v.expected_report_date,
  v.expected_session,
  v.is_estimated,
  v.snapshot_date,
  -- 직전 관측의 예정 시각. 같으면 안 밀린 것이다.
  lag(v.expected_report_at) OVER (
    PARTITION BY v.security_id, v.target_fiscal_year, v.target_fiscal_period
    ORDER BY v.snapshot_date
  ) AS previous_report_at
FROM fundamentals.earnings_schedule_versions v
JOIN universe.securities s ON s.security_id = v.security_id
ORDER BY v.security_id, v.target_fiscal_year, v.target_fiscal_period, v.snapshot_date DESC;

CREATE OR REPLACE VIEW reporting.earnings_surprise WITH (security_invoker = true) AS
SELECT
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
  e.eps_avg      AS eps_estimate,
  e.revenue_avg  AS revenue_estimate,
  e.snapshot_date AS estimate_snapshot_date,
  e.eps_analysts,
  -- 0으로 나누는 자리를 막는다. 컨센서스가 0인 종목이 실제로 있다.
  CASE WHEN e.eps_avg IS NOT NULL AND e.eps_avg <> 0
       THEN (r.eps_actual - e.eps_avg) / abs(e.eps_avg) END AS eps_surprise_pct,
  CASE WHEN e.revenue_avg IS NOT NULL AND e.revenue_avg <> 0
       THEN (r.revenue_actual - e.revenue_avg) / abs(e.revenue_avg) END AS revenue_surprise_pct,
  r.guidance_summary,
  r.operating_income_actual,
  r.net_income_actual,
  r.press_release_url
FROM fundamentals.earnings_results r
JOIN fundamentals.filings f ON f.accession_no = r.accession_no
JOIN universe.securities s ON s.cik = r.cik AND s.is_active_listing
LEFT JOIN LATERAL (
  SELECT est.eps_avg, est.revenue_avg, est.snapshot_date, est.eps_analysts
  FROM fundamentals.earnings_estimates est
  WHERE est.security_id = s.security_id
    AND est.target_fiscal_year = r.fiscal_year
    AND est.target_fiscal_period = r.fiscal_period
    AND est.snapshot_date < f.filing_date
  ORDER BY est.snapshot_date DESC
  LIMIT 1
) e ON true;

CREATE OR REPLACE VIEW reporting.macro_observation_history WITH (security_invoker = true) AS
SELECT s.series_code AS series_id, o.observation_date AS ref_period, o.value,
       (o.observation_date + time '23:59:59.999999') AT TIME ZONE 'UTC' AS effective_at,
       NULL::timestamptz AS collected_at, 'date_only'::text AS time_precision, s.source_code
FROM macro.market_observations o JOIN macro.series s USING(series_key)
UNION ALL
SELECT s.series_code, o.observation_date, o.value, o.vintage_at, o.available_at,
       o.time_precision, o.source_code
FROM macro.economic_observations o JOIN macro.series s USING(series_key);

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
ORDER BY o.series_id, o.ref_period DESC, o.effective_at DESC, o.collected_at DESC;

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

CREATE OR REPLACE VIEW reporting.macro_observations WITH (security_invoker = true) AS
SELECT DISTINCT ON (o.series_id, o.ref_period)
  o.series_id,
  o.ref_period AS obs_date,
  o.value,
  o.effective_at,
  o.collected_at
FROM reporting.macro_observation_history o
ORDER BY o.series_id, o.ref_period, o.effective_at DESC, o.collected_at DESC;

CREATE OR REPLACE VIEW reporting.macro_release_summary WITH (security_invoker = true) AS
SELECT
  s.series_code || ':' || e.ref_period::text AS event_key,
  s.series_code AS series_id,
  s.name_ko AS series_name_ko,
  s.country,
  s.category,
  s.frequency,
  s.timezone,
  e.ref_period,
  schedule.scheduled_at,
  schedule.source AS schedule_source,
  schedule.schedule_precision AS schedule_confidence,
  CASE
    WHEN schedule.is_cancelled THEN 'cancelled'
    WHEN latest_actual.value IS NOT NULL THEN 'released'
    WHEN schedule.scheduled_at <= now() THEN 'not_available_yet'
    ELSE 'scheduled'
  END AS status,
  first_actual.effective_at AS first_actual_at,
  first_actual.time_precision AS first_actual_precision,
  m.measure_id,
  split_part(m.measure_id, '.', 2) AS measure_code,
  m.name_ko AS measure_name_ko,
  m.unit,
  m.decimal_places,
  NULL::boolean AS is_surprise_eligible,
  first_actual.value AS first_actual_value,
  latest_actual.value AS latest_actual_value,
  latest_actual.effective_at AS latest_actual_effective_at,
  current_survey.value AS survey_value,
  current_nowcast.value AS nowcast_value,
  current_model.value AS own_model_value,
  closing_survey.value AS closing_survey_value,
  closing_nowcast.value AS closing_nowcast_value,
  closing_model.value AS closing_own_model_value,
  CASE WHEN latest_actual.value IS NOT NULL AND closing_survey.value IS NOT NULL
       THEN latest_actual.value - closing_survey.value END AS market_surprise,
  CASE WHEN latest_actual.value IS NOT NULL AND closing_nowcast.value IS NOT NULL
       THEN latest_actual.value - closing_nowcast.value END AS nowcast_error,
  CASE WHEN latest_actual.value IS NOT NULL AND closing_model.value IS NOT NULL
       THEN latest_actual.value - closing_model.value END AS model_error,
  CASE WHEN latest_actual.value IS NOT NULL AND first_actual.value IS NOT NULL
       THEN latest_actual.value - first_actual.value END AS revision
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
  SELECT o.value, o.effective_at, o.collected_at, o.time_precision
  FROM reporting.macro_observation_history o
  WHERE o.series_id = s.series_code AND o.ref_period = e.ref_period
  ORDER BY o.effective_at, o.collected_at
  LIMIT 1
) first_actual ON true
LEFT JOIN LATERAL (
  SELECT o.value, o.effective_at
  FROM reporting.macro_observation_history o
  WHERE o.series_id = s.series_code AND o.ref_period = e.ref_period
  ORDER BY o.effective_at DESC, o.collected_at DESC
  LIMIT 1
) latest_actual ON true
LEFT JOIN LATERAL (
  SELECT fv.value
  FROM macro.forecast_snapshots fv
  WHERE fv.series_key = e.series_key AND fv.ref_period = e.ref_period
    AND fv.measure_id = m.measure_id AND fv.forecast_kind = 'survey'
  ORDER BY fv.effective_at DESC, fv.collected_at DESC, fv.source_code
  LIMIT 1
) current_survey ON true
LEFT JOIN LATERAL (
  SELECT fv.value
  FROM macro.forecast_snapshots fv
  WHERE fv.series_key = e.series_key AND fv.ref_period = e.ref_period
    AND fv.measure_id = m.measure_id AND fv.forecast_kind = 'nowcast'
  ORDER BY fv.effective_at DESC, fv.collected_at DESC, fv.source_code
  LIMIT 1
) current_nowcast ON true
LEFT JOIN LATERAL (
  SELECT fv.value
  FROM macro.forecast_snapshots fv
  WHERE fv.series_key = e.series_key AND fv.ref_period = e.ref_period
    AND fv.measure_id = m.measure_id AND fv.forecast_kind = 'own_model'
  ORDER BY fv.effective_at DESC, fv.collected_at DESC, fv.source_code
  LIMIT 1
) current_model ON true
LEFT JOIN LATERAL (
  SELECT fv.value
  FROM macro.forecast_snapshots fv
  WHERE fv.series_key = e.series_key AND fv.ref_period = e.ref_period
    AND fv.measure_id = m.measure_id AND fv.forecast_kind = 'survey'
    AND (first_actual.collected_at IS NULL OR fv.collected_at <= first_actual.collected_at)
  ORDER BY fv.effective_at DESC, fv.collected_at DESC, fv.source_code
  LIMIT 1
) closing_survey ON true
LEFT JOIN LATERAL (
  SELECT fv.value
  FROM macro.forecast_snapshots fv
  WHERE fv.series_key = e.series_key AND fv.ref_period = e.ref_period
    AND fv.measure_id = m.measure_id AND fv.forecast_kind = 'nowcast'
    AND (first_actual.collected_at IS NULL OR fv.collected_at <= first_actual.collected_at)
  ORDER BY fv.effective_at DESC, fv.collected_at DESC, fv.source_code
  LIMIT 1
) closing_nowcast ON true
LEFT JOIN LATERAL (
  SELECT fv.value
  FROM macro.forecast_snapshots fv
  WHERE fv.series_key = e.series_key AND fv.ref_period = e.ref_period
    AND fv.measure_id = m.measure_id AND fv.forecast_kind = 'own_model'
    AND (first_actual.collected_at IS NULL OR fv.collected_at <= first_actual.collected_at)
  ORDER BY fv.effective_at DESC, fv.collected_at DESC, fv.source_code
  LIMIT 1
) closing_model ON true;

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

CREATE OR REPLACE VIEW reporting.macro_release_actuals WITH (security_invoker = true) AS
SELECT
  o.series_id,
  o.ref_period,
  m.measure_id,
  o.value,
  o.effective_at,
  o.collected_at,
  o.time_precision,
  o.source_code AS source
FROM reporting.macro_observation_history o
JOIN macro.series s ON s.series_code = o.series_id
JOIN macro.measures m ON m.series_key = s.series_key AND m.is_primary;

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

GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO anon, authenticated, service_role;
