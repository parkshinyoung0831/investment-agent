-- 수집 실행 상태는 intelligence 분석 데이터가 아니라 local runtime SQLite가 보관한다.
CREATE TABLE IF NOT EXISTS content_files (
  domain VARCHAR NOT NULL CHECK (domain IN ('news', 'social')),
  partition_date DATE NOT NULL,
  path VARCHAR PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS content_catalog_state (
  version INTEGER PRIMARY KEY
);
