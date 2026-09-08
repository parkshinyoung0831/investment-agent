-- 본문·제목·요약은 날짜 파티션 Parquet에 한 번만 저장한다. 이 표는 중복 제거,
-- retention, mention의 부모 확인에 필요한 작은 metadata index만 가진다.
--
-- 뉴스와 소셜을 한 표에 둔다. 두 표로 나눠 두면 같은 일(중복 제거·보존·신선도)을
-- 두 번 쓰게 되고, 실제로 한쪽만 고쳐 조용히 갈라졌다. 다른 것은 축 하나뿐이다 —
-- 뉴스는 같은 기사가 여러 URL로 오므로 `url_hash`로도 접어야 한다.
CREATE TABLE IF NOT EXISTS content_index (
    content_id VARCHAR PRIMARY KEY,
    content_kind VARCHAR NOT NULL CHECK (content_kind IN ('news', 'social')),
    -- 소셜에는 대응하는 축이 없어 NULL이다. DuckDB의 UNIQUE는 NULL을 서로 다른
    -- 값으로 보므로 소셜 행 여러 개가 여기서 부딪히지 않는다.
    url_hash VARCHAR UNIQUE,
    content_hash VARCHAR NOT NULL UNIQUE,
    -- 발행 시각 축. retention이 자르는 기준이다.
    observed_at TIMESTAMPTZ NOT NULL,
    -- PIT 축. "그때 우리가 이미 갖고 있었나"는 이것으로만 답한다.
    first_seen_at TIMESTAMPTZ NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL,
    partition_date DATE NOT NULL
);
