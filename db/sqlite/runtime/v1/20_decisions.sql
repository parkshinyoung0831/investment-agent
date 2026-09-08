-- 로컬 판단 원장. 외부 canonical identity는 호출 경계에서 검증한다.

CREATE TABLE IF NOT EXISTS policies (
  policy_key     text NOT NULL CHECK (trim(policy_key) <> ''),
  policy_version int  NOT NULL CHECK (policy_version > 0),
  stage          text NOT NULL CHECK (stage IN (
                   'shadow','backtest','out_of_sample','walk_forward','paper','live')),
  model_provider text NOT NULL CHECK (trim(model_provider) <> ''),
  model_name     text NOT NULL CHECK (trim(model_name) <> ''),
  prompt_version text NOT NULL CHECK (trim(prompt_version) <> ''),
  config         JSON NOT NULL CHECK (json_type(config) = 'object'),
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  PRIMARY KEY (policy_key, policy_version)
);

CREATE TABLE IF NOT EXISTS model_versions (
  artifact_id     text PRIMARY KEY CHECK (trim(artifact_id) <> ''),
  algorithm       text NOT NULL CHECK (algorithm IN (
                    'naive','ridge','lightgbm','xgboost',
                    'a2c','ddpg','ppo','sac','td3','llm','rule')),
  feature_version text NOT NULL CHECK (trim(feature_version) <> ''),
  train_start     TEXT,
  train_end       TEXT,
  seed            int,
  artifact_uri    text NOT NULL CHECK (trim(artifact_uri) <> ''),
  sha256          text NOT NULL CHECK (regexp('^[0-9a-f]{64}$', sha256)),
  params          JSON NOT NULL DEFAULT '{}' CHECK (json_type(params) = 'object'),
  code_commit     text,
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  CHECK (train_start IS NULL OR train_end > train_start)
);

CREATE TABLE IF NOT EXISTS model_promotions (
  promotion_id      INTEGER PRIMARY KEY,
  artifact_id       text NOT NULL REFERENCES model_versions(artifact_id),
  from_stage        text NOT NULL CHECK (from_stage IN (
                      'shadow','backtest','out_of_sample','walk_forward','paper')),
  to_stage          text NOT NULL CHECK (to_stage IN (
                      'backtest','out_of_sample','walk_forward','paper','live')),
  status            text NOT NULL CHECK (status IN ('proposed','approved','rejected','retired')),
  evidence          JSON NOT NULL CHECK (json_type(evidence) = 'object'),
  approved_by       text,
  approved_at       TEXT,
  confirmation_text text,
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  CHECK (
    (status = 'approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
    OR (status <> 'approved' AND approved_at IS NULL)
  ),
  CONSTRAINT model_promotions_transition_check CHECK (
    status <> 'approved'
    OR (from_stage = 'shadow'        AND to_stage = 'backtest')
    OR (from_stage = 'backtest'      AND to_stage = 'out_of_sample')
    OR (from_stage = 'out_of_sample' AND to_stage = 'walk_forward')
    OR (from_stage = 'walk_forward'  AND to_stage = 'paper')
    OR (from_stage = 'paper'         AND to_stage = 'live')
  )
);

CREATE TABLE IF NOT EXISTS decision_runs (
  run_id            text PRIMARY KEY CHECK (trim(run_id) <> ''),
  as_of_at          TEXT NOT NULL,
  stage             text NOT NULL CHECK (stage IN (
                      'shadow','backtest','out_of_sample','walk_forward','paper','live')),
  status            text NOT NULL CHECK (status IN ('running','completed','partial','failed')),
  candidate_tickers JSON NOT NULL CHECK (json_type(candidate_tickers) = 'array'),
  -- 판단이 바라본 계좌 상태(`execution.account_snapshots`). FK를 걸지 않는 것은 의도다 —
  -- 걸면 trading이 execution에 의존해 방향이 뒤집힌다.
  account_snapshot_id text,
  code_commit       text,
  started_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  finished_at       TEXT,
  failure_reason    text,
  -- 부분 성공을 전체 성공으로 승격하지 않는다.
  CHECK (
    (status = 'running' AND finished_at IS NULL)
    OR (status IN ('completed','partial') AND finished_at IS NOT NULL AND failure_reason IS NULL)
    OR (status = 'failed' AND finished_at IS NOT NULL AND failure_reason IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS security_decisions (
  case_key       text PRIMARY KEY CHECK (trim(case_key) <> ''),
  run_id         text REFERENCES decision_runs(run_id) ON DELETE SET NULL,
  security_id    integer NOT NULL CHECK (security_id > 0),
  as_of_at       TEXT NOT NULL,
  horizon_days   int NOT NULL CHECK (horizon_days BETWEEN 1 AND 252),
  policy_key     text NOT NULL,
  policy_version int NOT NULL,
  model_provider text NOT NULL CHECK (trim(model_provider) <> ''),
  model_name     text NOT NULL CHECK (trim(model_name) <> ''),
  source_kind    text NOT NULL CHECK (source_kind IN ('live_shadow','historical_replay')),
  status         text NOT NULL CHECK (status IN ('completed','abstained','failed')),
  -- 같은 입력이면 같은 판단이어야 한다. 재현 검증의 기준점이다.
  context_hash   text NOT NULL CHECK (regexp('^[0-9a-f]{64}$', context_hash)),
  final_decision JSON,
  failure_reason text,
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  FOREIGN KEY (policy_key, policy_version)
    REFERENCES policies(policy_key, policy_version),
  UNIQUE (security_id, as_of_at, horizon_days, policy_key, policy_version),
  CHECK (
    (status = 'failed' AND final_decision IS NULL AND failure_reason IS NOT NULL)
    OR (status IN ('completed','abstained') AND final_decision IS NOT NULL AND failure_reason IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS decision_evidence (
  case_key      text NOT NULL
                REFERENCES security_decisions(case_key) ON DELETE CASCADE,
  evidence_kind text NOT NULL CHECK (evidence_kind IN ('bundle','role_analyses')),
  artifact_uri  text NOT NULL CHECK (trim(artifact_uri) <> ''),
  sha256        text NOT NULL CHECK (regexp('^[0-9a-f]{64}$', sha256)),
  byte_size     integer NOT NULL CHECK (byte_size > 0),
  schema_version text NOT NULL CHECK (trim(schema_version) <> ''),
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  PRIMARY KEY (case_key, evidence_kind)
);

CREATE TABLE IF NOT EXISTS signal_runs (
  batch_id           text PRIMARY KEY CHECK (trim(batch_id) <> ''),
  run_id             text NOT NULL REFERENCES decision_runs(run_id) ON DELETE CASCADE,
  as_of_at           TEXT NOT NULL,
  completed_at       TEXT NOT NULL CHECK (completed_at >= as_of_at),
  requested_symbols  JSON NOT NULL CHECK (json_type(requested_symbols) = 'array'),
  successful_symbols JSON NOT NULL CHECK (json_type(successful_symbols) = 'array'),
  failed_symbols     JSON NOT NULL DEFAULT '[]'
                     CHECK (json_type(failed_symbols) = 'array'),
  is_complete        boolean NOT NULL,
  model_artifact_id  text REFERENCES model_versions(artifact_id),
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  UNIQUE (run_id)
);

CREATE TABLE IF NOT EXISTS signals (
  signal_id   text PRIMARY KEY CHECK (trim(signal_id) <> ''),
  batch_id    text NOT NULL REFERENCES signal_runs(batch_id) ON DELETE CASCADE,
  case_key    text REFERENCES security_decisions(case_key) ON DELETE SET NULL,
  security_id integer NOT NULL CHECK (security_id > 0),
  proposal    JSON NOT NULL CHECK (json_type(proposal) = 'object'),
  recorded_at TEXT NOT NULL,
  expires_at  TEXT NOT NULL CHECK (expires_at > recorded_at),
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  UNIQUE (batch_id, security_id)
);

CREATE TABLE IF NOT EXISTS portfolio_proposals (
  proposal_id       text PRIMARY KEY CHECK (trim(proposal_id) <> ''),
  run_id            text NOT NULL REFERENCES decision_runs(run_id) ON DELETE CASCADE,
  source_type       text NOT NULL CHECK (source_type IN ('llm','ml','rl','rule','optimizer')),
  source_version    text NOT NULL CHECK (trim(source_version) <> ''),
  stage             text NOT NULL CHECK (stage IN (
                      'shadow','backtest','out_of_sample','walk_forward','paper','live')),
  as_of_at          TEXT NOT NULL,
  weights           JSON NOT NULL CHECK (json_type(weights) = 'object'),
  confidence        REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  reasoning         JSON NOT NULL CHECK (json_type(reasoning) = 'array'),
  case_keys         JSON NOT NULL DEFAULT '[]' CHECK (json_type(case_keys) = 'array'),
  model_artifact_id text REFERENCES model_versions(artifact_id),
  account_snapshot_id text,
  metadata JSON NOT NULL DEFAULT '{}' CHECK (json_type(metadata) = 'object'),
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  -- 아래 복합 FK가 참조하므로 UNIQUE가 필요하다.
  UNIQUE (proposal_id, run_id)
);

CREATE TABLE IF NOT EXISTS risk_decisions (
  risk_decision_id text PRIMARY KEY CHECK (trim(risk_decision_id) <> ''),
  proposal_id      text NOT NULL REFERENCES portfolio_proposals(proposal_id),
  policy_key       text NOT NULL,
  policy_version   int  NOT NULL CHECK (policy_version > 0),
  -- 정책과 입력의 해시를 함께 남긴다. 같은 입력·같은 정책이면 같은 판정이어야 한다.
  policy_hash      text NOT NULL CHECK (regexp('^[0-9a-f]{64}$', policy_hash)),
  input_hash       text NOT NULL CHECK (regexp('^[0-9a-f]{64}$', input_hash)),
  is_approved      boolean NOT NULL,
  approved_weights JSON,
  violations       JSON NOT NULL DEFAULT '[]' CHECK (json_type(violations) = 'array'),
  adjustments      JSON NOT NULL DEFAULT '[]' CHECK (json_type(adjustments) = 'array'),
  metrics          JSON NOT NULL DEFAULT '{}' CHECK (json_type(metrics) = 'object'),
  decided_at       TEXT NOT NULL,
  FOREIGN KEY (policy_key, policy_version)
    REFERENCES policies(policy_key, policy_version),
  -- 승인이면 승인된 비중이 있어야 하고, 거절이면 없어야 한다.
  CHECK (
    (is_approved AND approved_weights IS NOT NULL AND json_type(approved_weights) = 'object')
    OR (NOT is_approved AND approved_weights IS NULL)
  ),
  UNIQUE (risk_decision_id, proposal_id)
);

CREATE TABLE IF NOT EXISTS portfolio_decisions (
  decision_id      text PRIMARY KEY CHECK (trim(decision_id) <> ''),
  run_id           text NOT NULL REFERENCES decision_runs(run_id),
  proposal_id      text NOT NULL REFERENCES portfolio_proposals(proposal_id),
  risk_decision_id text NOT NULL UNIQUE REFERENCES risk_decisions(risk_decision_id),
  champion_policy  JSON NOT NULL CHECK (json_type(champion_policy) = 'object'),
  status           text NOT NULL CHECK (status IN ('approved','rejected')),
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  CONSTRAINT portfolio_decisions_proposal_run_fkey
    FOREIGN KEY (proposal_id, run_id)
    REFERENCES portfolio_proposals(proposal_id, run_id),
  CONSTRAINT portfolio_decisions_risk_proposal_fkey
    FOREIGN KEY (risk_decision_id, proposal_id)
    REFERENCES risk_decisions(risk_decision_id, proposal_id)
);

CREATE TABLE IF NOT EXISTS decision_evaluations (
  case_key                text NOT NULL
                          REFERENCES security_decisions(case_key) ON DELETE CASCADE,
  horizon_days            int  NOT NULL CHECK (horizon_days IN (1, 5, 20, 60)),
  start_trade_date        date NOT NULL,
  end_trade_date          date NOT NULL CHECK (end_trade_date > start_trade_date),
  asset_return            REAL NOT NULL,
  benchmark_return        REAL NOT NULL,
  excess_return           REAL NOT NULL,
  max_adverse_excursion   REAL NOT NULL CHECK (max_adverse_excursion <= max_favorable_excursion),
  max_favorable_excursion REAL NOT NULL,
  direction_correct       boolean,
  brier_score             REAL NOT NULL CHECK (brier_score BETWEEN 0 AND 1),
  evaluated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  PRIMARY KEY (case_key, horizon_days)
);

CREATE TABLE IF NOT EXISTS attribution_reports (
  report_id      INTEGER PRIMARY KEY,
  period_start   date NOT NULL,
  period_end     date NOT NULL CHECK (period_end >= period_start),
  execution_mode text NOT NULL CHECK (execution_mode IN ('paper','live')),
  breakdown      JSON NOT NULL CHECK (json_type(breakdown) = 'object'),
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
  UNIQUE (period_start, period_end, execution_mode)
);
