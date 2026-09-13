-- institutional — SEC 13F 사실만 보관한다. 추적할 운용사 목록과 이름·화면 순서는 코드 설정
-- (`investment_agent.data.institutional.managers.MANAGER_CATALOG`)이 소유한다. 운용사는 SEC
-- 사실이 아니라 우리가 고른 추적 대상이라 표로 두지 않는다.
--
-- 보유 종목은 원문 식별자(CUSIP/CINS) 그대로 둔다. 어느 종목인지는 보고 분기말을 기준일로
-- `universe.security_on`이 읽는 시점에 답한다 — 제출일의 현재 ticker를 붙이지 않는다.

CREATE SCHEMA IF NOT EXISTS institutional;

REVOKE ALL ON SCHEMA institutional FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA institutional TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA institutional REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA institutional GRANT ALL ON TABLES TO service_role;

CREATE TABLE IF NOT EXISTS institutional.filings (
  accession_no text PRIMARY KEY CHECK (accession_no ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'),
  manager_cik text NOT NULL CHECK (manager_cik ~ '^[0-9]{10}$'),
  period_end date NOT NULL,
  form_type text NOT NULL CHECK (form_type IN ('13F-HR', '13F-HR/A')),
  report_type text NOT NULL CHECK (btrim(report_type) <> ''),
  filing_date date NOT NULL,
  accepted_at timestamptz NOT NULL,
  amendment_type text CHECK (amendment_type IN ('RESTATEMENT', 'NEW HOLDINGS')),
  amendment_no integer CHECK (amendment_no IS NULL OR amendment_no > 0),
  reported_value_usd numeric NOT NULL CHECK (reported_value_usd >= 0),
  reported_line_count integer NOT NULL CHECK (reported_line_count >= 0),
  confidential_omitted boolean,
  source_url text NOT NULL CHECK (btrim(source_url) <> ''),
  content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  CHECK ((form_type = '13F-HR' AND amendment_type IS NULL AND amendment_no IS NULL)
      OR (form_type = '13F-HR/A' AND amendment_type IS NOT NULL AND amendment_no IS NOT NULL)),
  CHECK (period_end <= filing_date)
);
CREATE INDEX IF NOT EXISTS filings_manager_period_accepted_idx
  ON institutional.filings (manager_cik, period_end, accepted_at, accession_no);

COMMENT ON TABLE institutional.filings IS '운용사 하나의 13F 보고서(원본 또는 정정) 하나 = 한 행. 이 CIK는 발행사가 아니라 보고 운용사다.';
COMMENT ON COLUMN institutional.filings.accession_no IS 'SEC 공시 접수번호.';
COMMENT ON COLUMN institutional.filings.manager_cik IS '보고 운용사 CIK(MANAGER_CATALOG 키).';
COMMENT ON COLUMN institutional.filings.period_end IS '보유를 보고하는 분기말. 종목 식별의 기준일이다.';
COMMENT ON COLUMN institutional.filings.form_type IS '13F-HR=원본, 13F-HR/A=정정.';
COMMENT ON COLUMN institutional.filings.report_type IS '13F 보고 유형(HOLDINGS REPORT 등).';
COMMENT ON COLUMN institutional.filings.filing_date IS 'SEC 제출일.';
COMMENT ON COLUMN institutional.filings.accepted_at IS 'SEC 접수 시각. 공개 시점 판단용.';
COMMENT ON COLUMN institutional.filings.amendment_type IS '정정 유형: RESTATEMENT=전체 대체, NEW HOLDINGS=추가 보고. 원본이면 NULL.';
COMMENT ON COLUMN institutional.filings.amendment_no IS '정정 차수. 원본이면 NULL.';
COMMENT ON COLUMN institutional.filings.reported_value_usd IS '표지에 적힌 총 보유 가치(USD). 행 합계 검증 기준.';
COMMENT ON COLUMN institutional.filings.reported_line_count IS '표지에 적힌 보유 행 수.';
COMMENT ON COLUMN institutional.filings.confidential_omitted IS '기밀 처리로 일부 보유를 뺐다고 표시했는가. 모르면 NULL.';
COMMENT ON COLUMN institutional.filings.source_url IS '보유 표 원문 URL.';
COMMENT ON COLUMN institutional.filings.content_sha256 IS '원문 SHA-256. 같은 원문 재적재를 알아본다.';

CREATE TABLE IF NOT EXISTS institutional.positions (
  accession_no text NOT NULL REFERENCES institutional.filings(accession_no) ON DELETE CASCADE,
  source_row_no integer NOT NULL CHECK (source_row_no > 0),
  issuer_name text NOT NULL CHECK (btrim(issuer_name) <> ''),
  identifier text NOT NULL CHECK (identifier ~ '^[A-Z0-9]{9}$'),
  identifier_type text NOT NULL CHECK (identifier_type IN ('CUSIP', 'CINS')),
  value_usd numeric NOT NULL CHECK (value_usd >= 0),
  quantity bigint NOT NULL CHECK (quantity >= 0),
  quantity_type text NOT NULL CHECK (quantity_type IN ('SH', 'PRN')),
  position_kind text NOT NULL CHECK (position_kind IN ('SHARES', 'PUT', 'CALL')),
  PRIMARY KEY (accession_no, source_row_no)
);
CREATE INDEX IF NOT EXISTS positions_identifier_idx ON institutional.positions (identifier, identifier_type);

COMMENT ON TABLE institutional.positions IS '13F 보유 표의 원문 한 줄 = 한 행. 종목에 연결하지 못한 줄도 그대로 남긴다.';
COMMENT ON COLUMN institutional.positions.accession_no IS '보고서.';
COMMENT ON COLUMN institutional.positions.source_row_no IS '원문 표의 행 번호(1부터).';
COMMENT ON COLUMN institutional.positions.issuer_name IS '원문 발행사명(보고 운용사 표기).';
COMMENT ON COLUMN institutional.positions.identifier IS '원문 식별자(대문자 9자리).';
COMMENT ON COLUMN institutional.positions.identifier_type IS 'CUSIP 또는 CINS.';
COMMENT ON COLUMN institutional.positions.value_usd IS '보유 가치(USD). 원문 표의 값으로, 표지 합계(reported_value_usd)와 같은 단위다.';
COMMENT ON COLUMN institutional.positions.quantity IS '보유 수량(quantity_type 단위).';
COMMENT ON COLUMN institutional.positions.quantity_type IS 'SH=주식 수, PRN=채권 원금.';
COMMENT ON COLUMN institutional.positions.position_kind IS 'SHARES=현물, PUT/CALL=옵션.';

GRANT ALL ON ALL TABLES IN SCHEMA institutional TO service_role;

ALTER TABLE institutional.filings ENABLE ROW LEVEL SECURITY;
ALTER TABLE institutional.positions ENABLE ROW LEVEL SECURITY;
