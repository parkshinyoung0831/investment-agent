-- institutional — SEC 13F 사실만 보관한다. 투자 해석·화면 순서·추적 대상 manager
-- 목록(name/fund_name/is_active)은 코드 설정
-- (`investment_agent.data.institutional.managers.MANAGER_CATALOG`)이 소유한다.
-- manager는 SEC 사실이 아니라 우리가 고른 추적 대상이므로 여기 테이블로 두지 않는다.

CREATE SCHEMA IF NOT EXISTS institutional;
REVOKE ALL ON SCHEMA institutional FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA institutional TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA institutional REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA institutional GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA institutional GRANT SELECT ON TABLES TO anon, authenticated;

CREATE TABLE IF NOT EXISTS institutional.filings (
  accession_no text PRIMARY KEY CHECK (accession_no ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'),
  -- manager_cik은 코드 설정의 MANAGER_CATALOG 키와 맞아야 하지만, manager가
  -- Supabase 테이블이 아니므로 FK로 강제하지 않고 형식만 검증한다.
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
CREATE INDEX IF NOT EXISTS filings_manager_period_accepted_idx ON institutional.filings (manager_cik, period_end, accepted_at, accession_no);

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

ALTER TABLE institutional.filings ENABLE ROW LEVEL SECURITY;
ALTER TABLE institutional.positions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS filings_read ON institutional.filings;
DROP POLICY IF EXISTS positions_read ON institutional.positions;
CREATE POLICY filings_read ON institutional.filings FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY positions_read ON institutional.positions FOR SELECT TO anon, authenticated USING (true);
