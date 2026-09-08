-- backtest 상세 행은 Parquet가 소유한다. DuckDB에는 범위와 평가 요약만 남긴다.
CREATE TABLE IF NOT EXISTS backtests (
    backtest_id VARCHAR PRIMARY KEY,
    experiment_id VARCHAR NOT NULL REFERENCES experiments(experiment_id),
    parquet_path VARCHAR NOT NULL,
    content_sha256 VARCHAR NOT NULL,
    row_count BIGINT NOT NULL CHECK (row_count >= 0),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    stage VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    metrics JSON,
    created_at TIMESTAMPTZ NOT NULL,
    CHECK (period_start <= period_end)
);
