-- macro — 지표 정의, 시장 지표의 현재 값, 경제 발표의 빈티지·일정·예상.
--
-- 시장 지표(금리·지수·스프레드)는 날짜마다 현재 정정 기준 값 하나만 둔다. 경제 발표(CPI·
-- 고용 등)는 같은 기간 값이 발표·개정마다 달라지므로 빈티지를 전부 남긴다.
--
-- ## raw와 measure를 섞지 않는다
--
-- series는 원천이 주는 원값(CPI 지수 334.131)의 정의이고, measure는 그 원값에서 계산한 비교
-- 단위(CPI 전월비 %)다. 예상치는 measure 단위로 오므로 실제치도 같은 measure로 바꾼 뒤에만
-- 비교한다. 변환 규칙은 `macro.measure_value`가 코드(`domain/releases/normalize.py`)와 같은
-- 규칙으로 계산한다 — 변환한 값을 표에 저장하지 않는다.

CREATE SCHEMA IF NOT EXISTS macro;

REVOKE ALL ON SCHEMA macro FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA macro TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA macro REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA macro GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA macro GRANT USAGE, SELECT ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA macro REVOKE ALL ON FUNCTIONS FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA macro GRANT EXECUTE ON FUNCTIONS TO service_role;


-- ── 지표 정의 ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS macro.series (
  series_key smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  series_code text NOT NULL UNIQUE CHECK (series_code ~ '^[A-Z][A-Z0-9_]*$'),
  domain text NOT NULL CHECK (domain IN ('market_indicator', 'economic_release')),
  name_ko text NOT NULL CHECK (btrim(name_ko) <> ''),
  description text,
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

COMMENT ON TABLE macro.series IS '원천 지표 하나의 정의 = 한 행. 값의 단위는 원천이 주는 원값(raw) 기준이다.';
COMMENT ON COLUMN macro.series.series_key IS '내부 키(작은 정수). 관측 표가 참조한다.';
COMMENT ON COLUMN macro.series.series_code IS '사람이 부르는 지표 코드(US_CPI, VIX 등). 코드 catalog와 같다.';
COMMENT ON COLUMN macro.series.domain IS 'market_indicator=날짜별 시장 값, economic_release=기간별 발표·개정이 있는 경제지표.';
COMMENT ON COLUMN macro.series.name_ko IS '한국어 지표명.';
COMMENT ON COLUMN macro.series.description IS '지표 설명(계절조정·정의 등).';
COMMENT ON COLUMN macro.series.source_code IS '원천 이름(FRED, ECOS, BLS 등).';
COMMENT ON COLUMN macro.series.provider_series_code IS '원천 API의 시리즈 코드(예: FRED CPIAUCSL).';
COMMENT ON COLUMN macro.series.frequency IS '관측 주기.';
COMMENT ON COLUMN macro.series.unit IS '원값 단위(지수, %, 천 명 등).';
COMMENT ON COLUMN macro.series.category IS '화면 묶음(물가·고용 등).';
COMMENT ON COLUMN macro.series.country IS '국가(US/KR). 시장 지표는 NULL일 수 있다.';
COMMENT ON COLUMN macro.series.series_kind IS '시장 지표의 성격(price·rate·spread 등). 경제지표는 NULL.';
COMMENT ON COLUMN macro.series.timezone IS '발표 시각의 기준 시간대(경제지표).';


CREATE TABLE IF NOT EXISTS macro.measures (
  measure_id text PRIMARY KEY,
  series_key smallint NOT NULL REFERENCES macro.series(series_key) ON DELETE CASCADE,
  name_ko text NOT NULL,
  unit text NOT NULL,
  transform text NOT NULL CHECK (transform IN ('level','change_1','change_4','change_previous','pct_change_1','pct_change_12')),
  decimal_places smallint NOT NULL CHECK (decimal_places BETWEEN 0 AND 6),
  is_primary boolean NOT NULL DEFAULT false,
  rollup_method text NOT NULL DEFAULT 'none' CHECK (rollup_method IN ('none','last','average','sum')),
  CONSTRAINT measures_series_measure_key UNIQUE (series_key, measure_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS measures_one_primary_per_series_idx ON macro.measures (series_key) WHERE is_primary;

COMMENT ON TABLE macro.measures IS '원값에서 계산하는 비교 단위 하나 = 한 행(US_CPI.MOM 등). 예상과 실제는 같은 measure에서만 비교한다.';
COMMENT ON COLUMN macro.measures.measure_id IS '"<series_code>.<measure>" 형식 ID.';
COMMENT ON COLUMN macro.measures.series_key IS '계산 원천 지표.';
COMMENT ON COLUMN macro.measures.name_ko IS '한국어 이름(전월비 등).';
COMMENT ON COLUMN macro.measures.unit IS '계산 결과 단위(%, %p, 천 명 등).';
COMMENT ON COLUMN macro.measures.transform IS 'level=원값, change_1/4=1·4기간 전 대비 차이, change_previous=직전 관측 대비 차이, pct_change_1/12=1·12기간 전 대비 변화율(%). 월·분기는 달력 기준, 주간은 7일 단위.';
COMMENT ON COLUMN macro.measures.decimal_places IS '표시 소수 자릿수.';
COMMENT ON COLUMN macro.measures.is_primary IS '지표의 대표 비교 단위인가(지표당 하나).';
COMMENT ON COLUMN macro.measures.rollup_method IS '더 긴 주기로 묶을 때의 방법.';


-- ── 시장 지표 값 ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS macro.market_observations (
  series_key smallint NOT NULL REFERENCES macro.series(series_key) ON DELETE CASCADE,
  observation_date date NOT NULL,
  value double precision NOT NULL CHECK (value > '-Infinity'::float8 AND value < 'Infinity'::float8),
  PRIMARY KEY (series_key, observation_date)
);
CREATE INDEX IF NOT EXISTS market_observations_date_idx ON macro.market_observations (observation_date, series_key);

COMMENT ON TABLE macro.market_observations IS '시장 지표 하나의 날짜 하나 값 = 한 행. 원천의 현재 정정 기준 값 하나만 둔다.';
COMMENT ON COLUMN macro.market_observations.series_key IS '지표.';
COMMENT ON COLUMN macro.market_observations.observation_date IS '값이 해당하는 날짜(원천 기준 거래일).';
COMMENT ON COLUMN macro.market_observations.value IS '값(series.unit 단위).';


-- ── 경제 발표 빈티지 ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS macro.economic_observations (
  series_key smallint NOT NULL REFERENCES macro.series(series_key) ON DELETE CASCADE,
  observation_date date NOT NULL,
  vintage_at timestamptz NOT NULL,
  available_at timestamptz NOT NULL,
  value double precision NOT NULL CHECK (value > '-Infinity'::float8 AND value < 'Infinity'::float8),
  time_precision text NOT NULL DEFAULT 'collector_seen' CHECK (time_precision IN ('exact','date_only','collector_seen')),
  source_code text NOT NULL CHECK (btrim(source_code) <> ''),
  PRIMARY KEY (series_key, observation_date, vintage_at, available_at)
);
CREATE INDEX IF NOT EXISTS economic_observations_asof_idx
  ON macro.economic_observations (series_key, observation_date, vintage_at DESC);

COMMENT ON TABLE macro.economic_observations IS '경제지표 하나의 대상 기간 하나를 특정 빈티지(발표·개정)에서 본 원값 = 한 행. 최초 발표와 개정을 덮어쓰지 않는다.';
COMMENT ON COLUMN macro.economic_observations.series_key IS '지표.';
COMMENT ON COLUMN macro.economic_observations.observation_date IS '값이 설명하는 대상 기간의 시작일(월간=1일).';
COMMENT ON COLUMN macro.economic_observations.vintage_at IS '원천이 말하는 이 값의 공개 시점(ALFRED 빈티지·발표 시각). 정밀도는 time_precision.';
COMMENT ON COLUMN macro.economic_observations.available_at IS '우리 수집기가 이 값을 처음 본 시각. 과거 빈티지 백필은 백필 시각이다.';
COMMENT ON COLUMN macro.economic_observations.value IS '원값(series.unit 단위). measure 단위가 아니다.';
COMMENT ON COLUMN macro.economic_observations.time_precision IS 'exact=발표 시각까지 확인, date_only=날짜만 확인, collector_seen=수집 시각으로만 안다.';
COMMENT ON COLUMN macro.economic_observations.source_code IS '값을 알려 준 원천.';


-- ── 발표 이벤트와 일정 ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS macro.release_events (
  series_key smallint NOT NULL REFERENCES macro.series(series_key) ON DELETE CASCADE,
  ref_period date NOT NULL,
  source_code text NOT NULL CHECK (btrim(source_code) <> ''),
  PRIMARY KEY (series_key, ref_period)
);

COMMENT ON TABLE macro.release_events IS '경제지표 하나의 대상 기간 하나에 대한 발표 = 한 행. 일정이 바뀌어도 이 identity는 그대로이고, 예상은 이 발표를 가리킨다.';
COMMENT ON COLUMN macro.release_events.series_key IS '지표.';
COMMENT ON COLUMN macro.release_events.ref_period IS '발표 대상 기간의 시작일.';
COMMENT ON COLUMN macro.release_events.source_code IS '발표를 알려 준 원천.';

CREATE TABLE IF NOT EXISTS macro.release_schedule_versions (
  series_key smallint NOT NULL,
  ref_period date NOT NULL,
  scheduled_at timestamptz NOT NULL,
  collected_at timestamptz NOT NULL,
  -- 도메인이 정확도별 watcher 창을 선언한다(`domain/releases/schedule.py:schedule_window`).
  -- 그 목록과 여기가 어긋나면 그 정확도를 쓰는 지표의 일정 적재가 통째로 죽는다.
  schedule_precision text NOT NULL
    CHECK (schedule_precision IN ('exact','rule','date_only','estimated')),
  source_code text NOT NULL CHECK (btrim(source_code) <> ''),
  is_cancelled boolean NOT NULL DEFAULT false,
  PRIMARY KEY (series_key, ref_period, collected_at),
  FOREIGN KEY (series_key, ref_period) REFERENCES macro.release_events(series_key, ref_period) ON DELETE CASCADE
);

COMMENT ON TABLE macro.release_schedule_versions IS '발표 하나의 일정을 특정 시각에 확인한 상태 = 한 행. 일정 연기·취소 이력이다.';
COMMENT ON COLUMN macro.release_schedule_versions.series_key IS '지표.';
COMMENT ON COLUMN macro.release_schedule_versions.ref_period IS '발표 대상 기간.';
COMMENT ON COLUMN macro.release_schedule_versions.scheduled_at IS '예정 발표 시각(UTC 저장).';
COMMENT ON COLUMN macro.release_schedule_versions.collected_at IS '이 일정을 확인한 시각.';
COMMENT ON COLUMN macro.release_schedule_versions.schedule_precision IS 'exact=기관 공지 시각, rule=공표 규칙에서 유도, date_only=날짜만, estimated=추정.';
COMMENT ON COLUMN macro.release_schedule_versions.source_code IS '일정 원천.';
COMMENT ON COLUMN macro.release_schedule_versions.is_cancelled IS '발표가 취소됐는가.';


-- ── 예상치 ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS macro.forecast_snapshots (
  series_key smallint NOT NULL,
  ref_period date NOT NULL,
  measure_id text,
  forecast_kind text NOT NULL CHECK (forecast_kind IN ('survey','nowcast','own_model')),
  source_code text NOT NULL CHECK (btrim(source_code) <> ''),
  value double precision CHECK (value > '-Infinity'::float8 AND value < 'Infinity'::float8),
  effective_at timestamptz NOT NULL,
  collected_at timestamptz NOT NULL,
  time_precision text NOT NULL DEFAULT 'collector_seen' CHECK (time_precision IN ('exact','date_only','collector_seen')),
  PRIMARY KEY (series_key, ref_period, measure_id, forecast_kind, source_code, effective_at, collected_at),
  FOREIGN KEY (series_key, ref_period) REFERENCES macro.release_events(series_key, ref_period) ON DELETE CASCADE,
  -- 예상이 가리키는 measure는 같은 지표의 것이어야 한다. 다른 지표 단위와 비교되는 길을 막는다.
  FOREIGN KEY (series_key, measure_id) REFERENCES macro.measures(series_key, measure_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS forecast_snapshots_measure_idx
  ON macro.forecast_snapshots (measure_id, ref_period);

COMMENT ON TABLE macro.forecast_snapshots IS '발표 하나·measure 하나·예상 종류·원천별 예상값을 특정 시점에 확인한 상태 = 한 행. consensus·nowcast·자체모델을 한 값으로 합치지 않는다.';
COMMENT ON COLUMN macro.forecast_snapshots.series_key IS '지표.';
COMMENT ON COLUMN macro.forecast_snapshots.ref_period IS '예상 대상 기간.';
COMMENT ON COLUMN macro.forecast_snapshots.measure_id IS '예상값의 단위(measure). 원값 단위 예상이면 level measure를 가리킨다.';
COMMENT ON COLUMN macro.forecast_snapshots.forecast_kind IS 'survey=시장 컨센서스, nowcast=GDPNow 같은 기관 모델, own_model=이 시스템의 자체 모델.';
COMMENT ON COLUMN macro.forecast_snapshots.source_code IS '예상 원천.';
COMMENT ON COLUMN macro.forecast_snapshots.value IS '예상값(measure 단위). 원천이 값을 비웠으면 NULL.';
COMMENT ON COLUMN macro.forecast_snapshots.effective_at IS '원천이 말하는 예상 시점.';
COMMENT ON COLUMN macro.forecast_snapshots.collected_at IS '우리가 이 예상을 확인한 시각. 발표 전에 알았는지를 가르는 경계다.';
COMMENT ON COLUMN macro.forecast_snapshots.time_precision IS 'effective_at의 정밀도.';


-- ── measure 계산 ──────────────────────────────────────────────────────────
-- 기준 시점까지 공개된 원값(빈티지 축)으로 measure를 계산한다. 비교 기간의 값이 없거나
-- 기저가 0이면 NULL — 0이나 추정값을 채우지 않는다.
CREATE OR REPLACE FUNCTION macro.raw_value(p_series_key smallint, p_period date, p_as_of timestamptz)
RETURNS double precision LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $fn$
  SELECT coalesce(
    (SELECT o.value FROM macro.economic_observations o
      WHERE o.series_key = p_series_key AND o.observation_date = p_period
        AND o.vintage_at <= p_as_of
      ORDER BY o.vintage_at DESC, o.available_at DESC LIMIT 1),
    (SELECT m.value FROM macro.market_observations m
      WHERE m.series_key = p_series_key AND m.observation_date = p_period)
  );
$fn$;
COMMENT ON FUNCTION macro.raw_value(smallint, date, timestamptz) IS '지표·기간의 원값 중 기준 시점까지 공개된 가장 늦은 빈티지. 시장 지표는 현재 값.';

CREATE OR REPLACE FUNCTION macro.measure_value(p_measure_id text, p_ref_period date, p_as_of timestamptz)
RETURNS double precision LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE
  v_transform text; v_series smallint; v_frequency text;
  v_lag integer; v_prior_period date; v_current double precision; v_prior double precision;
BEGIN
  SELECT ms.transform, ms.series_key, s.frequency INTO v_transform, v_series, v_frequency
    FROM macro.measures ms JOIN macro.series s ON s.series_key = ms.series_key
    WHERE ms.measure_id = p_measure_id;
  IF NOT FOUND THEN RETURN NULL; END IF;
  v_current := macro.raw_value(v_series, p_ref_period, p_as_of);
  IF v_current IS NULL OR v_transform = 'level' THEN RETURN v_current; END IF;

  v_lag := CASE v_transform WHEN 'change_4' THEN 4 WHEN 'pct_change_12' THEN 12 ELSE 1 END;
  IF v_transform = 'change_previous' THEN
    SELECT max(o.observation_date) INTO v_prior_period FROM macro.economic_observations o
      WHERE o.series_key = v_series AND o.observation_date < p_ref_period AND o.vintage_at <= p_as_of;
  ELSIF v_frequency = 'weekly' THEN
    v_prior_period := p_ref_period - 7 * v_lag;
  ELSIF v_frequency IN ('daily', 'irregular') THEN
    v_prior_period := p_ref_period - v_lag;
  ELSE
    -- 달력상 N개월(분기는 3N개월) 전. 날짜는 대상 월 말일로 제한된다(normalize.calendar_months_before).
    v_prior_period := (p_ref_period - pg_catalog.make_interval(
      months => v_lag * CASE WHEN v_frequency = 'quarterly' THEN 3 ELSE 1 END))::date;
  END IF;
  IF v_prior_period IS NULL THEN RETURN NULL; END IF;
  v_prior := macro.raw_value(v_series, v_prior_period, p_as_of);
  IF v_prior IS NULL THEN RETURN NULL; END IF;
  IF v_transform IN ('change_1', 'change_4', 'change_previous') THEN
    RETURN v_current - v_prior;
  END IF;
  IF v_prior = 0 THEN RETURN NULL; END IF;
  RETURN (v_current / v_prior - 1.0) * 100.0;
END;
$fn$;
COMMENT ON FUNCTION macro.measure_value(text, date, timestamptz) IS
  'measure 하나의 대상 기간 값을 기준 시점까지 공개된 원값으로 계산한다. 최초 발표 값은 최초 빈티지 시각을, 최신 값은 infinity를 넣는다.';


-- ── 권한 ──────────────────────────────────────────────────────────────────
GRANT ALL ON ALL TABLES IN SCHEMA macro TO service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA macro TO service_role;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA macro FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA macro TO service_role;

ALTER TABLE macro.series ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro.measures ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro.market_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro.economic_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro.release_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro.release_schedule_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE macro.forecast_snapshots ENABLE ROW LEVEL SECURITY;
