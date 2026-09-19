# Research training sample 저장 경계 이관 — Implementation Plan

> **For agentic workers:** 이 계획은 현재 `main`에서 inline 실행한다. 매 Task 시작 시 코드·호출자·테스트를 다시 확인하고, 문서보다 현재 Git을 우선한다.

**Goal:** 학습 sample과 기준일 completion manifest의 read/write를 Research owner가 직접 소유하게 하고, Trading façade의 호환 메서드 3개를 실제 caller 0건 이후 제거한다.

**Architecture:** `SupabaseRepository`는 이 단위에서 universe와 feature/label input read를 계속 맡는다. `ResearchStore`는 sample write와 manifest read/write를 맡는다. lightweight metadata → pending 기간의 full payload read, sample batch 저장 후 manifest 저장 순서와 재시작 semantics는 그대로 둔다. feature/label read façade는 별도 단위에서 판단한다.

**Tech Stack:** Python `unittest`, Research DuckDB/Parquet, 기존 AST owner guard.

## Constraints

- TDD: 현재 계약 확인 → 실패하는 store 분리 테스트 → 최소 변경 → targeted·architecture 테스트.
- DB schema, PIT/read filter, sample 계산, cost/risk 수치, inserted count, dry-run 동작, CLI/harness, live flag는 변경하지 않는다.
- sample 저장 실패 시 run manifest가 기록되지 않아야 한다. 재실행에서 완료된 기간은 full feature/label payload를 다시 읽지 않아야 한다.
- 새 interface·registry·façade를 만들거나 `PENDING_DEPENDENCIES`에 예외를 추가하지 않는다.
- 기존 user 변경과 graphify 산출물은 커밋하지 않는다.

### Task 1: command의 sample·manifest owner 분리

**Files:** `src/investment_agent/research/commands/build_training_samples.py`, `tests/investment_agent/research/commands/test_training_samples.py`, 진행 원장.

- [ ] 기존 test를 reader fake와 Research store fake로 나누고 store 인자를 넘긴다. 현재 구현에서 인자 오류로 RED를 확인한다.
- [ ] sample 저장 실패 시 manifest 미기록, 성공 시 sample→manifest 호출 순서, inserted count, dry-run, 재실행·input hash 변경 시 재계산, lightweight read 경로를 테스트로 고정한다.
- [ ] command에 `store: ResearchStore | None`을 추가한다. manifest는 ResearchStore read-only 기본 인스턴스에서 읽고, 실제 저장할 때만 write 인스턴스를 연다. 주입된 store는 read/write를 함께 수행한다. Supabase read와 sample 계산은 유지한다.
- [ ] targeted tests와 architecture/import 검증, caller 검색, 원장 갱신 후 커밋한다.

### Task 2: 직접 persistence test 이관, façade 제거, guard 강화

**Files:** `src/investment_agent/trading/supabase_repository.py`, `tests/investment_agent/trading/test_training_sample_persistence.py` (owner 경로로 이동 여부 판단), `tests/investment_agent/trading/test_repository_ownership.py`, 진행 원장.

- [ ] 동일 sample의 Parquet no-rewrite 검증은 `ResearchStore` 직접 테스트로 바꾼다. production/test façade caller 0건 확인 전에는 메서드를 제거하지 않는다.
- [ ] owner guard에 `save_training_samples`, `save_training_sample_runs`를 추가해 기존 façade에서 RED와 위반 주입 실패를 확인한다.
- [ ] façade의 sample write, manifest read/write 호환 메서드만 삭제한다. 사용하지 않는 import를 정리한다.
- [ ] targeted·architecture 테스트, exact caller 0건, 원장 갱신 후 커밋한다.

### Task 3: 통합 검증과 다음 경계 인계

**Files:** 진행 원장.

- [ ] architecture·repo convention·workflow 및 관련 research/storage tests를 실행한다. 가능한 범위의 전체 suite를 기준선과 비교한다.
- [ ] pending dependency 수, 현재 diff/status와 sample/manifest façade caller 0건을 확인한다.
- [ ] 변경 전·후 호출 관계, 파일 이동·삭제, 테스트, 남은 feature/label read dependency를 원장에 기록하고 커밋한다.

## 다음 단위 후보

`rl_feature_snapshot_rows`, `rl_training_label_rows`, `training_sample_period_inputs`는 ResearchStore raw read에 PIT·version·ticker 필터를 더하는 façade다. 이번 저장 이관 뒤 각 caller와 필터 계약을 별도 확인해야 한다. 단순 re-export로 숨기지 않는다.
