-- fundamentals — SEC 공시에서 나온 재무 사실과 시장이 기대한 실적.
--
-- ## 세 가지 시각을 구분한다
--
-- `filing_date`는 SEC에 제출된 날, `available_at`은 우리가 그 공시를 손에 넣은 시각,
-- `period_end`는 숫자가 설명하는 회계기간의 끝이다. 섞으면 backtest가 제출 당일(또는 기간
-- 말일)에 이미 알았다고 가정한다. 운영 재현(PIT)은 `available_at`으로 자른다.
--
-- ## 재무는 공시 버전으로 쌓는다
--
-- 같은 회계기간을 정정 공시가 다시 보고하면 새 행을 더한다. "지금 최신 값"은
-- `fundamentals.financials` 뷰가, "그때 알 수 있던 값"은 버전 표를 cutoff로 잘라 답한다.
--
-- ## 예상치·일정은 바뀔 때만 새 행이다
--
-- 매일 같은 컨센서스를 한 행씩 쌓으면 대부분이 반복이다(관측 예상치 67%, 일정 76%). 직전
-- 상태와 다를 때만 새 행을 넣고, 같으면 그 행의 `last_seen_at`만 옮긴다. 값이 A→B→A로
-- 돌아온 사건은 세 행으로 남는다. "값이 안 바뀌었다"와 "수집이 실패했다"는
-- `last_seen_at`으로 구별한다.
--
-- 회계기간은 표마다 (fiscal_year, fiscal_period, period_end) 자연키로 둔다. 기간 표를 따로
-- 두고 모든 표가 ID로 참조하게 하면 적재 순서·ID 조회가 늘지만 얻는 것은 작다.

CREATE SCHEMA IF NOT EXISTS fundamentals;

REVOKE ALL ON SCHEMA fundamentals FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA fundamentals TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA fundamentals REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA fundamentals GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA fundamentals REVOKE ALL ON FUNCTIONS FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA fundamentals GRANT EXECUTE ON FUNCTIONS TO service_role;


-- numeric 배열에 NaN/Infinity가 섞였는지 본다. numeric은 'NaN'을 값으로 받는데, 그 한 행이
-- SUM·AVG를 통째로 NaN으로 만들고 그 결과는 예외 없이 카드에 실린다.
-- 인자 이름이 `values`면 안 된다 — Postgres 예약어라 본문에서 그대로 못 쓴다.
CREATE OR REPLACE FUNCTION fundamentals.is_finite_numbers(numbers numeric[])
RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path = '' AS $fn$
  SELECT NOT EXISTS (
    SELECT 1 FROM pg_catalog.unnest(numbers) AS v
    WHERE v IS NOT NULL
      AND (v = 'NaN'::numeric OR v = 'Infinity'::numeric OR v = '-Infinity'::numeric)
  );
$fn$;
COMMENT ON FUNCTION fundamentals.is_finite_numbers(numeric[]) IS 'numeric 배열에 NaN·무한대가 없으면 true. CHECK 제약용.';


-- ── 공시 ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fundamentals.filings (
  accession_no text NOT NULL PRIMARY KEY
               CHECK (accession_no ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'),
  cik          text NOT NULL REFERENCES universe.entities(cik),
  form_type    text NOT NULL CHECK (form_type IN ('10-Q', '10-Q/A', '10-K', '10-K/A', '8-K')),
  filing_date  date NOT NULL,
  report_date  date,
  available_at timestamptz NOT NULL DEFAULT now(),
  source       text NOT NULL CHECK (btrim(source) <> '')
);

CREATE INDEX IF NOT EXISTS filings_cik_filed_idx
  ON fundamentals.filings (cik, filing_date DESC);
CREATE INDEX IF NOT EXISTS filings_available_idx
  ON fundamentals.filings (available_at);

COMMENT ON TABLE fundamentals.filings IS 'SEC 공시 하나 = 한 행. "어떤 공시가 존재하는가"라는 사실이며, 처리 결과는 filing_processing이 갖는다.';
COMMENT ON COLUMN fundamentals.filings.accession_no IS 'SEC 공시 접수번호(0000320193-26-000071). 공시의 영구 식별자.';
COMMENT ON COLUMN fundamentals.filings.cik IS '공시를 제출한 CIK. 승계가 있어도 원래 제출자를 바꾸지 않는다.';
COMMENT ON COLUMN fundamentals.filings.form_type IS '공시 양식(10-Q/10-K와 정정본, 8-K).';
COMMENT ON COLUMN fundamentals.filings.filing_date IS 'SEC 제출일(ET 날짜).';
COMMENT ON COLUMN fundamentals.filings.report_date IS '공시가 보고하는 기간의 말일(SEC reportDate). 없으면 NULL.';
COMMENT ON COLUMN fundamentals.filings.available_at IS '우리 수집기가 이 공시를 처음 손에 넣은 시각. 운영 재현(PIT)의 경계다. 백필로 받은 과거 공시는 백필한 시각이다.';
COMMENT ON COLUMN fundamentals.filings.source IS '공시 목록을 알려 준 원천(sec_submissions 등).';


CREATE TABLE IF NOT EXISTS fundamentals.filing_processing (
  accession_no    text NOT NULL REFERENCES fundamentals.filings(accession_no) ON DELETE CASCADE,
  content_type    text NOT NULL CHECK (content_type IN ('company', 'segments')),
  mapping_version text NOT NULL,
  status          text NOT NULL CHECK (status IN ('parsed', 'empty', 'unsupported', 'superseded')),
  facts_count     int  NOT NULL DEFAULT 0 CHECK (facts_count >= 0),
  rows_count      int  NOT NULL DEFAULT 0 CHECK (rows_count >= 0),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (accession_no, content_type, mapping_version),
  CONSTRAINT filing_processing_shape_check CHECK (
    (status = 'parsed'      AND facts_count > 0 AND rows_count > 0)
    OR (status = 'empty'       AND facts_count = 0 AND rows_count = 0)
    OR (status = 'unsupported' AND facts_count > 0 AND rows_count = 0)
    OR (status = 'superseded'  AND facts_count = 0 AND rows_count = 0)
  )
);

CREATE INDEX IF NOT EXISTS filing_processing_status_idx
  ON fundamentals.filing_processing (content_type, mapping_version, status);

COMMENT ON TABLE fundamentals.filing_processing IS '공시 하나를 내용 종류·매핑 버전별로 처리한 결과 = 한 행. 재처리 대상 선정은 이 표만 읽는다(중복 처리 방지 원장).';
COMMENT ON COLUMN fundamentals.filing_processing.accession_no IS '처리한 공시.';
COMMENT ON COLUMN fundamentals.filing_processing.content_type IS 'company=기업 전체 재무, segments=세그먼트 재무.';
COMMENT ON COLUMN fundamentals.filing_processing.mapping_version IS '적용한 XBRL 매핑 규칙 버전. 종류마다 어휘가 달라 섞어 읽지 않는다.';
COMMENT ON COLUMN fundamentals.filing_processing.status IS 'parsed=행을 만듦, empty=허용 fact 없음, unsupported=fact는 있으나 규칙상 저장 안 함, superseded=다른 CIK의 같은 기간 공시가 대신함.';
COMMENT ON COLUMN fundamentals.filing_processing.facts_count IS '공시에서 읽은 허용 XBRL fact 수.';
COMMENT ON COLUMN fundamentals.filing_processing.rows_count IS '저장한 행 수.';
COMMENT ON COLUMN fundamentals.filing_processing.updated_at IS '처리 결과를 마지막으로 기록한 시각.';


-- ── 기업 전체 재무 (공시 버전) ───────────────────────────────────────────
-- SEC CompanyFacts는 등록인(CIK) 사실이다. ticker로 펼치는 것은 읽는 쪽이 한다.
CREATE TABLE IF NOT EXISTS fundamentals.financial_versions (
  cik           text NOT NULL REFERENCES universe.entities(cik),
  period_end    date NOT NULL,
  fiscal_year   int  NOT NULL CHECK (fiscal_year BETWEEN 1900 AND 2200),
  fiscal_period text NOT NULL CHECK (fiscal_period IN ('FY','Q1','Q2','Q3','Q4')),
  accession_no  text NOT NULL REFERENCES fundamentals.filings(accession_no) ON DELETE RESTRICT,
  mapping_version text NOT NULL,
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
  -- 은행·금융 핵심 계정
  net_interest_income                          numeric,
  provision_for_credit_losses                  numeric,
  net_loans_and_leases                         numeric,
  total_deposits                               numeric,
  ingested_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cik, period_end, fiscal_period, accession_no, mapping_version)
);

CREATE INDEX IF NOT EXISTS financial_versions_accession_idx
  ON fundamentals.financial_versions (accession_no);

COMMENT ON TABLE fundamentals.financial_versions IS
  '회사(CIK) 하나의 회계기간 하나를 공시 하나가 매핑 버전 하나로 보고한 재무 값 = 한 행. 정정 공시는 새 행이며 이전 수치를 지우지 않는다. 최신 값은 fundamentals.financials 뷰.';
COMMENT ON COLUMN fundamentals.financial_versions.cik IS '보고 주체 CIK.';
COMMENT ON COLUMN fundamentals.financial_versions.period_end IS '회계기간 말일.';
COMMENT ON COLUMN fundamentals.financial_versions.fiscal_year IS '회사 회계연도(달력 연도가 아닐 수 있다).';
COMMENT ON COLUMN fundamentals.financial_versions.fiscal_period IS 'FY=연간, Q1~Q4=분기. Q4는 FY에서 Q1~Q3를 뺀 값일 수 있다.';
COMMENT ON COLUMN fundamentals.financial_versions.accession_no IS '이 값을 보고한 공시. 행의 대표 근거이며 항목별 채택 근거는 처리 manifest에 있다.';
COMMENT ON COLUMN fundamentals.financial_versions.mapping_version IS 'XBRL 개념→컬럼 매핑 규칙 버전(gaap_concepts.SEMANTIC_POLICY_VERSION). 버전이 다른 행을 한 시계열에 섞지 않는다.';
COMMENT ON COLUMN fundamentals.financial_versions.revenue IS '매출(USD). 모르면 NULL — 0으로 채우지 않는다. 아래 금액 컬럼은 모두 보고 통화(USD) 원 단위다.';
COMMENT ON COLUMN fundamentals.financial_versions.eps_basic_gaap IS 'GAAP 기본 주당순이익(USD/주).';
COMMENT ON COLUMN fundamentals.financial_versions.eps_diluted_gaap IS 'GAAP 희석 주당순이익(USD/주).';
COMMENT ON COLUMN fundamentals.financial_versions.dividends_declared_per_share IS '주당 선언 배당(USD/주).';
COMMENT ON COLUMN fundamentals.financial_versions.liabilities IS '총부채. is_liabilities_derived가 true면 자산-자본으로 계산한 값이다.';
COMMENT ON COLUMN fundamentals.financial_versions.is_liabilities_derived IS 'liabilities를 공시가 직접 보고하지 않아 계산했는가.';
COMMENT ON COLUMN fundamentals.financial_versions.common_equity IS '자본 총계. 범위는 common_equity_scope가 말한다.';
COMMENT ON COLUMN fundamentals.financial_versions.common_equity_scope IS 'common=보통주 자본, stockholders=주주 자본, stockholders_including_nci=비지배지분 포함, unknown=범위 미상.';
COMMENT ON COLUMN fundamentals.financial_versions.mezzanine_equity IS '메자닌(임시) 자본: 상환 가능 비지배지분·우선주. 부채도 영구 자본도 아니다.';
COMMENT ON COLUMN fundamentals.financial_versions.capital_expenses IS '유형자산 취득 현금 지출(양수로 저장).';
COMMENT ON COLUMN fundamentals.financial_versions.shares_average IS '기간 가중평균 기본 주식수(주). 특정일 발행주식수가 아니다.';
COMMENT ON COLUMN fundamentals.financial_versions.shares_fully_diluted_average IS '기간 가중평균 희석 주식수(주).';
COMMENT ON COLUMN fundamentals.financial_versions.cost_of_goods_and_services_sold IS '매출원가.';
COMMENT ON COLUMN fundamentals.financial_versions.gross_profit IS '매출총이익(보고값). 매출-원가로 계산한 값과 다를 수 있다.';
COMMENT ON COLUMN fundamentals.financial_versions.research_and_development_expenses IS '연구개발비.';
COMMENT ON COLUMN fundamentals.financial_versions.selling_general_and_admin_expenses IS '판매관리비.';
COMMENT ON COLUMN fundamentals.financial_versions.operating_income_loss IS '영업이익(손실은 음수).';
COMMENT ON COLUMN fundamentals.financial_versions.interest_expense IS '이자비용.';
COMMENT ON COLUMN fundamentals.financial_versions.pretax_income_loss IS '법인세차감전이익.';
COMMENT ON COLUMN fundamentals.financial_versions.income_taxes IS '법인세비용.';
COMMENT ON COLUMN fundamentals.financial_versions.net_income IS '당기순이익(비지배지분 포함 여부는 회사 보고 범위를 따른다).';
COMMENT ON COLUMN fundamentals.financial_versions.minority_interest_income IS '비지배지분 귀속 순이익.';
COMMENT ON COLUMN fundamentals.financial_versions.net_income_to_common_shareholders IS '보통주주 귀속 순이익. net_income과 귀속 범위가 다르다.';
COMMENT ON COLUMN fundamentals.financial_versions.assets IS '총자산.';
COMMENT ON COLUMN fundamentals.financial_versions.current_assets_total IS '유동자산.';
COMMENT ON COLUMN fundamentals.financial_versions.cash_and_cash_equivalents IS '현금및현금성자산.';
COMMENT ON COLUMN fundamentals.financial_versions.short_term_investments IS '단기투자자산. 현금과 합치지 않는다.';
COMMENT ON COLUMN fundamentals.financial_versions.trade_receivables IS '매출채권.';
COMMENT ON COLUMN fundamentals.financial_versions.inventories IS '재고자산.';
COMMENT ON COLUMN fundamentals.financial_versions.property_plant_equipment_net IS '유형자산(순액).';
COMMENT ON COLUMN fundamentals.financial_versions.goodwill IS '영업권.';
COMMENT ON COLUMN fundamentals.financial_versions.intangible_assets_excluding_goodwill IS '영업권 제외 무형자산.';
COMMENT ON COLUMN fundamentals.financial_versions.operating_lease_right_of_use_asset IS '운용리스 사용권자산.';
COMMENT ON COLUMN fundamentals.financial_versions.current_liabilities_total IS '유동부채.';
COMMENT ON COLUMN fundamentals.financial_versions.trade_payables IS '매입채무.';
COMMENT ON COLUMN fundamentals.financial_versions.short_term_debt IS '단기차입금.';
COMMENT ON COLUMN fundamentals.financial_versions.current_portion_of_long_term_debt IS '유동성 장기부채.';
COMMENT ON COLUMN fundamentals.financial_versions.long_term_debt IS '장기부채(비유동).';
COMMENT ON COLUMN fundamentals.financial_versions.total_debt_including_current IS '유동분 포함 총차입(보고값). 리스는 포함하지 않는다.';
COMMENT ON COLUMN fundamentals.financial_versions.operating_lease_current_debt_equivalent IS '운용리스 부채(유동).';
COMMENT ON COLUMN fundamentals.financial_versions.operating_lease_non_current_debt_equivalent IS '운용리스 부채(비유동).';
COMMENT ON COLUMN fundamentals.financial_versions.minority_interest_balance IS '비지배지분(대차대조표 잔액).';
COMMENT ON COLUMN fundamentals.financial_versions.preferred_stock IS '우선주 자본.';
COMMENT ON COLUMN fundamentals.financial_versions.retained_earnings IS '이익잉여금.';
COMMENT ON COLUMN fundamentals.financial_versions.net_cash_from_operating_activities IS '영업활동 현금흐름.';
COMMENT ON COLUMN fundamentals.financial_versions.net_cash_from_investing_activities IS '투자활동 현금흐름.';
COMMENT ON COLUMN fundamentals.financial_versions.net_cash_from_financing_activities IS '재무활동 현금흐름.';
COMMENT ON COLUMN fundamentals.financial_versions.depreciation_amortization_cf IS '현금흐름표의 감가상각·상각비.';
COMMENT ON COLUMN fundamentals.financial_versions.stock_based_compensation_cf IS '현금흐름표의 주식보상비용.';
COMMENT ON COLUMN fundamentals.financial_versions.acquisitions_net_of_cash IS '인수 대가(취득 현금 차감). capex와 합치지 않는다.';
COMMENT ON COLUMN fundamentals.financial_versions.stock_repurchase_payments IS '자사주 매입 지출.';
COMMENT ON COLUMN fundamentals.financial_versions.common_dividends_paid IS '보통주 배당 지급액.';
COMMENT ON COLUMN fundamentals.financial_versions.long_term_debt_issued IS '장기부채 발행 유입.';
COMMENT ON COLUMN fundamentals.financial_versions.long_term_debt_repaid IS '장기부채 상환 지출.';
COMMENT ON COLUMN fundamentals.financial_versions.net_interest_income IS '순이자이익(은행).';
COMMENT ON COLUMN fundamentals.financial_versions.provision_for_credit_losses IS '신용손실 충당금 전입(은행).';
COMMENT ON COLUMN fundamentals.financial_versions.net_loans_and_leases IS '순대출·리스 채권(은행).';
COMMENT ON COLUMN fundamentals.financial_versions.total_deposits IS '총예금(은행).';
COMMENT ON COLUMN fundamentals.financial_versions.ingested_at IS '이 버전 행을 처음 저장한 시각. 같은 공시를 새 매핑 버전으로 재처리하면 더 늦은 시각의 행이 생긴다.';

-- 기간마다 가장 최근 공시(같으면 가장 늦게 처리한 매핑)의 값. "지금 알고 있는 최신 재무"다.
-- 과거 시점에 알던 값이 필요하면 이 뷰가 아니라 financial_versions를 cutoff로 자른다.
CREATE OR REPLACE VIEW fundamentals.financials WITH (security_invoker = true) AS
SELECT DISTINCT ON (v.cik, v.period_end, v.fiscal_period)
  v.*,
  f.filing_date,
  f.form_type,
  f.available_at
FROM fundamentals.financial_versions v
JOIN fundamentals.filings f ON f.accession_no = v.accession_no
ORDER BY v.cik, v.period_end, v.fiscal_period, f.filing_date DESC, v.accession_no DESC, v.ingested_at DESC;
COMMENT ON VIEW fundamentals.financials IS '회계기간마다 최신 공시 버전 한 행. 정정이 반영된 현재 값이며 PIT 조회에 쓰지 않는다.';


-- ── 주식수 스냅샷 ─────────────────────────────────────────────────────────
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
  CONSTRAINT share_class_dimension_shape_check
    CHECK ((share_class_axis IS NULL) = (share_class_member IS NULL)),
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
CREATE INDEX IF NOT EXISTS share_class_accession_idx
  ON fundamentals.share_class_snapshots (accession_no);

COMMENT ON TABLE fundamentals.share_class_snapshots IS '공시 표지에 적힌 주식 클래스 하나의 특정일 발행주식수 = 한 행. 시가총액 계산의 분자다.';
COMMENT ON COLUMN fundamentals.share_class_snapshots.cik IS '발행사 CIK.';
COMMENT ON COLUMN fundamentals.share_class_snapshots.share_class_key IS '클래스 식별 키(축·멤버 조합 또는 단일 클래스 기본값).';
COMMENT ON COLUMN fundamentals.share_class_snapshots.share_class_axis IS 'XBRL 클래스 축. 단일 클래스면 NULL.';
COMMENT ON COLUMN fundamentals.share_class_snapshots.share_class_member IS 'XBRL 클래스 멤버. 단일 클래스면 NULL.';
COMMENT ON COLUMN fundamentals.share_class_snapshots.share_class_title IS '클래스 이름(사람이 읽는 표기).';
COMMENT ON COLUMN fundamentals.share_class_snapshots.mapped_security_id IS '이 클래스가 붙은 상장 종목. 확정하지 못하면 NULL(사유는 ticker_mapping_status).';
COMMENT ON COLUMN fundamentals.share_class_snapshots.as_of_date IS '주식수가 말하는 날짜(표지 기준일). 공시일과 다르다.';
COMMENT ON COLUMN fundamentals.share_class_snapshots.shares_outstanding IS '발행주식수(주).';
COMMENT ON COLUMN fundamentals.share_class_snapshots.accession_no IS '이 값을 보고한 공시.';
COMMENT ON COLUMN fundamentals.share_class_snapshots.source_concept IS '값을 읽은 XBRL 개념.';
COMMENT ON COLUMN fundamentals.share_class_snapshots.ticker_mapping_status IS '종목 연결 방식 또는 연결 실패 사유.';
COMMENT ON COLUMN fundamentals.share_class_snapshots.ingested_at IS '저장한 시각.';


-- ── 세그먼트 재무 ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fundamentals.segment_metrics (
  cik                   text NOT NULL REFERENCES universe.entities(cik),
  accession_no          text NOT NULL REFERENCES fundamentals.filings(accession_no) ON DELETE CASCADE,
  fiscal_year           int  NOT NULL CHECK (fiscal_year BETWEEN 1900 AND 2200),
  fiscal_period         text NOT NULL CHECK (fiscal_period IN ('FY','Q1','Q2','Q3','Q4')),
  period_end            date NOT NULL,
  segment_hash          text NOT NULL CHECK (segment_hash ~ '^[0-9a-f]{40}$'),
  segment_type          text NOT NULL CHECK (segment_type IN ('business','product','geographic')),
  axis                  text NOT NULL CHECK (btrim(axis) <> ''),
  member                text NOT NULL CHECK (btrim(member) <> ''),
  secondary_axis        text,
  secondary_member      text,
  is_derived            boolean NOT NULL DEFAULT false,
  revenue               numeric,
  quality_status        text CHECK (quality_status IN ('verified','partial')),
  coverage_ratio        numeric,
  profit_loss           numeric,
  profit_measure_kind   text,
  profit_quality_status text CHECK (profit_quality_status IN ('verified','partial')),
  assets                numeric,
  assets_quality_status text CHECK (assets_quality_status IN ('verified','partial')),
  ingested_at           timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cik, accession_no, fiscal_year, fiscal_period, segment_hash),
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
CREATE INDEX IF NOT EXISTS segment_metrics_accession_idx
  ON fundamentals.segment_metrics (accession_no);

COMMENT ON TABLE fundamentals.segment_metrics IS '공시 하나가 보고한 회계기간 하나의 세그먼트(축·멤버, 2차 축까지) 하나 값 = 한 행. 공시별로 쌓여 정정이 이전 값을 지우지 않는다.';
COMMENT ON COLUMN fundamentals.segment_metrics.cik IS '보고 주체 CIK.';
COMMENT ON COLUMN fundamentals.segment_metrics.accession_no IS '이 값을 보고한 공시.';
COMMENT ON COLUMN fundamentals.segment_metrics.fiscal_year IS '회사 회계연도.';
COMMENT ON COLUMN fundamentals.segment_metrics.fiscal_period IS 'FY 또는 Q1~Q4.';
COMMENT ON COLUMN fundamentals.segment_metrics.period_end IS '회계기간 말일.';
COMMENT ON COLUMN fundamentals.segment_metrics.segment_hash IS '축·멤버 조합의 SHA-1 지문(PK용).';
COMMENT ON COLUMN fundamentals.segment_metrics.segment_type IS 'business=사업부, product=제품군, geographic=지역.';
COMMENT ON COLUMN fundamentals.segment_metrics.axis IS 'XBRL 1차 축 이름.';
COMMENT ON COLUMN fundamentals.segment_metrics.member IS 'XBRL 1차 멤버 이름.';
COMMENT ON COLUMN fundamentals.segment_metrics.secondary_axis IS '2차 축. 1차원 분할이면 NULL.';
COMMENT ON COLUMN fundamentals.segment_metrics.secondary_member IS '2차 멤버. 1차원 분할이면 NULL.';
COMMENT ON COLUMN fundamentals.segment_metrics.is_derived IS '회사가 보고한 값이 아니라 FY에서 Q1~Q3를 빼는 식으로 계산한 값인가.';
COMMENT ON COLUMN fundamentals.segment_metrics.revenue IS '세그먼트 매출(USD).';
COMMENT ON COLUMN fundamentals.segment_metrics.quality_status IS '매출 품질: verified=합계와 맞음, partial=일부만 덮음.';
COMMENT ON COLUMN fundamentals.segment_metrics.coverage_ratio IS '1차원 분할 매출 합이 전사 매출을 덮는 비율(1=100%). 2차원 행은 NULL.';
COMMENT ON COLUMN fundamentals.segment_metrics.profit_loss IS '세그먼트 이익(USD). 어떤 이익인지는 profit_measure_kind.';
COMMENT ON COLUMN fundamentals.segment_metrics.profit_measure_kind IS '이익 정의(영업·세전·순·매출총 등).';
COMMENT ON COLUMN fundamentals.segment_metrics.profit_quality_status IS '이익 값 품질.';
COMMENT ON COLUMN fundamentals.segment_metrics.assets IS '세그먼트 자산(USD).';
COMMENT ON COLUMN fundamentals.segment_metrics.assets_quality_status IS '자산 값 품질.';
COMMENT ON COLUMN fundamentals.segment_metrics.ingested_at IS '저장한 시각.';


-- ── 실적 실제치 (8-K 보도자료) ────────────────────────────────────────────
-- 예상치는 여기 저장하지 않는다. 서프라이즈를 계산해 저장하면 컨센서스가 갱신될 때 과거
-- 서프라이즈가 조용히 흔들린다 — reporting 뷰가 조회 시점에 만든다.
CREATE TABLE IF NOT EXISTS fundamentals.earnings_results (
  cik                     text NOT NULL REFERENCES universe.entities(cik),
  accession_no            text NOT NULL REFERENCES fundamentals.filings(accession_no) ON DELETE CASCADE,
  fiscal_year             int  NOT NULL CHECK (fiscal_year BETWEEN 1900 AND 2200),
  fiscal_period           text NOT NULL CHECK (fiscal_period IN ('Q1','Q2','Q3','Q4','FY')),
  period_end              date NOT NULL,
  revenue_actual          numeric,
  eps_actual              numeric,
  eps_basis               text NOT NULL DEFAULT 'unknown'
                          CHECK (eps_basis IN ('gaap_diluted', 'gaap_basic', 'adjusted', 'unknown')),
  currency                text CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
  operating_income_actual numeric,
  net_income_actual       numeric,
  guidance_summary        text,
  press_release_url       text,
  source                  text NOT NULL DEFAULT 'sec_8k' CHECK (btrim(source) <> ''),
  collected_at            timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cik, fiscal_year, fiscal_period, accession_no),
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
CREATE INDEX IF NOT EXISTS earnings_results_accession_idx
  ON fundamentals.earnings_results (accession_no);

COMMENT ON TABLE fundamentals.earnings_results IS '실적 발표(8-K Item 2.02) 하나가 알린 회계기간 하나의 실제치 = 한 행. 정식 재무(10-Q/K)보다 먼저 오는 속보 값이다.';
COMMENT ON COLUMN fundamentals.earnings_results.cik IS '발행사 CIK.';
COMMENT ON COLUMN fundamentals.earnings_results.accession_no IS '보도자료가 첨부된 8-K 공시. 공개 시각은 filings.available_at·filing_date.';
COMMENT ON COLUMN fundamentals.earnings_results.fiscal_year IS '회사 회계연도.';
COMMENT ON COLUMN fundamentals.earnings_results.fiscal_period IS '발표 대상 기간.';
COMMENT ON COLUMN fundamentals.earnings_results.period_end IS '대상 기간 말일.';
COMMENT ON COLUMN fundamentals.earnings_results.revenue_actual IS '발표 매출(currency 원 단위).';
COMMENT ON COLUMN fundamentals.earnings_results.eps_actual IS '발표 EPS(currency/주). 어떤 EPS인지는 eps_basis.';
COMMENT ON COLUMN fundamentals.earnings_results.eps_basis IS 'EPS 정의: gaap_diluted/gaap_basic/adjusted, 보도자료에서 확정 못 하면 unknown. 서프라이즈는 같은 정의끼리만 비교한다.';
COMMENT ON COLUMN fundamentals.earnings_results.currency IS '보고 통화(ISO 4217). 확인 못 하면 NULL.';
COMMENT ON COLUMN fundamentals.earnings_results.operating_income_actual IS '발표 영업이익.';
COMMENT ON COLUMN fundamentals.earnings_results.net_income_actual IS '발표 순이익.';
COMMENT ON COLUMN fundamentals.earnings_results.guidance_summary IS '보도자료의 가이던스 한 줄 원문. 해석하지 않은 문장이다.';
COMMENT ON COLUMN fundamentals.earnings_results.press_release_url IS '보도자료 원문 URL.';
COMMENT ON COLUMN fundamentals.earnings_results.source IS '추출 원천(sec_8k).';
COMMENT ON COLUMN fundamentals.earnings_results.collected_at IS '추출해 저장한 시각.';


-- ── 시장 예상치 (상태 변경 버전) ─────────────────────────────────────────
-- 상대 horizon(q+0·fy+1)으로 오는 값을 회사 회계력의 절대 연도·분기로 고정해 저장한다.
-- 상대 좌표로 두면 분기가 넘어가는 순간 같은 행이 다른 기간을 가리킨다.
CREATE TABLE IF NOT EXISTS fundamentals.earnings_estimates (
  security_id          integer NOT NULL REFERENCES universe.securities(security_id) ON DELETE RESTRICT,
  target_fiscal_year   int  NOT NULL CHECK (target_fiscal_year BETWEEN 1900 AND 2200),
  target_fiscal_period text NOT NULL CHECK (target_fiscal_period IN ('Q1','Q2','Q3','Q4','FY')),
  target_period_end    date NOT NULL,
  source               text NOT NULL CHECK (btrim(source) <> ''),
  snapshot_kind        text NOT NULL CHECK (snapshot_kind IN (
                         'captured_live', 'vendor_pit', 'reconstructed', 'latest_history')),
  snapshot_date        date NOT NULL,
  eps_basis            text NOT NULL DEFAULT 'unknown'
                       CHECK (eps_basis IN ('gaap_diluted', 'gaap_basic', 'adjusted', 'unknown')),
  currency             text CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
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
  last_seen_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (security_id, target_fiscal_year, target_fiscal_period, source, snapshot_kind, snapshot_date),
  CONSTRAINT estimates_range_check CHECK (
    (eps_low     IS NULL OR eps_high     IS NULL OR eps_low     <= eps_high)
    AND (revenue_low IS NULL OR revenue_high IS NULL OR revenue_low <= revenue_high)
  ),
  CONSTRAINT estimates_has_value_check CHECK (eps_avg IS NOT NULL OR revenue_avg IS NOT NULL),
  CONSTRAINT estimates_not_from_the_future_check
    CHECK (snapshot_date <= (collected_at AT TIME ZONE 'America/New_York')::date),
  CONSTRAINT estimates_seen_order_check CHECK (last_seen_at >= collected_at),
  CONSTRAINT estimates_finite_check CHECK (
    fundamentals.is_finite_numbers(
      ARRAY[eps_avg, eps_low, eps_high, revenue_avg, revenue_low, revenue_high])
  )
);

CREATE INDEX IF NOT EXISTS estimates_asof_idx
  ON fundamentals.earnings_estimates
     (security_id, target_fiscal_year, target_fiscal_period, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS estimates_period_end_idx
  ON fundamentals.earnings_estimates (security_id, target_period_end, snapshot_date DESC);

COMMENT ON TABLE fundamentals.earnings_estimates IS
  '종목 하나·대상 회계기간 하나·원천·수집 성격별 컨센서스 상태 하나 = 한 행. 상태가 바뀔 때만 새 행이고 같은 상태가 다시 보이면 last_seen_at만 옮긴다.';
COMMENT ON COLUMN fundamentals.earnings_estimates.security_id IS '종목 ID. 주당 값이라 클래스 단위다.';
COMMENT ON COLUMN fundamentals.earnings_estimates.target_fiscal_year IS '예상 대상 회계연도(회사 회계력의 절대값).';
COMMENT ON COLUMN fundamentals.earnings_estimates.target_fiscal_period IS '예상 대상 기간.';
COMMENT ON COLUMN fundamentals.earnings_estimates.target_period_end IS '대상 기간 말일. 미래 기간은 회사 회계력에서 추정한 날짜일 수 있다.';
COMMENT ON COLUMN fundamentals.earnings_estimates.source IS '예상치 공급자(yfinance 등).';
COMMENT ON COLUMN fundamentals.earnings_estimates.snapshot_kind IS 'captured_live=그날 우리가 직접 수집, vendor_pit=공급자가 당시 값임을 보장한 과거 자료, reconstructed=현재 API의 발표 이력에서 되살린 값(발표 전 비교에 쓰지 않음), latest_history=당시 값 보장이 없는 과거 요약. 섞어 읽으면 PIT가 깨진다.';
COMMENT ON COLUMN fundamentals.earnings_estimates.snapshot_date IS '이 상태가 유효해진 날짜(ET): captured_live는 처음 관측한 날, 과거 자료는 원천이 말하는 날.';
COMMENT ON COLUMN fundamentals.earnings_estimates.eps_basis IS 'EPS 예상의 정의. 공급자가 밝히지 않으면 unknown.';
COMMENT ON COLUMN fundamentals.earnings_estimates.currency IS '예상치 통화(ISO 4217). 모르면 NULL.';
COMMENT ON COLUMN fundamentals.earnings_estimates.eps_avg IS '애널리스트 EPS 예상 평균(currency/주).';
COMMENT ON COLUMN fundamentals.earnings_estimates.eps_low IS 'EPS 예상 최저.';
COMMENT ON COLUMN fundamentals.earnings_estimates.eps_high IS 'EPS 예상 최고.';
COMMENT ON COLUMN fundamentals.earnings_estimates.eps_analysts IS 'EPS 예상에 참여한 애널리스트 수. 매출 참여자와 다를 수 있다.';
COMMENT ON COLUMN fundamentals.earnings_estimates.revenue_avg IS '매출 예상 평균(currency 원 단위).';
COMMENT ON COLUMN fundamentals.earnings_estimates.revenue_low IS '매출 예상 최저.';
COMMENT ON COLUMN fundamentals.earnings_estimates.revenue_high IS '매출 예상 최고.';
COMMENT ON COLUMN fundamentals.earnings_estimates.revenue_analysts IS '매출 예상 애널리스트 수.';
COMMENT ON COLUMN fundamentals.earnings_estimates.revisions_up_7d IS '최근 7일 EPS 상향 건수(공급자 집계).';
COMMENT ON COLUMN fundamentals.earnings_estimates.revisions_up_30d IS '최근 30일 EPS 상향 건수.';
COMMENT ON COLUMN fundamentals.earnings_estimates.revisions_down_7d IS '최근 7일 EPS 하향 건수.';
COMMENT ON COLUMN fundamentals.earnings_estimates.revisions_down_30d IS '최근 30일 EPS 하향 건수.';
COMMENT ON COLUMN fundamentals.earnings_estimates.collected_at IS '이 상태를 처음 저장한 시각. 발표 전에 알았는지를 가르는 경계다.';
COMMENT ON COLUMN fundamentals.earnings_estimates.last_seen_at IS '이 상태를 마지막으로 다시 확인한 시각. 값이 안 바뀐 것과 수집이 멈춘 것을 구별한다.';


-- ── 발표 예정 (상태 변경 버전) ────────────────────────────────────────────
-- 예정일은 자주 바뀌고, 바뀌었다는 사실 자체가 신호다. 저장하는 사실은 시각 하나이고
-- ET 날짜는 감시 창 조회용 인덱스를 위해 계산해 둔다(KST로 읽으면 하루 밀려 보인다).
CREATE TABLE IF NOT EXISTS fundamentals.earnings_schedule_versions (
  security_id          integer NOT NULL REFERENCES universe.securities(security_id) ON DELETE RESTRICT,
  target_fiscal_year   int  NOT NULL CHECK (target_fiscal_year BETWEEN 1900 AND 2200),
  target_fiscal_period text NOT NULL CHECK (target_fiscal_period IN ('Q1','Q2','Q3','Q4')),
  target_period_end    date NOT NULL,
  source               text NOT NULL CHECK (btrim(source) <> ''),
  snapshot_date        date NOT NULL,
  expected_report_at   timestamptz NOT NULL,
  expected_report_date date GENERATED ALWAYS AS
                       ((expected_report_at AT TIME ZONE 'America/New_York')::date) STORED,
  expected_session     text NOT NULL DEFAULT 'unknown'
                       CHECK (expected_session IN ('bmo','amc','dmh','unknown')),
  is_estimated         boolean,
  collected_at         timestamptz NOT NULL DEFAULT now(),
  last_seen_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (security_id, target_fiscal_year, target_fiscal_period, source, snapshot_date),
  CONSTRAINT schedule_order_check CHECK (
    target_period_end <= (expected_report_at AT TIME ZONE 'America/New_York')::date
    AND snapshot_date <= (collected_at AT TIME ZONE 'America/New_York')::date
    AND last_seen_at >= collected_at
  )
);

CREATE INDEX IF NOT EXISTS schedule_session_idx
  ON fundamentals.earnings_schedule_versions (expected_report_date, expected_session);

COMMENT ON TABLE fundamentals.earnings_schedule_versions IS
  '종목 하나·대상 분기 하나·원천별 발표 예정 상태 하나 = 한 행. 예정 시각·세션·추정 여부가 바뀔 때만 새 행이다.';
COMMENT ON COLUMN fundamentals.earnings_schedule_versions.security_id IS '종목 ID(원천이 종목 단위로 알려 준다).';
COMMENT ON COLUMN fundamentals.earnings_schedule_versions.target_fiscal_year IS '발표 대상 회계연도.';
COMMENT ON COLUMN fundamentals.earnings_schedule_versions.target_fiscal_period IS '발표 대상 분기.';
COMMENT ON COLUMN fundamentals.earnings_schedule_versions.target_period_end IS '대상 분기 말일(추정일 수 있다).';
COMMENT ON COLUMN fundamentals.earnings_schedule_versions.source IS '일정 원천(yfinance 등).';
COMMENT ON COLUMN fundamentals.earnings_schedule_versions.snapshot_date IS '이 일정 상태를 처음 관측한 날짜(ET).';
COMMENT ON COLUMN fundamentals.earnings_schedule_versions.expected_report_at IS '예정 발표 시각(UTC 저장).';
COMMENT ON COLUMN fundamentals.earnings_schedule_versions.expected_report_date IS 'expected_report_at의 ET 날짜(계산 컬럼).';
COMMENT ON COLUMN fundamentals.earnings_schedule_versions.expected_session IS 'bmo=장전, amc=장후, dmh=장중, unknown=미상. 8-K 감시 창을 정한다.';
COMMENT ON COLUMN fundamentals.earnings_schedule_versions.is_estimated IS 'true=추정일, false=회사 확정 공지, NULL=원천이 말하지 않음.';
COMMENT ON COLUMN fundamentals.earnings_schedule_versions.collected_at IS '이 상태를 처음 저장한 시각.';
COMMENT ON COLUMN fundamentals.earnings_schedule_versions.last_seen_at IS '이 상태를 마지막으로 다시 확인한 시각.';


-- ── 애널리스트 커버리지 (상태 변경 버전) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS fundamentals.analyst_consensus_snapshots (
  security_id   integer NOT NULL REFERENCES universe.securities(security_id) ON DELETE RESTRICT,
  source        text NOT NULL CHECK (btrim(source) <> ''),
  snapshot_date date NOT NULL,
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
  last_seen_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (security_id, source, snapshot_date),
  CONSTRAINT consensus_range_check
    CHECK (target_low IS NULL OR target_high IS NULL OR target_low <= target_high),
  CONSTRAINT consensus_has_value_check CHECK (
    num_nonnulls(target_mean, target_median, target_high, target_low,
                 strong_buy, buy, hold, sell, strong_sell) > 0
  ),
  CONSTRAINT consensus_not_from_the_future_check
    CHECK (snapshot_date <= (collected_at AT TIME ZONE 'America/New_York')::date),
  CONSTRAINT consensus_seen_order_check CHECK (last_seen_at >= collected_at),
  CONSTRAINT consensus_finite_check CHECK (
    fundamentals.is_finite_numbers(ARRAY[target_mean, target_median, target_high, target_low])
  )
);

COMMENT ON TABLE fundamentals.analyst_consensus_snapshots IS
  '종목 하나·원천별 목표주가와 투자의견 분포 상태 하나 = 한 행. 실적 컨센서스(earnings_estimates)와 다른 사실이다. 바뀔 때만 새 행이다.';
COMMENT ON COLUMN fundamentals.analyst_consensus_snapshots.security_id IS '종목 ID.';
COMMENT ON COLUMN fundamentals.analyst_consensus_snapshots.source IS '원천(yfinance 등).';
COMMENT ON COLUMN fundamentals.analyst_consensus_snapshots.snapshot_date IS '이 상태를 처음 관측한 날짜(ET).';
COMMENT ON COLUMN fundamentals.analyst_consensus_snapshots.target_mean IS '목표주가 평균(USD).';
COMMENT ON COLUMN fundamentals.analyst_consensus_snapshots.target_median IS '목표주가 중앙값(USD).';
COMMENT ON COLUMN fundamentals.analyst_consensus_snapshots.target_high IS '목표주가 최고(USD).';
COMMENT ON COLUMN fundamentals.analyst_consensus_snapshots.target_low IS '목표주가 최저(USD).';
COMMENT ON COLUMN fundamentals.analyst_consensus_snapshots.strong_buy IS '강력 매수 의견 수.';
COMMENT ON COLUMN fundamentals.analyst_consensus_snapshots.buy IS '매수 의견 수.';
COMMENT ON COLUMN fundamentals.analyst_consensus_snapshots.hold IS '보유 의견 수.';
COMMENT ON COLUMN fundamentals.analyst_consensus_snapshots.sell IS '매도 의견 수.';
COMMENT ON COLUMN fundamentals.analyst_consensus_snapshots.strong_sell IS '강력 매도 의견 수.';
COMMENT ON COLUMN fundamentals.analyst_consensus_snapshots.collected_at IS '이 상태를 처음 저장한 시각.';
COMMENT ON COLUMN fundamentals.analyst_consensus_snapshots.last_seen_at IS '이 상태를 마지막으로 다시 확인한 시각.';


-- ── 권한 ──────────────────────────────────────────────────────────────────
GRANT ALL ON ALL TABLES IN SCHEMA fundamentals TO service_role;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA fundamentals FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA fundamentals TO service_role;

ALTER TABLE fundamentals.filings                     ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.filing_processing           ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.financial_versions          ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.share_class_snapshots       ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.segment_metrics             ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.earnings_results            ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.earnings_estimates          ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.earnings_schedule_versions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE fundamentals.analyst_consensus_snapshots ENABLE ROW LEVEL SECURITY;
