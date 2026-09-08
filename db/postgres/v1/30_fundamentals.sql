-- fundamentals — SEC 공시에서 나온 재무 사실.
--
-- 공시 단위로 append한다. PK에 `accession_no`가 들어가므로 원본과 정정이 나란히
-- 남고, "as-of 시점의 최신"은 저장이 아니라 **조회**로 답한다.
--
-- ## 두 개의 시각을 구분한다
--
-- `filed_at`은 SEC에 제출된 날, `available_at`은 우리가 그것을 손에 넣은 시각이다. 둘을
-- 한 컬럼에 섞으면 backtest가 제출 당일 즉시 알았다고 가정하게 되는데, 실제로는 수집이
-- 며칠 늦을 수 있다. PIT 조회는 반드시 `available_at`으로 자른다.

CREATE SCHEMA IF NOT EXISTS fundamentals;

REVOKE ALL ON SCHEMA fundamentals FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA fundamentals TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA fundamentals
  REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA fundamentals GRANT ALL    ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA fundamentals GRANT SELECT ON TABLES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA fundamentals
  REVOKE ALL ON FUNCTIONS FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA fundamentals GRANT EXECUTE ON FUNCTIONS TO service_role;


-- numeric 배열에 NaN/Infinity가 섞였는지 본다. Postgres의 numeric은 'NaN'을 값으로
-- 받아들이는데, 그 한 행이 SUM·AVG를 통째로 NaN으로 만들고 그 결과는 예외 없이
-- 카드에 실린다. 그래서 넣는 자리에서 막는다.
-- 인자 이름이 `values`면 안 된다 — Postgres 예약어라 본문에서 그대로 못 쓴다.
CREATE OR REPLACE FUNCTION fundamentals.is_finite_numbers(numbers numeric[])
RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $fn$
  SELECT NOT EXISTS (
    SELECT 1 FROM unnest(numbers) AS v
    WHERE v IS NOT NULL
      AND (v = 'NaN'::numeric OR v = 'Infinity'::numeric OR v = '-Infinity'::numeric)
  );
$fn$;

-- ── 공시 원장 ─────────────────────────────────────────────────────────────
-- "어떤 공시가 존재하는가"는 사실이고, "우리가 그것을 어떻게 처리했는가"는 상태다.
CREATE TABLE IF NOT EXISTS fundamentals.filings (
  accession_no text NOT NULL PRIMARY KEY
               CHECK (accession_no ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'),
  cik          text NOT NULL REFERENCES universe.entities(cik),
  form_type    text NOT NULL CHECK (form_type IN ('10-Q', '10-Q/A', '10-K', '10-K/A', '8-K')),
  filing_date  date NOT NULL,
  report_date  date,
  -- 우리가 이 공시를 알게 된 시각. PIT 경계다.
  available_at timestamptz NOT NULL DEFAULT now(),
  source       text NOT NULL CHECK (btrim(source) <> '')
);

CREATE INDEX IF NOT EXISTS filings_cik_filed_idx
  ON fundamentals.filings (cik, filing_date DESC);
CREATE INDEX IF NOT EXISTS filings_available_idx
  ON fundamentals.filings (available_at);


-- 처리 상태. 재처리 대상 선정이 이 표만 읽는다 — 공시 사실은 위에 그대로 남는다.
-- `mapping_version`은 content_type마다 다른 어휘를 쓰므로 섞어 읽으면 안 된다.
CREATE TABLE IF NOT EXISTS fundamentals.filing_processing (
  accession_no    text NOT NULL REFERENCES fundamentals.filings(accession_no) ON DELETE CASCADE,
  content_type    text NOT NULL CHECK (content_type IN ('company', 'segments')),
  mapping_version text NOT NULL,
  status          text NOT NULL CHECK (status IN ('parsed', 'empty', 'unsupported', 'superseded')),
  facts_count     int  NOT NULL DEFAULT 0 CHECK (facts_count >= 0),
  rows_count      int  NOT NULL DEFAULT 0 CHECK (rows_count >= 0),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (accession_no, content_type, mapping_version),
  -- 상태와 건수가 어긋나면 재처리 판단이 조용히 틀린다.
  CONSTRAINT filing_processing_shape_check CHECK (
    (status = 'parsed'      AND facts_count > 0 AND rows_count > 0)
    OR (status = 'empty'       AND facts_count = 0 AND rows_count = 0)
    OR (status = 'unsupported' AND facts_count > 0 AND rows_count = 0)
    OR (status = 'superseded'  AND facts_count = 0 AND rows_count = 0)
  )
);

CREATE INDEX IF NOT EXISTS filing_processing_status_idx
  ON fundamentals.filing_processing (content_type, mapping_version, status);


-- ── 기업 전체 재무 (canonical) ───────────────────────────────────────────
-- SEC CompanyFacts는 등록인(CIK) 사실이다. ticker fan-out은 읽는 쪽이 한다.
CREATE TABLE IF NOT EXISTS fundamentals.financials (
  cik           text NOT NULL REFERENCES universe.entities(cik),
  period_end    date NOT NULL,
  -- 이 값을 만든 최신 공시. 정정은 canonical 기간 행을 교체한다.
  source_accession_no text NOT NULL REFERENCES fundamentals.filings(accession_no) ON DELETE RESTRICT,
  source_filing_date  date NOT NULL,
  fiscal_year   int  NOT NULL,
  fiscal_period text NOT NULL CHECK (fiscal_period IN ('FY','Q1','Q2','Q3','Q4')),
  -- 손익계산서
  revenue                                      numeric,
  cost_of_goods_and_services_sold              numeric,
  gross_profit                                 numeric,
  research_and_development_expenses            numeric,
  selling_general_and_admin_expenses           numeric,
  operating_income_loss                        numeric,
  interest_expense                             numeric,
  pretax_income_loss                           numeric,
  income_taxes                                 numeric,
  net_income                                   numeric,
  minority_interest_income                     numeric,
  net_income_to_common_shareholders            numeric,
  eps_basic_gaap                               numeric,
  eps_diluted_gaap                             numeric,
  dividends_declared_per_share                 numeric,
  -- 대차대조표 — 자산
  assets                                       numeric,
  current_assets_total                         numeric,
  cash_and_cash_equivalents                    numeric,
  short_term_investments                       numeric,
  trade_receivables                            numeric,
  inventories                                  numeric,
  property_plant_equipment_net                 numeric,
  goodwill                                     numeric,
  intangible_assets_excluding_goodwill         numeric,
  operating_lease_right_of_use_asset           numeric,
  -- 대차대조표 — 부채·자본
  liabilities                                  numeric,
  is_liabilities_derived                       boolean     NOT NULL DEFAULT false,
  current_liabilities_total                    numeric,
  trade_payables                               numeric,
  short_term_debt                              numeric,
  current_portion_of_long_term_debt            numeric,
  long_term_debt                               numeric,
  total_debt_including_current                 numeric,
  operating_lease_current_debt_equivalent      numeric,
  operating_lease_non_current_debt_equivalent  numeric,
  common_equity                                numeric,
  common_equity_scope                          text        NOT NULL DEFAULT 'unknown'
    CHECK (common_equity_scope IN (
      'common', 'stockholders', 'stockholders_including_nci', 'unknown'
    )),
  minority_interest_balance                    numeric,
  -- 메자닌(임시) 자본. 명시적으로 상환가능한 비지배지분·우선주는 부채도 영구자본도
  -- 아니다. 저장하지 않으면 회계항등식이 구조적으로 깨지고
  -- EV에서 보통주보다 앞선 청구권이 빠진다.
  mezzanine_equity                             numeric,
  preferred_stock                              numeric,
  retained_earnings                            numeric,
  -- 현금흐름표
  net_cash_from_operating_activities           numeric,
  net_cash_from_investing_activities           numeric,
  net_cash_from_financing_activities           numeric,
  depreciation_amortization_cf                 numeric,
  stock_based_compensation_cf                  numeric,
  capital_expenses                             numeric,
  acquisitions_net_of_cash                     numeric,
  stock_repurchase_payments                    numeric,
  common_dividends_paid                        numeric,
  long_term_debt_issued                        numeric,
  long_term_debt_repaid                        numeric,
  -- 주식수
  shares_average                               numeric,
  shares_fully_diluted_average                 numeric,
  -- 은행·금융 핵심 계정. reporting 계층이 필요에 따라 계산한다.
  net_interest_income                          numeric,
  provision_for_credit_losses                  numeric,
  net_loans_and_leases                         numeric,
  total_deposits                               numeric,

  -- 적재 코드가 넣는다(gaap_concepts.SEMANTIC_POLICY_VERSION). 세대가 다른 행을
  -- 섞어 읽으면 같은 개념이 다른 규칙으로 매핑된 값이 한 시계열에 들어간다.
  mapping_version text        NOT NULL,
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cik, period_end, fiscal_period)
);

CREATE INDEX IF NOT EXISTS financials_period_idx
  ON fundamentals.financials (cik, period_end DESC);
CREATE INDEX IF NOT EXISTS financials_accession_idx
  ON fundamentals.financials (source_accession_no);

-- backfill과 daily가 역순으로 끝나도 최신 정정값을 과거 공시가 덮지 못한다.
CREATE OR REPLACE FUNCTION fundamentals.guard_canonical_financials()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE source_date date; source_cik text;
BEGIN
  SELECT filing_date,cik INTO STRICT source_date,source_cik
    FROM fundamentals.filings WHERE accession_no=NEW.source_accession_no;
  IF source_cik <> NEW.cik THEN
    RAISE EXCEPTION 'financial source filing belongs to a different entity';
  END IF;
  NEW.source_filing_date := source_date;
  IF TG_OP = 'UPDATE' THEN
    IF (NEW.source_filing_date,NEW.source_accession_no) < (OLD.source_filing_date,OLD.source_accession_no) THEN
      RETURN NULL;
    END IF;
    NEW.updated_at := OLD.updated_at;
    IF to_jsonb(NEW) = to_jsonb(OLD) THEN RETURN NULL; END IF;
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END;
$fn$;
CREATE TRIGGER financials_canonical_guard BEFORE INSERT OR UPDATE ON fundamentals.financials
  FOR EACH ROW EXECUTE FUNCTION fundamentals.guard_canonical_financials();

-- ── 주식수 스냅샷 ─────────────────────────────────────────────────────────
-- dei:EntityCommonStockSharesOutstanding은 표지에 적힌 **관측 시점** 주식수다.
-- `as_of_date`(그 숫자가 말하는 날)와 공시일이 다르고, 그 차이가 시가총액 계산을
-- 좌우하므로 둘을 절대 한 컬럼에 합치지 않는다. 공시일은 `filings`에 있다.
--
-- 멀티클래스(BRK.A/BRK.B, GOOG/GOOGL)에서는 클래스별 행이 따로 오는데, 어느 상장
-- 종목에 붙는지 확정하지 못하는 경우가 있다. 그 실패를 NULL로 지우지 않고
-- `ticker_mapping_status`로 남긴다 — 매핑 규칙을 고칠 때 무엇이 안 붙었는지 알아야 한다.
CREATE TABLE IF NOT EXISTS fundamentals.share_class_snapshots (
  cik                   text NOT NULL REFERENCES universe.entities(cik) ON DELETE CASCADE,
  share_class_key       text NOT NULL CHECK (btrim(share_class_key) <> ''),
  share_class_axis      text,
  share_class_member    text,
  share_class_title     text NOT NULL CHECK (btrim(share_class_title) <> ''),
  mapped_security_id    integer REFERENCES universe.securities(security_id) ON DELETE SET NULL,
  as_of_date            date NOT NULL,
  shares_outstanding    bigint NOT NULL CHECK (shares_outstanding > 0),
  accession_no          text NOT NULL REFERENCES fundamentals.filings(accession_no) ON DELETE CASCADE,
  source_concept        text NOT NULL CHECK (source_concept IN (
                          'dei:EntityCommonStockSharesOutstanding',
                          'us-gaap:CommonStockSharesOutstanding'
                        )),
  ticker_mapping_status text NOT NULL DEFAULT 'unresolved_multiclass'
                        CHECK (ticker_mapping_status IN (
                          'single_class_default', 'mapped_by_symbol', 'mapped_by_title',
                          'unmapped_unlisted', 'unresolved_multiclass'
                        )),
  ingested_at           timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cik, share_class_key, as_of_date, accession_no),
  -- 축과 멤버는 함께 있거나 함께 없다. 반쪽짜리 클래스 좌표는 어디에도 못 붙인다.
  CONSTRAINT share_class_dimension_shape_check
    CHECK ((share_class_axis IS NULL) = (share_class_member IS NULL)),
  -- 종목이 붙은 행은 붙었다고 말해야 한다. 상태와 값이 어긋나면 충전율 진단이 거짓말한다.
  CONSTRAINT share_class_mapping_shape_check CHECK (
    (mapped_security_id IS NOT NULL AND ticker_mapping_status IN
       ('single_class_default','mapped_by_symbol','mapped_by_title'))
    OR (mapped_security_id IS NULL AND ticker_mapping_status IN
       ('unmapped_unlisted','unresolved_multiclass'))
  )
);

CREATE INDEX IF NOT EXISTS share_class_cik_as_of_idx
  ON fundamentals.share_class_snapshots (cik, as_of_date DESC);
CREATE INDEX IF NOT EXISTS share_class_security_as_of_idx
  ON fundamentals.share_class_snapshots (mapped_security_id, as_of_date DESC)
  WHERE mapped_security_id IS NOT NULL;


-- ── 세그먼트 재무 ─────────────────────────────────────────────────────────
-- 전사 재무와 같은 회계기간 모델을 쓰되 축·멤버로 한 번 더 쪼갠 값이다.
-- `secondary_axis`가 NULL이면 1차원, 아니면 2차원 — 이것이 유일한 판별식이다.
--
-- 값마다 품질 등급을 함께 저장한다. 등급 없이 숫자만 남기면 "회사가 보고한 값"과
-- "우리가 FY에서 Q1~Q3를 빼서 만든 값"이 한 시계열에 섞여 추세가 조용히 틀린다.
CREATE TABLE IF NOT EXISTS fundamentals.segment_metrics (
  cik                   text NOT NULL REFERENCES universe.entities(cik),
  accession_no          text NOT NULL REFERENCES fundamentals.filings(accession_no) ON DELETE CASCADE,
  fiscal_year           int  NOT NULL CHECK (fiscal_year BETWEEN 1900 AND 2200),
  fiscal_period         text NOT NULL CHECK (fiscal_period IN ('FY','Q1','Q2','Q3','Q4')),
  period_end            date NOT NULL,
  -- 축·멤버 조합의 지문. 문자열이 길고 유니코드가 섞여 PK에 직접 넣기 어렵다.
  segment_hash          text NOT NULL CHECK (segment_hash ~ '^[0-9a-f]{40}$'),
  segment_type          text NOT NULL CHECK (segment_type IN ('business','product','geographic')),
  axis                  text NOT NULL CHECK (btrim(axis) <> ''),
  member                text NOT NULL CHECK (btrim(member) <> ''),
  secondary_axis        text,
  secondary_member      text,
  -- 보고된 값인지, 우리가 빼서 만든 값인지.
  is_derived            boolean NOT NULL DEFAULT false,
  revenue               numeric,
  quality_status        text CHECK (quality_status IN ('verified','partial')),
  -- 1차원 분할이 전사 합계를 얼마나 덮는지. group 단위 값이라 2차원 행에는 없다.
  coverage_ratio        numeric,
  profit_loss           numeric,
  -- 어떤 이익인지(영업·세전·순·매출총). 이것 없이는 숫자의 의미가 정해지지 않는다.
  profit_measure_kind   text,
  profit_quality_status text CHECK (profit_quality_status IN ('verified','partial')),
  assets                numeric,
  assets_quality_status text CHECK (assets_quality_status IN ('verified','partial')),
  ingested_at           timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cik, accession_no, fiscal_year, fiscal_period, segment_hash),
  -- 값이 하나도 없는 축 멤버는 저장하지 않는다.
  CONSTRAINT segment_has_value_check
    CHECK (num_nonnulls(revenue, profit_loss, assets) > 0),
  CONSTRAINT segment_revenue_quality_check CHECK (revenue IS NULL OR quality_status IS NOT NULL),
  CONSTRAINT segment_profit_definition_check
    CHECK (profit_loss IS NULL OR (profit_measure_kind IS NOT NULL AND profit_quality_status IS NOT NULL)),
  CONSTRAINT segment_assets_quality_check CHECK (assets IS NULL OR assets_quality_status IS NOT NULL),
  CONSTRAINT segment_secondary_pair_check CHECK (
    (secondary_axis IS NULL AND secondary_member IS NULL)
    OR (btrim(secondary_axis) <> '' AND btrim(secondary_member) <> '')
  ),
  CONSTRAINT segment_coverage_scope_check
    CHECK (coverage_ratio IS NULL OR (secondary_axis IS NULL AND coverage_ratio > 0)),
  CONSTRAINT segment_finite_check
    CHECK (fundamentals.is_finite_numbers(ARRAY[revenue, coverage_ratio, profit_loss, assets]))
);

CREATE INDEX IF NOT EXISTS segment_metrics_period_idx
  ON fundamentals.segment_metrics (cik, period_end DESC, fiscal_period);
CREATE INDEX IF NOT EXISTS segment_metrics_axis_idx
  ON fundamentals.segment_metrics (cik, segment_type, axis, period_end DESC);


-- ── 실적 실제치 (8-K 속보) ────────────────────────────────────────────────
-- **예상치는 여기 저장하지 않는다.** 발표 시점 컨센서스는 `earnings_estimates`를
-- `snapshot_date < filing_date`로 조인해 조회 시점에 만든다. 서프라이즈를 계산해
-- 저장해 두면 컨센서스가 갱신될 때 과거 서프라이즈가 조용히 흔들린다.
CREATE TABLE IF NOT EXISTS fundamentals.earnings_results (
  cik                     text NOT NULL REFERENCES universe.entities(cik),
  accession_no            text NOT NULL REFERENCES fundamentals.filings(accession_no) ON DELETE CASCADE,
  fiscal_year             int  NOT NULL CHECK (fiscal_year BETWEEN 1900 AND 2200),
  fiscal_period           text NOT NULL CHECK (fiscal_period IN ('Q1','Q2','Q3','Q4','FY')),
  period_end              date NOT NULL,
  revenue_actual          numeric,
  eps_actual              numeric,
  operating_income_actual numeric,
  net_income_actual       numeric,
  -- 보도자료 원문에서 뽑은 가이던스 한 줄. 해석은 읽는 쪽이 한다.
  guidance_summary        text,
  press_release_url       text,
  source                  text NOT NULL DEFAULT 'sec_8k' CHECK (btrim(source) <> ''),
  collected_at            timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cik, fiscal_year, fiscal_period, accession_no),
  -- 아무 값도 없는 속보는 알림을 만들 수 없다. 빈 행이 쌓이면 커버리지가 거짓말한다.
  CONSTRAINT earnings_results_has_payload_check CHECK (
    num_nonnulls(revenue_actual, eps_actual, operating_income_actual, net_income_actual,
                 nullif(btrim(guidance_summary), ''), nullif(btrim(press_release_url), '')) > 0
  ),
  CONSTRAINT earnings_results_finite_check CHECK (
    fundamentals.is_finite_numbers(
      ARRAY[revenue_actual, eps_actual, operating_income_actual, net_income_actual])
  )
);

CREATE INDEX IF NOT EXISTS earnings_results_period_idx
  ON fundamentals.earnings_results (cik, period_end DESC);


-- ── 컨센서스 스냅샷 ───────────────────────────────────────────────────────
-- 상대 horizon(q+0·q+1·fy+0·fy+1)으로 오는 값을 회사 회계력의 **절대** 연도·분기로
-- 고정해 저장한다. 상대 좌표로 두면 분기가 넘어가는 순간 같은 행이 다른 기간을
-- 가리키게 되고, 그때 과거 서프라이즈가 통째로 어긋난다.
CREATE TABLE IF NOT EXISTS fundamentals.earnings_estimates (
  security_id          integer NOT NULL REFERENCES universe.securities(security_id) ON DELETE CASCADE,
  target_fiscal_year   int  NOT NULL CHECK (target_fiscal_year BETWEEN 1900 AND 2200),
  target_fiscal_period text NOT NULL CHECK (target_fiscal_period IN ('Q1','Q2','Q3','Q4','FY')),
  target_period_end    date NOT NULL,
  snapshot_date        date NOT NULL,
  -- observed = 그날 실제로 본 값, reconstructed = 과거 발표 기록에서 되살린 값.
  -- 섞어 읽으면 PIT가 깨진다.
  snapshot_kind        text NOT NULL CHECK (snapshot_kind IN ('observed','reconstructed')),
  source               text NOT NULL DEFAULT 'yfinance' CHECK (btrim(source) <> ''),
  source_horizon       text NOT NULL CHECK (source_horizon IN ('q+0','q+1','fy+0','fy+1')),
  eps_avg              numeric,
  eps_low              numeric,
  eps_high             numeric,
  eps_analysts         int CHECK (eps_analysts IS NULL OR eps_analysts >= 0),
  revenue_avg          numeric,
  revenue_low          numeric,
  revenue_high         numeric,
  revenue_analysts     int CHECK (revenue_analysts IS NULL OR revenue_analysts >= 0),
  revisions_up_7d      int CHECK (revisions_up_7d    IS NULL OR revisions_up_7d    >= 0),
  revisions_up_30d     int CHECK (revisions_up_30d   IS NULL OR revisions_up_30d   >= 0),
  revisions_down_7d    int CHECK (revisions_down_7d  IS NULL OR revisions_down_7d  >= 0),
  revisions_down_30d   int CHECK (revisions_down_30d IS NULL OR revisions_down_30d >= 0),
  collected_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (security_id, target_fiscal_year, target_fiscal_period, snapshot_date, source, snapshot_kind),
  CONSTRAINT estimates_range_check CHECK (
    (eps_low     IS NULL OR eps_high     IS NULL OR eps_low     <= eps_high)
    AND (revenue_low IS NULL OR revenue_high IS NULL OR revenue_low <= revenue_high)
  ),
  CONSTRAINT estimates_has_value_check CHECK (eps_avg IS NOT NULL OR revenue_avg IS NOT NULL),
  -- 관측일이 수집 시각보다 미래면 그 행은 미래를 본 것이다.
  CONSTRAINT estimates_not_from_the_future_check
    CHECK (snapshot_date <= (collected_at AT TIME ZONE 'America/New_York')::date),
  CONSTRAINT estimates_finite_check CHECK (
    fundamentals.is_finite_numbers(
      ARRAY[eps_avg, eps_low, eps_high, revenue_avg, revenue_low, revenue_high])
  )
);

-- 카드·화면은 거의 항상 observed만 본다. 부분 인덱스가 그 경로를 좁게 잡는다.
CREATE INDEX IF NOT EXISTS estimates_observed_idx
  ON fundamentals.earnings_estimates
     (security_id, target_fiscal_year, target_fiscal_period, snapshot_date DESC)
  WHERE snapshot_kind = 'observed';
-- 서프라이즈 계산은 발표일 이전 마지막 스냅샷을 찾는다 — kind와 무관하게 훑는다.
CREATE INDEX IF NOT EXISTS estimates_asof_idx
  ON fundamentals.earnings_estimates
     (security_id, target_period_end, snapshot_date DESC);


-- ── 발표 예정 (버전 보존) ─────────────────────────────────────────────────
-- 예정일은 자주 바뀌고, **바뀌었다는 사실 자체가 신호다.** 그래서 덮어쓰지 않고
-- 관측일마다 새 행을 쌓는다. "언제 밀렸나"는 이 표를 시간순으로 읽으면 나온다.
--
-- 저장하는 사실은 시각 하나다. 날짜는 ET 기준으로 파생한다 — 두 컬럼으로 저장하면
-- 어긋날 수 있고, KST에서 읽을 때 하루 밀려 보인다(16:00 ET = 익일 05:00 KST).
CREATE TABLE IF NOT EXISTS fundamentals.earnings_schedule_versions (
  security_id          integer NOT NULL REFERENCES universe.securities(security_id) ON DELETE CASCADE,
  target_fiscal_year   int  NOT NULL CHECK (target_fiscal_year BETWEEN 1900 AND 2200),
  target_fiscal_period text NOT NULL CHECK (target_fiscal_period IN ('Q1','Q2','Q3','Q4')),
  target_period_end    date NOT NULL,
  snapshot_date        date NOT NULL,
  expected_report_at   timestamptz NOT NULL,
  expected_report_date date GENERATED ALWAYS AS
                       ((expected_report_at AT TIME ZONE 'America/New_York')::date) STORED,
  -- 장전/장후/장중. 8-K 접수 시각이 8시간 넘게 갈리므로 감시 창을 이것으로 잡는다.
  expected_session     text NOT NULL DEFAULT 'unknown'
                       CHECK (expected_session IN ('bmo','amc','dmh','unknown')),
  -- 추정일인지 회사 확정 공지인지. 추정이면 감시 창을 넓게 잡는다.
  is_estimated         boolean,
  source               text NOT NULL DEFAULT 'yfinance' CHECK (btrim(source) <> ''),
  collected_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (security_id, target_fiscal_year, target_fiscal_period, snapshot_date, source),
  CONSTRAINT schedule_order_check CHECK (
    target_period_end <= (expected_report_at AT TIME ZONE 'America/New_York')::date
    AND snapshot_date <= (expected_report_at AT TIME ZONE 'America/New_York')::date
    AND snapshot_date <= (collected_at AT TIME ZONE 'America/New_York')::date
  )
);

-- 수집 job이 "오늘 이 세션에 발표하는 종목"을 한 번에 뽑는 경로.
CREATE INDEX IF NOT EXISTS schedule_session_idx
  ON fundamentals.earnings_schedule_versions (expected_report_date, expected_session);
CREATE INDEX IF NOT EXISTS schedule_security_idx
  ON fundamentals.earnings_schedule_versions
     (security_id, target_fiscal_year, target_fiscal_period, snapshot_date DESC);


-- ── 애널리스트 커버리지 스냅샷 ────────────────────────────────────────────
-- 목표주가와 투자의견 분포. 관측일별로 쌓아 추세를 볼 수 있게 한다.
CREATE TABLE IF NOT EXISTS fundamentals.analyst_consensus_snapshots (
  security_id   integer NOT NULL REFERENCES universe.securities(security_id) ON DELETE CASCADE,
  snapshot_date date NOT NULL,
  source        text NOT NULL DEFAULT 'yfinance' CHECK (btrim(source) <> ''),
  target_mean   numeric CHECK (target_mean   IS NULL OR target_mean   >= 0),
  target_median numeric CHECK (target_median IS NULL OR target_median >= 0),
  target_high   numeric CHECK (target_high   IS NULL OR target_high   >= 0),
  target_low    numeric CHECK (target_low    IS NULL OR target_low    >= 0),
  strong_buy    int CHECK (strong_buy  IS NULL OR strong_buy  >= 0),
  buy           int CHECK (buy         IS NULL OR buy         >= 0),
  hold          int CHECK (hold        IS NULL OR hold        >= 0),
  sell          int CHECK (sell        IS NULL OR sell        >= 0),
  strong_sell   int CHECK (strong_sell IS NULL OR strong_sell >= 0),
  collected_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (security_id, snapshot_date, source),
  CONSTRAINT consensus_range_check
    CHECK (target_low IS NULL OR target_high IS NULL OR target_low <= target_high),
  CONSTRAINT consensus_has_value_check CHECK (
    num_nonnulls(target_mean, target_median, target_high, target_low,
                 strong_buy, buy, hold, sell, strong_sell) > 0
  ),
  CONSTRAINT consensus_not_from_the_future_check
    CHECK (snapshot_date <= (collected_at AT TIME ZONE 'America/New_York')::date),
  CONSTRAINT consensus_finite_check CHECK (
    fundamentals.is_finite_numbers(ARRAY[target_mean, target_median, target_high, target_low])
  )
);

CREATE INDEX IF NOT EXISTS consensus_security_idx
  ON fundamentals.analyst_consensus_snapshots (security_id, snapshot_date DESC);


-- ── RLS ─────────────────────────────────────────────────────────────────────────
ALTER TABLE fundamentals.filings                     ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.filing_processing           ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.financials                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.share_class_snapshots       ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.segment_metrics             ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.earnings_results            ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.earnings_estimates          ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.earnings_schedule_versions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.analyst_consensus_snapshots ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS filings_read                     ON fundamentals.filings;
DROP POLICY IF EXISTS filing_processing_read           ON fundamentals.filing_processing;
DROP POLICY IF EXISTS financials_read                  ON fundamentals.financials;
DROP POLICY IF EXISTS share_class_snapshots_read       ON fundamentals.share_class_snapshots;
DROP POLICY IF EXISTS segment_metrics_read             ON fundamentals.segment_metrics;
DROP POLICY IF EXISTS earnings_results_read            ON fundamentals.earnings_results;
DROP POLICY IF EXISTS earnings_estimates_read          ON fundamentals.earnings_estimates;
DROP POLICY IF EXISTS earnings_schedule_versions_read  ON fundamentals.earnings_schedule_versions;
DROP POLICY IF EXISTS analyst_consensus_snapshots_read ON fundamentals.analyst_consensus_snapshots;

CREATE POLICY filings_read                     ON fundamentals.filings                     FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY filing_processing_read           ON fundamentals.filing_processing           FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY financials_read                  ON fundamentals.financials                  FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY share_class_snapshots_read       ON fundamentals.share_class_snapshots       FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY segment_metrics_read             ON fundamentals.segment_metrics             FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY earnings_results_read            ON fundamentals.earnings_results            FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY earnings_estimates_read          ON fundamentals.earnings_estimates          FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY earnings_schedule_versions_read  ON fundamentals.earnings_schedule_versions  FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY analyst_consensus_snapshots_read ON fundamentals.analyst_consensus_snapshots FOR SELECT TO anon, authenticated USING (true);


-- ── 발표가 끝난 뒤의 스냅샷 정리 ──────────────────────────────────────────
-- 예상치·일정·커버리지는 매일 한 행씩 쌓인다. 발표 전에는 그 누적 자체가 값이지만
-- (예정일이 밀린 것, 컨센서스가 움직인 것), **발표가 끝나면 그중 하나만 계속 쓰인다**
-- — `reporting.earnings_surprise`가 고르는 "발표일 직전 마지막 스냅샷"이다.
--
-- 그래서 지우는 기준은 나이가 아니라 발표 여부다. 나이로만 자르면 아직 발표 안 한
-- 분기의 드리프트가 사라지고, 반대로 10년 전 분기의 매일치가 그대로 남는다.
--
-- `p_recent_days` 안쪽은 발표가 끝났어도 건드리지 않는다. 최근 구간을 통째로 들고
-- 있어야 그 시점 판단을 그대로 재현(historical replay)할 수 있다.
CREATE OR REPLACE FUNCTION fundamentals.prune_expectation_snapshots(p_recent_days int DEFAULT 180)
RETURNS TABLE (estimates_deleted bigint, schedules_deleted bigint, consensus_deleted bigint)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE
  cutoff date;
  est bigint; sch bigint; con bigint;
BEGIN
  IF p_recent_days IS NULL OR p_recent_days < 1 THEN
    RAISE EXCEPTION 'p_recent_days must be at least 1';
  END IF;
  cutoff := (pg_catalog.now() AT TIME ZONE 'America/New_York')::date - p_recent_days;

  CREATE TEMP TABLE reported_period ON COMMIT DROP AS
  SELECT s.security_id, r.fiscal_year, r.fiscal_period, f.filing_date
  FROM fundamentals.earnings_results r
  JOIN fundamentals.filings f ON f.accession_no = r.accession_no
  JOIN universe.securities s ON s.cik = r.cik;

  -- 서프라이즈가 집는 그 한 행. 원천·kind별로 남겨 두 원천이 서로를 밀어내지 않게 한다.
  CREATE TEMP TABLE estimate_keeper ON COMMIT DROP AS
  SELECT DISTINCT ON (e.security_id, e.target_fiscal_year, e.target_fiscal_period,
                      e.source, e.snapshot_kind)
         e.security_id, e.target_fiscal_year, e.target_fiscal_period,
         e.source, e.snapshot_kind, e.snapshot_date
  FROM fundamentals.earnings_estimates e
  JOIN reported_period rp
    ON rp.security_id = e.security_id
   AND rp.fiscal_year = e.target_fiscal_year
   AND rp.fiscal_period = e.target_fiscal_period
  WHERE e.snapshot_date < rp.filing_date
  ORDER BY e.security_id, e.target_fiscal_year, e.target_fiscal_period,
           e.source, e.snapshot_kind, e.snapshot_date DESC;

  WITH removed AS (
    DELETE FROM fundamentals.earnings_estimates e
    USING reported_period rp
    WHERE rp.security_id = e.security_id
      AND rp.fiscal_year = e.target_fiscal_year
      AND rp.fiscal_period = e.target_fiscal_period
      AND e.snapshot_date < cutoff
      AND NOT EXISTS (
        SELECT 1 FROM estimate_keeper k
        WHERE k.security_id = e.security_id
          AND k.target_fiscal_year = e.target_fiscal_year
          AND k.target_fiscal_period = e.target_fiscal_period
          AND k.source = e.source
          AND k.snapshot_kind = e.snapshot_kind
          AND k.snapshot_date = e.snapshot_date
      )
    RETURNING 1
  ) SELECT count(*) INTO est FROM removed;

  -- 일정은 "언제 밀렸나"가 발표 전에만 신호다. 끝난 분기는 확정된 마지막 한 건만 둔다.
  WITH removed AS (
    DELETE FROM fundamentals.earnings_schedule_versions v
    USING reported_period rp
    WHERE rp.security_id = v.security_id
      AND rp.fiscal_year = v.target_fiscal_year
      AND rp.fiscal_period = v.target_fiscal_period
      AND v.snapshot_date < cutoff
      AND v.snapshot_date < (
        SELECT max(latest.snapshot_date)
        FROM fundamentals.earnings_schedule_versions latest
        WHERE latest.security_id = v.security_id
          AND latest.target_fiscal_year = v.target_fiscal_year
          AND latest.target_fiscal_period = v.target_fiscal_period
          AND latest.source = v.source
      )
    RETURNING 1
  ) SELECT count(*) INTO sch FROM removed;

  -- 커버리지는 기간 축이 없다 — 종목·원천별 현재값만 계속 쓰인다.
  WITH removed AS (
    DELETE FROM fundamentals.analyst_consensus_snapshots c
    WHERE c.snapshot_date < cutoff
      AND c.snapshot_date < (
        SELECT max(latest.snapshot_date)
        FROM fundamentals.analyst_consensus_snapshots latest
        WHERE latest.security_id = c.security_id AND latest.source = c.source
      )
    RETURNING 1
  ) SELECT count(*) INTO con FROM removed;

  RETURN QUERY SELECT est, sch, con;
END $fn$;

REVOKE ALL ON FUNCTION fundamentals.prune_expectation_snapshots(int) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION fundamentals.prune_expectation_snapshots(int) TO service_role;
