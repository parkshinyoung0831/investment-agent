-- 대용량 feature/dataset 행은 Parquet가 소유한다. 아래 표는 현재 코드의 작은
-- catalog와 재현 가능한 dataset metadata만 보관한다.
--
-- 이 DB의 여덟 표는 세 묶음이고 서로 다른 일을 한다. 숫자만 보고 합치면 기능이 준다.
--
--   1. Parquet 뿌리 catalog — `feature_sets`, `dataset_runs`
--      "그 parquet 뿌리가 어디고 얼마나 최신인가". 쓰는 자리가 서로 다르다
--      (feature 적재 / dataset 적재).
--   2. 연구 원장 — `datasets` → `experiments` → `models` → `backtests`
--      hash로 고정된 불변 lineage. 어떤 데이터로 무엇을 학습해 어떻게 평가했나.
--   3. 전략 연구 — `strategy_runs`, `strategy_allocations`
--      월간 전략 배분 파이프라인의 관계형 계약. ML 실험과 다른 축이다.
CREATE TABLE IF NOT EXISTS feature_sets (
    feature_version VARCHAR PRIMARY KEY,
    root_path VARCHAR NOT NULL,
    latest_trade_date DATE,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_runs (
    dataset VARCHAR PRIMARY KEY,
    root_path VARCHAR NOT NULL,
    row_count BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS datasets (
    dataset_id VARCHAR PRIMARY KEY,
    parquet_path VARCHAR NOT NULL,
    content_sha256 VARCHAR NOT NULL,
    row_count BIGINT NOT NULL CHECK (row_count >= 0),
    period_start DATE,
    period_end DATE,
    feature_version VARCHAR,
    label_version VARCHAR,
    code_commit VARCHAR NOT NULL,
    stage VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CHECK (period_start IS NULL OR period_end IS NULL OR period_start <= period_end)
);
