-- universe — 회사·증권 identity, 식별자 브리지, 지수 membership, 관심 기업.
--
-- 이 스키마가 "무엇을 다룰 것인가"의 단일 게이트다. 다른 모든 스키마는 여기의
-- security를 참조하고, 여기에 없는 종목은 수집도 판단도 하지 않는다.
--
-- ## v1에서 바뀐 것과 그 이유
--
-- **ticker를 identity로 쓰지 않는다.** ticker는 바뀐다(개명·듀얼클래스·거래소 이동).
-- 그것을 PK로 쓰면 개명 한 번에 과거 가격과 현재 가격이 다른 회사처럼 갈라지거나,
-- 반대로 재사용된 ticker 때문에 서로 다른 회사가 한 종목으로 합쳐진다. 둘 다 에러 없이
-- 조용히 틀린다. v1은 `security_id`를 identity로 두고 ticker는 **현재 표기**로만 남긴다.
-- 사용자에게 보이는 이름은 계속 ticker다.
--
-- 과거 표기는 `security_identifiers`가 기간과 함께 보관하므로, "2019년의 FB는 지금의
-- META"를 조회로 답할 수 있다.

CREATE SCHEMA IF NOT EXISTS universe;

REVOKE ALL ON SCHEMA universe FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA universe TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA universe
  REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA universe GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA universe GRANT SELECT ON TABLES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA universe
  REVOKE ALL ON FUNCTIONS FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA universe GRANT EXECUTE ON FUNCTIONS TO service_role;


-- ── 발행사 ────────────────────────────────────────────────────────────────
-- 회사 사실은 CIK에 한 번만 저장한다. 한국어 표기도 상장 종목별 속성이 아니라
-- 발행사 표기이므로 여기가 owner다.
CREATE TABLE IF NOT EXISTS universe.entities (
  cik                     text PRIMARY KEY CHECK (cik ~ '^[0-9]{10}$'),
  company_name            text NOT NULL CHECK (btrim(company_name) <> ''),
  company_name_ko         text,
  entity_type             text,
  sic_code                text CHECK (sic_code IS NULL OR sic_code ~ '^[0-9]{4}$'),
  -- SIC는 GICS 섹터가 아니다. `sector`라고 부르면 다른 분류로 오해된다.
  sic_industry_name       text,
  sic_division_name       text,
  fiscal_year_end         text CHECK (fiscal_year_end IS NULL OR fiscal_year_end ~ '^[0-9]{4}$'),
  state_of_incorporation  text,
  former_names            jsonb NOT NULL DEFAULT '[]'::jsonb
                          CHECK (jsonb_typeof(former_names) = 'array'),
  -- SEC metadata의 마지막 정상 응답 시각. 재시도 상태가 아니라 metadata의 freshness다.
  sec_metadata_updated_at timestamptz,
  -- ── 관심 기업 ──
  -- "무엇을 더 깊이 볼 것인가"는 별도 원장이 아니라 발행사 행의 상태로 둔다.
  -- 관심은 종목이 아니라 회사에 대한 것이고, 공시·재무도 CIK가 identity다.
  -- 알림을 보낼지 말지는 notifications가 정한다 — 알림 설정은 여기 두지 않는다.
  --
  -- 활성 여부는 "아직 이 회사를 원하는 출처가 남아 있는가"다. 토스 보유가 빠져도
  -- 수동 등록이 남아 있으면 계속 본다. 정의를 한 곳에만 둔다.
  watchlist_sources       text[] NOT NULL DEFAULT ARRAY[]::text[]
                          CHECK (watchlist_sources <@ ARRAY['manual', 'toss']::text[]),
  is_watchlisted          boolean GENERATED ALWAYS AS (cardinality(watchlist_sources) > 0) STORED,
  -- 언제부터 이 회사를 보기 시작했는가. 등록 이전 과거 사건까지 소급하지 않는다.
  watch_from              date,
  -- 마지막으로 관심에서 빠진 시각. 활성 여부의 사본이 아니라 이력이다.
  watchlist_removed_at    timestamptz,
  updated_at              timestamptz NOT NULL DEFAULT now(),
  -- 보고 있는데 시작일을 모르면 "언제부터의 사건인가"를 답할 수 없다.
  CONSTRAINT entities_watch_from_required_check
    CHECK (cardinality(watchlist_sources) = 0 OR watch_from IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS entities_watchlisted_idx
  ON universe.entities (cik) WHERE is_watchlisted;


-- ── 증권 ──────────────────────────────────────────────────────────────────
-- identity는 `security_id`다. `ticker`는 현재 표기이며 UNIQUE로 유지해 조회는
-- 지금처럼 ticker로 한다 — 다만 다른 스키마의 FK는 security_id를 참조한다.
CREATE TABLE IF NOT EXISTS universe.securities (
  security_id       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ticker            text NOT NULL UNIQUE CHECK (ticker ~ '^[A-Z0-9-]{1,12}$'),
  cik               text REFERENCES universe.entities(cik),
  exchange_code     text,
  security_type     text NOT NULL DEFAULT 'common_stock'
                    CHECK (security_type IN (
                      'common_stock', 'preferred_stock', 'depositary_share',
                      'warrant', 'unit', 'note', 'etn', 'etf', 'right', 'other'
                    )),
  security_title    text,
  is_active_listing boolean NOT NULL DEFAULT true,
  -- 범용 수집 게이트. 이 값이 참인 종목만 수집·판단 대상이다.
  is_tracked        boolean NOT NULL DEFAULT false,
  updated_at        timestamptz NOT NULL DEFAULT now(),
  -- 추적하거나 상장 중이면 발행사를 알아야 한다. 모르는 채로 수집하면 그 종목의
  -- 재무를 영영 붙일 수 없다.
  CONSTRAINT securities_cik_required_for_active_check
    CHECK ((NOT is_active_listing AND NOT is_tracked) OR cik IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS securities_cik_idx
  ON universe.securities (cik) WHERE cik IS NOT NULL;
CREATE INDEX IF NOT EXISTS securities_tracked_idx
  ON universe.securities (ticker) WHERE is_tracked;
-- `entities.is_tracked`는 v1에 없다. securities에서 파생되는 값이라 저장하지 않고,
-- 발행사 단위 게이트가 필요하면 securities를 집계해 답한다.


-- ── 식별자 브리지 ─────────────────────────────────────────────────────────
-- CUSIP/CINS/FIGI와 **과거 ticker**를 한 표에서 다룬다. 13F는 CUSIP으로만 오고,
-- 과거 시점 조회는 그때의 ticker로 들어온다 — 둘 다 여기서 security_id로 옮긴다.
--
-- 기간(`valid_from`/`valid_to`)을 갖는 이유: 재사용된 ticker를 시점 없이 매핑하면
-- 서로 다른 회사가 한 종목으로 합쳐진다.
CREATE TABLE IF NOT EXISTS universe.security_identifiers (
  identifier      text NOT NULL CHECK (btrim(identifier) <> ''),
  identifier_type text NOT NULL CHECK (identifier_type IN ('CUSIP', 'CINS', 'FIGI', 'TICKER')),
  security_id     integer REFERENCES universe.securities(security_id) ON DELETE RESTRICT,
  -- 매핑이 안 된 식별자도 남긴다. 지우면 매 실행이 같은 조회를 반복한다.
  mapping_status  text NOT NULL CHECK (mapping_status IN (
                    'mapped', 'not_found', 'ambiguous', 'historical')),
  source          text NOT NULL CHECK (btrim(source) <> ''),
  -- 기간의 시작은 항상 있다. PK에 들어가므로 NULL일 수 없고, "언제부터인지 모른다"는
  -- `-infinity`로 적는다 — 선언과 실제가 어긋나면 읽는 사람이 NULL을 허용된 것으로 읽는다.
  valid_from      date NOT NULL DEFAULT '-infinity'::date,
  valid_to        date,
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (identifier, identifier_type, valid_from),
  CONSTRAINT security_identifiers_shape_check CHECK (
    (mapping_status IN ('mapped', 'historical') AND security_id IS NOT NULL)
    OR
    (mapping_status IN ('not_found', 'ambiguous') AND security_id IS NULL)
  ),
  CONSTRAINT security_identifiers_period_check
    CHECK (valid_to IS NULL OR valid_to >= valid_from),
  CONSTRAINT security_identifiers_cusip_shape_check CHECK (
    identifier_type NOT IN ('CUSIP', 'CINS') OR identifier ~ '^[A-Z0-9]{9}$'
  ),
  CONSTRAINT security_identifiers_figi_shape_check CHECK (
    identifier_type <> 'FIGI' OR identifier ~ '^[A-Z0-9]{12}$'
  ),
  CONSTRAINT security_identifiers_ticker_shape_check CHECK (
    identifier_type <> 'TICKER' OR identifier ~ '^[A-Z0-9-]{1,12}$'
  )
);

CREATE INDEX IF NOT EXISTS security_identifiers_security_idx
  ON universe.security_identifiers (security_id) WHERE security_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS security_identifiers_status_updated_idx
  ON universe.security_identifiers (mapping_status, updated_at);


-- ── 지수 membership ───────────────────────────────────────────────────────
-- point-in-time 원장이다. "그날 지수에 무엇이 있었는가"에 답하지 못하면 backtest가
-- 생존 편향에 걸린다 — 지금 살아남은 종목만 과거에 들어가기 때문이다.
--
-- 기간 행으로 보관한다. ticker 배열을 저장하면 PIT membership 조회가 JSON 전체
-- 스캔이 된다. 종료일은 배타적이므로 `valid_from <= d < valid_to`로 읽는다.
CREATE TABLE IF NOT EXISTS universe.index_memberships (
  index_code  text NOT NULL CHECK (index_code ~ '^[A-Z0-9_]{2,20}$'),
  security_id integer NOT NULL REFERENCES universe.securities(security_id) ON DELETE RESTRICT,
  valid_from  date NOT NULL,
  valid_to    date,
  source      text NOT NULL CHECK (btrim(source) <> ''),
  source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
  PRIMARY KEY (index_code, security_id, valid_from),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);

CREATE INDEX IF NOT EXISTS index_memberships_index_period_idx
  ON universe.index_memberships (index_code, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS index_memberships_security_period_idx
  ON universe.index_memberships (security_id, valid_from);

-- 한 스냅샷의 편입·편출은 반드시 한 transaction에서 반영한다.
CREATE OR REPLACE FUNCTION universe.replace_index_membership(
  p_index_code text, p_effective_date date, p_security_ids integer[],
  p_source text, p_source_hash text
) RETURNS integer LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE latest_boundary date; changed integer;
BEGIN
  IF p_effective_date IS NULL OR p_source IS NULL OR btrim(p_source) = ''
     OR p_source_hash IS NULL OR p_source_hash !~ '^[0-9a-f]{64}$'
     OR p_security_ids IS NULL OR cardinality(p_security_ids) = 0
     OR EXISTS (SELECT 1 FROM unnest(p_security_ids) x WHERE x IS NULL)
     OR cardinality(p_security_ids) <> (SELECT count(DISTINCT x) FROM unnest(p_security_ids) x)
     OR (p_index_code = 'SP500' AND cardinality(p_security_ids) NOT BETWEEN 450 AND 520) THEN
    RAISE EXCEPTION 'invalid index membership snapshot';
  END IF;
  PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('index_membership:' || p_index_code));
  SELECT max(greatest(valid_from, valid_to)) INTO latest_boundary
    FROM universe.index_memberships WHERE index_code = p_index_code;
  IF latest_boundary > p_effective_date THEN
    RAISE EXCEPTION 'membership snapshots must be applied in chronological order';
  END IF;
  DELETE FROM universe.index_memberships
    WHERE index_code=p_index_code AND valid_from=p_effective_date AND valid_to IS NULL
      AND NOT (security_id=ANY(p_security_ids));
  UPDATE universe.index_memberships SET valid_to=p_effective_date
    WHERE index_code=p_index_code AND valid_to IS NULL AND valid_from<p_effective_date
      AND NOT (security_id=ANY(p_security_ids));
  UPDATE universe.index_memberships SET valid_to=NULL
    WHERE index_code=p_index_code AND valid_to=p_effective_date AND security_id=ANY(p_security_ids);
  INSERT INTO universe.index_memberships(index_code,security_id,valid_from,source,source_hash)
    SELECT p_index_code,x,p_effective_date,p_source,p_source_hash FROM unnest(p_security_ids) x
    WHERE NOT EXISTS (SELECT 1 FROM universe.index_memberships m
      WHERE m.index_code=p_index_code AND m.security_id=x AND m.valid_to IS NULL);
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed;
END;
$fn$;
REVOKE ALL ON FUNCTION universe.replace_index_membership(text,date,integer[],text,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION universe.replace_index_membership(text,date,integer[],text,text) TO service_role;


-- ── RLS ───────────────────────────────────────────────────────────────────
-- 읽기는 열고 쓰기는 service_role만. fail-closed가 기본이다.
ALTER TABLE universe.entities            ENABLE ROW LEVEL SECURITY;
ALTER TABLE universe.securities          ENABLE ROW LEVEL SECURITY;
ALTER TABLE universe.security_identifiers ENABLE ROW LEVEL SECURITY;
ALTER TABLE universe.index_memberships   ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS entities_read             ON universe.entities;
DROP POLICY IF EXISTS securities_read           ON universe.securities;
DROP POLICY IF EXISTS security_identifiers_read ON universe.security_identifiers;
DROP POLICY IF EXISTS index_memberships_read    ON universe.index_memberships;

CREATE POLICY entities_read             ON universe.entities             FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY securities_read           ON universe.securities           FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY security_identifiers_read ON universe.security_identifiers FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY index_memberships_read    ON universe.index_memberships    FOR SELECT TO anon, authenticated USING (true);
