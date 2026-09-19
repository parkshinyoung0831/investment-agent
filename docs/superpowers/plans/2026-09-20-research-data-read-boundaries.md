# Research의 Data read 경계 — Implementation Plan

**Goal:** Research command가 Trading God façade를 통해 읽는 입력 중, 이미 canonical Data owner API가 있고 historical replay 의미를 보존할 수 있는 호출만 작은 단위로 직접 이관한다.

**Boundary:** `SupabaseRepository`를 일괄 치환하지 않는다. local mirror, PIT cutoff, historical membership, 가격 batch semantics가 필요한 command는 별도 검증 전 유지한다. 새 generic repository나 façade를 만들지 않는다.

### Task 1 — build_events current universe (완료)

CLI main의 현재 tracked ticker read만 `data.universe.persistence`의 기존 owner API로 연결한다. operations가 명시 tickers를 넘기는 `build_events()` 함수와 event 계산·저장은 바꾸지 않는다. 정확한 pending 한 쌍만 RED→GREEN으로 제거한다.

### Task 2 — 다음 Data read 후보 (조사 전)

feature, valuation, label, dataset, continuous retrain의 실제 live/historical caller와 local mirror 요구를 각각 조사한다. owner API가 동등한 경우에만 후속 계획을 구체화한다.
