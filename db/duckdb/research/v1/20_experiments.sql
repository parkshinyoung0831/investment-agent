-- strategy_runs/strategy_allocations는 현재 포트폴리오 연구 API의 관계형 계약이다.
CREATE TABLE IF NOT EXISTS strategy_runs (
    run_id VARCHAR PRIMARY KEY,
    strategy_id VARCHAR NOT NULL,
    decision_date DATE NOT NULL,
    apply_date DATE NOT NULL,
    mode VARCHAR NOT NULL,
    signals JSON NOT NULL,
    UNIQUE (strategy_id, apply_date)
);

CREATE TABLE IF NOT EXISTS strategy_allocations (
    run_id VARCHAR NOT NULL REFERENCES strategy_runs(run_id),
    asset_symbol VARCHAR NOT NULL,
    weight DOUBLE NOT NULL CHECK (isfinite(weight) AND weight > 0 AND weight <= 1),
    PRIMARY KEY (run_id, asset_symbol)
);

CREATE TABLE IF NOT EXISTS experiments (
    experiment_id VARCHAR PRIMARY KEY,
    dataset_id VARCHAR NOT NULL REFERENCES datasets(dataset_id),
    code_commit VARCHAR NOT NULL,
    stage VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    metrics JSON,
    created_at TIMESTAMPTZ NOT NULL
);
