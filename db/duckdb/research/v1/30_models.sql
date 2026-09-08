-- 모델 바이너리는 artifact 디렉터리에 두고 이 표에는 검증 가능한 위치와 hash만 둔다.
CREATE TABLE IF NOT EXISTS models (
    model_id VARCHAR PRIMARY KEY,
    experiment_id VARCHAR NOT NULL REFERENCES experiments(experiment_id),
    artifact_path VARCHAR NOT NULL,
    artifact_sha256 VARCHAR NOT NULL,
    stage VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    metrics JSON,
    created_at TIMESTAMPTZ NOT NULL
);
