-- macro — 시장 관측은 canonical 값 하나, 경제 발표만 full vintage를 보존한다.

CREATE SCHEMA IF NOT EXISTS macro;
REVOKE ALL ON SCHEMA macro FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA macro TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA macro REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA macro GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA macro GRANT SELECT ON TABLES TO anon, authenticated;

CREATE TABLE IF NOT EXISTS macro.series (
  series_key smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  series_code text NOT NULL UNIQUE CHECK (series_code ~ '^[A-Z][A-Z0-9_]*$'),
  domain text NOT NULL CHECK (domain IN ('market_indicator', 'economic_release')),
  name_ko text NOT NULL CHECK (btrim(name_ko) <> ''),
  description text,
  -- 원천 이름은 그 자체가 값이다. 십수 개짜리 목록을 위해 표를 하나 더 두면
  -- 읽는 곳마다 join이 붙고, 그 join이 reporting view 여섯 곳을 차지했다.
  source_code text NOT NULL CHECK (source_code = btrim(source_code)
              AND length(source_code) BETWEEN 1 AND 120),
  provider_series_code text,
  frequency text NOT NULL CHECK (frequency IN ('daily','weekly','monthly','quarterly','irregular')),
  unit text NOT NULL CHECK (btrim(unit) <> ''),
  category text,
  country text CHECK (country IS NULL OR country IN ('US','KR')),
  series_kind text CHECK (series_kind IS NULL OR series_kind IN ('price','fx','rate','spread','oscillator','flow','valuation','ratio')),
  timezone text,
  CHECK ((domain = 'market_indicator' AND series_kind IS NOT NULL)
      OR (domain = 'economic_release' AND timezone IS NOT NULL AND country IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS series_domain_idx ON macro.series (domain);

CREATE TABLE IF NOT EXISTS macro.measures (
  measure_id text PRIMARY KEY,
  series_key smallint NOT NULL REFERENCES macro.series(series_key) ON DELETE CASCADE,
  name_ko text NOT NULL,
  unit text NOT NULL,
  transform text NOT NULL CHECK (transform IN ('level','change_1','change_4','change_previous','pct_change_1','pct_change_12')),
  decimal_places smallint NOT NULL CHECK (decimal_places BETWEEN 0 AND 6),
  is_primary boolean NOT NULL DEFAULT false,
  rollup_method text NOT NULL DEFAULT 'none' CHECK (rollup_method IN ('none','last','average','sum'))
);
CREATE UNIQUE INDEX IF NOT EXISTS measures_one_primary_per_series_idx ON macro.measures (series_key) WHERE is_primary;

CREATE TABLE IF NOT EXISTS macro.market_observations (
  series_key smallint NOT NULL REFERENCES macro.series(series_key) ON DELETE CASCADE,
  observation_date date NOT NULL,
  value double precision NOT NULL CHECK (value > '-Infinity'::float8 AND value < 'Infinity'::float8),
  PRIMARY KEY (series_key, observation_date)
);
CREATE INDEX IF NOT EXISTS market_observations_date_idx ON macro.market_observations (observation_date, series_key);

CREATE TABLE IF NOT EXISTS macro.economic_observations (
  series_key smallint NOT NULL REFERENCES macro.series(series_key) ON DELETE CASCADE,
  observation_date date NOT NULL,
  vintage_at timestamptz NOT NULL,
  available_at timestamptz NOT NULL,
  value double precision NOT NULL CHECK (value > '-Infinity'::float8 AND value < 'Infinity'::float8),
  revision_no smallint NOT NULL DEFAULT 0 CHECK (revision_no >= 0),
  time_precision text NOT NULL DEFAULT 'collector_seen' CHECK (time_precision IN ('exact','date_only','collector_seen')),
  source_code text NOT NULL CHECK (btrim(source_code) <> ''),
  PRIMARY KEY (series_key, observation_date, vintage_at, available_at)
);
CREATE INDEX IF NOT EXISTS economic_observations_asof_idx
  ON macro.economic_observations (series_key, observation_date, available_at DESC);

CREATE TABLE IF NOT EXISTS macro.release_events (
  series_key smallint NOT NULL REFERENCES macro.series(series_key) ON DELETE CASCADE,
  ref_period date NOT NULL,
  source_code text NOT NULL CHECK (btrim(source_code) <> ''),
  PRIMARY KEY (series_key, ref_period)
);

CREATE TABLE IF NOT EXISTS macro.release_schedule_versions (
  series_key smallint NOT NULL REFERENCES macro.series(series_key) ON DELETE CASCADE,
  ref_period date NOT NULL,
  scheduled_at timestamptz NOT NULL,
  collected_at timestamptz NOT NULL,
  -- 도메인이 정확도별 watcher 창을 선언한다(`domain/releases/schedule.py:schedule_window`).
  -- 그 목록과 여기가 어긋나면 그 정확도를 쓰는 지표의 일정 적재가 통째로 죽는다 —
  -- 실측으로 `rule`(공표된 규칙에서 날짜를 유도)이 빠져 있어 econ 백필이 크래시했다.
  schedule_precision text NOT NULL
    CHECK (schedule_precision IN ('exact','rule','date_only','estimated')),
  source_code text NOT NULL CHECK (btrim(source_code) <> ''),
  is_cancelled boolean NOT NULL DEFAULT false,
  PRIMARY KEY (series_key, ref_period, collected_at)
);

CREATE TABLE IF NOT EXISTS macro.forecast_snapshots (
  series_key smallint NOT NULL REFERENCES macro.series(series_key) ON DELETE CASCADE,
  ref_period date NOT NULL,
  measure_id text REFERENCES macro.measures(measure_id) ON DELETE RESTRICT,
  forecast_kind text NOT NULL CHECK (forecast_kind IN ('survey','nowcast','own_model')),
  source_code text NOT NULL CHECK (btrim(source_code) <> ''),
  value double precision CHECK (value > '-Infinity'::float8 AND value < 'Infinity'::float8),
  effective_at timestamptz NOT NULL,
  collected_at timestamptz NOT NULL,
  time_precision text NOT NULL DEFAULT 'collector_seen' CHECK (time_precision IN ('exact','date_only','collector_seen')),
  PRIMARY KEY (series_key, ref_period, measure_id, forecast_kind, source_code, effective_at, collected_at)
);

ALTER TABLE macro.series ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro.measures ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro.market_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro.economic_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro.release_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro.release_schedule_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro.forecast_snapshots ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS series_read ON macro.series;
DROP POLICY IF EXISTS measures_read ON macro.measures;
DROP POLICY IF EXISTS market_observations_read ON macro.market_observations;
DROP POLICY IF EXISTS economic_observations_read ON macro.economic_observations;
DROP POLICY IF EXISTS release_events_read ON macro.release_events;
DROP POLICY IF EXISTS release_schedule_versions_read ON macro.release_schedule_versions;
DROP POLICY IF EXISTS forecast_snapshots_read ON macro.forecast_snapshots;
CREATE POLICY series_read ON macro.series FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY measures_read ON macro.measures FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY market_observations_read ON macro.market_observations FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY economic_observations_read ON macro.economic_observations FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY release_events_read ON macro.release_events FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY release_schedule_versions_read ON macro.release_schedule_versions FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY forecast_snapshots_read ON macro.forecast_snapshots FOR SELECT TO anon, authenticated USING (true);


-- ── 발표가 끝난 뒤의 일정·예상 스냅샷 정리 ────────────────────────────────
-- fundamentals와 같은 기준이다. 발표 전에는 일정 변경과 예상 변동 자체가 신호지만,
-- 발표가 끝나면 `reporting.macro_release_summary`가 쓰는 것은 둘뿐이다 —
-- 확정된 마지막 일정, 그리고 실제치가 나오기 직전의 예상(closing).
--
-- 그래서 실제치가 있는 ref_period만, 그것도 `p_recent_days` 밖의 것만 줄인다.
CREATE OR REPLACE FUNCTION macro.prune_release_snapshots(p_recent_days int DEFAULT 180)
RETURNS TABLE (schedules_deleted bigint, forecasts_deleted bigint)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE
  cutoff timestamptz;
  sch bigint; fc bigint;
BEGIN
  IF p_recent_days IS NULL OR p_recent_days < 1 THEN
    RAISE EXCEPTION 'p_recent_days must be at least 1';
  END IF;
  cutoff := pg_catalog.now() - make_interval(days => p_recent_days);

  -- 실제치가 처음 나온 시각. closing 예상을 가르는 경계다.
  CREATE TEMP TABLE released_period ON COMMIT DROP AS
  SELECT o.series_key, o.observation_date AS ref_period, min(o.available_at) AS first_actual_at
  FROM macro.economic_observations o
  GROUP BY o.series_key, o.observation_date;

  WITH removed AS (
    DELETE FROM macro.release_schedule_versions v
    USING released_period rp
    WHERE rp.series_key = v.series_key
      AND rp.ref_period = v.ref_period
      AND v.collected_at < cutoff
      AND v.collected_at < (
        SELECT max(latest.collected_at)
        FROM macro.release_schedule_versions latest
        WHERE latest.series_key = v.series_key AND latest.ref_period = v.ref_period
      )
    RETURNING 1
  ) SELECT count(*) INTO sch FROM removed;

  -- 실제치 직전 마지막 예상. 이것이 사라지면 "예상 대비"를 계산할 기준이 없어진다.
  CREATE TEMP TABLE forecast_keeper ON COMMIT DROP AS
  SELECT DISTINCT ON (f.series_key, f.ref_period, f.measure_id, f.forecast_kind, f.source_code)
         f.series_key, f.ref_period, f.measure_id, f.forecast_kind, f.source_code,
         f.effective_at, f.collected_at
  FROM macro.forecast_snapshots f
  JOIN released_period rp ON rp.series_key = f.series_key AND rp.ref_period = f.ref_period
  WHERE f.collected_at <= rp.first_actual_at
  ORDER BY f.series_key, f.ref_period, f.measure_id, f.forecast_kind, f.source_code,
           f.effective_at DESC, f.collected_at DESC;

  WITH removed AS (
    DELETE FROM macro.forecast_snapshots f
    USING released_period rp
    WHERE rp.series_key = f.series_key
      AND rp.ref_period = f.ref_period
      AND f.collected_at < cutoff
      AND NOT EXISTS (
        SELECT 1 FROM forecast_keeper k
        WHERE k.series_key = f.series_key
          AND k.ref_period = f.ref_period
          AND k.measure_id IS NOT DISTINCT FROM f.measure_id
          AND k.forecast_kind = f.forecast_kind
          AND k.source_code = f.source_code
          AND k.effective_at = f.effective_at
          AND k.collected_at = f.collected_at
      )
    RETURNING 1
  ) SELECT count(*) INTO fc FROM removed;

  RETURN QUERY SELECT sch, fc;
END $fn$;

REVOKE ALL ON FUNCTION macro.prune_release_snapshots(int) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION macro.prune_release_snapshots(int) TO service_role;
