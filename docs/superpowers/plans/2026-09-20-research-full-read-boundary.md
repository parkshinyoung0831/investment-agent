# Research feature/label full read 경계 — Implementation Plan

> 현재 `main`의 caller, source, tests가 기준이다. 기존 설계 문서는 인계 자료다.

**Goal:** Research DuckDB의 full feature/label 조회·PIT cutoff·저장 무결성 검증을 ResearchStore가 소유하게 하고, 모든 실제 caller를 이관한 뒤 Trading의 두 호환 read 메서드를 제거한다.

**Safety:** 저장 스키마, 투자 계산, label 확정 시각, hash/ID fail-closed, as-of 순서, dry-run, 미확정 주문 처리에는 변경이 없다. ResearchStore의 read-only 사용을 유지한다. 새 generic repository나 숨김 alias를 만들지 않는다.

### Task 1 — owner 조회 계약 (완료)

실제 Parquet와 read-only store로 version/ticker/window/as-of-value/availability/cutoff 및 hash/ID 변조 거부를 먼저 테스트한다. 현재 Trading façade의 두 조회 구현을 ResearchStore로 옮기고 façade는 기존 caller용으로 직접 전달만 한다. Research owner·기존 Trading 계약·architecture 테스트를 통과시키고 원장을 갱신한다.

### Task 2 — Research commands (진행 전)

`build_labels`, `build_training_samples`, `export_dataset`가 membership/가격 read와 별도로 ResearchStore의 full read를 사용하게 한다. 각 command의 기존 호출 순서·dry-run·실패 계약을 검증하고 관련 테스트를 함께 갱신한다. 최소 독립 단위로 나눠 커밋한다.

### Task 3 — RL training과 ML serving runtime (진행 전)

`research/rl/features.py`의 feature/label 로더와 실제 상위 조립 caller, `research/ml_serving.py`의 champion forecast 및 실제 Trading 조립 caller를 추적한다. membership은 data owner, full feature/label은 Research owner라는 경계를 런타임에서 성립시킨다. fail-closed fallback과 모델 계약을 유지한다.

### Task 4 — 호환 경계 제거 및 최종 검증 (진행 전)

source/test caller 0건을 AST/검색으로 확인한 뒤 Trading façade의 두 read 메서드와 중복 변환 함수를 삭제한다. owner contract tests와 architecture guard를 강화하고 가능한 전체 suite·import 검증을 실행한다. 남은 pending은 실제 import가 사라진 항목만 제거한다.
