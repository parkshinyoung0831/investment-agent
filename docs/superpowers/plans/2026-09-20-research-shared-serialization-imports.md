# Research shared serialization import 후속 정리 — Implementation Plan

> `main`의 현재 import와 runtime/test caller를 매 Task 시작 시 다시 확인한다. 이전 분석은 판정 근거가 아니다.

**Goal:** Research가 `trading/contracts.py`에서 가져오지만 실제 구현은 `platform.serialization`에 있는 `ContractError`, `parse_datetime`, `json_value`의 남은 순수 재수출 import 20곳을 작은 묶음으로 직접 owner에 연결한다.

**Boundary:** `research/features/layer.py`의 `EvidenceBundle`, `research/evaluation/evaluator.py`의 `EvaluationResult`는 실제 Trading 금융 계약이므로 이 계획에서 pending을 제거하지 않는다. 다른 Trading 알고리즘·portfolio·Supabase read import도 유지한다. 같은 이름을 가진 새 alias/façade는 만들지 않는다.

**Verification:** 각 Task에서 정확한 pending 항목을 먼저 제거해 architecture RED를 확인하고, 소스 import 변경 후 GREEN과 해당 도메인 테스트를 확인한다. 타입 identity와 행동, DB schema, 투자 계산, execution safety는 바꾸지 않는다. 새 pending 항목을 추가하지 않는다.

### Task 1 — valuation 3곳

`research/valuation/engine.py`, `research/valuation/inputs.py`, `research/commands/build_valuations.py`의 순수 serialization import만 변경한다. valuation·historical replay·architecture 테스트와 진행 원장을 확인하고 커밋한다.

### Task 2 — Research command 7곳

`research/commands/adopt_ml_model.py`, `build_events.py`, `build_features.py`, `build_labels.py`, `build_training_samples.py`, `export_dataset.py`, `ml_challengers.py`의 순수 import만 변경한다. 각 command의 직접 테스트·architecture·workflow를 확인하고 원장 갱신 후 커밋한다.

### Task 3 — RL·training·backtest 7곳

`research/rl/baseline.py`, `features.py`, `leakage.py`, `research/training/baseline.py`, `walk_forward.py`, `research/backtest/contracts.py`, `engine.py`의 순수 import만 변경한다. 다른 `trading/portfolio/` import는 건드리지 않는다. 관련 계약·재현성·architecture 검증 후 커밋한다.

### Task 4 — ML 3곳과 최종 통합

`research/ml_inference.py`, `ml_serving.py`, `models/baselines.py`의 순수 import만 변경한다. 관련 테스트·architecture·docs consistency·가능한 전체 suite를 실행한다. 정확한 pending 감소(64→44)를 확인하고 다음 실제 금융 계약/read 경계를 원장에 기록한 뒤 커밋한다.
