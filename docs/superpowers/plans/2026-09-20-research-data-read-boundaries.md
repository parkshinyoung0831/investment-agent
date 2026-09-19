# Research의 Data read 경계 — Implementation Plan

**Goal:** Research command가 Trading God façade를 통해 읽는 입력 중, 이미 canonical Data owner API가 있고 historical replay 의미를 보존할 수 있는 호출만 작은 단위로 직접 이관한다.

**Boundary:** `SupabaseRepository`를 일괄 치환하지 않는다. local mirror, PIT cutoff, historical membership, 가격 batch semantics가 필요한 command는 별도 검증 전 유지한다. 새 generic repository나 façade를 만들지 않는다.

### Task 1 — build_events current universe (완료)

CLI main의 현재 tracked ticker read만 `data/universe/persistence.py`의 기존 owner API로 연결한다. operations가 명시 tickers를 넘기는 `build_events()` 함수와 event 계산·저장은 바꾸지 않는다. 정확한 pending 한 쌍만 RED→GREEN으로 제거한다.

### Task 2 — training/export/retrain universe read (완료)

`build_training_samples`, `export_dataset`, `continuous_retrain`의 기본 runtime이 Trading façade에서 사용하던 메서드를 추적했다. 세 command 모두 기본 경로에서는 현재 tracked ticker와 PIT S&P 500 membership만 필요했고, feature/label/decision experience는 이미 ResearchStore에서 읽었다. historical backfill은 repository를 명시 주입하므로 local mirror도 보존된다.

Research datasets에 Data universe owner의 기존 조회를 조립하는 concrete reader를 두고 세 기본 caller를 이 reader로 변경한다. RL membership row 변환, 역전된 기간 거부, ticker 정규화를 계약 테스트로 고정한다. 과거 재현용 명시 repository 인자는 유지한다. 정확한 pending 세 쌍만 RED→GREEN으로 제거한다.

### Task 3 — 다음 Data read 후보 (조사 전)

label·feature·valuation·decision experience producer의 남은 façade 사용은 universe뿐 아니라 local mirror, 가격, fundamental, decision ledger를 함께 요구한다. 메서드별 owner와 historical replay cutoff를 다시 조사한 뒤 별도 단위로 분리한다.
