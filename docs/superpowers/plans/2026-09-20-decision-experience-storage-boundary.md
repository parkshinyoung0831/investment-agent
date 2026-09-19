# Decision experience 저장 경계 — Implementation Plan

**Goal:** 재계산 가능한 `decision_experiences`의 read/write와 label-availability cutoff를 ResearchStore가 소유하게 하고, Research·Operations·Reporting caller를 이관한 뒤 Trading façade를 삭제한다.

**Safety:** 원본 판단, 가격 경로, reward 계산, cutoff, ignore-existing, performance summary 의미를 바꾸지 않는다. Trading decision ledger와 Research experience artifact는 계속 분리한다.

### Task 1 — owner read 계약 (완료)

실제 ResearchStore에서 최초 관측 보존과 `available_at <= as_of_at` cutoff를 테스트한 뒤 canonical read 메서드를 추가한다.

### Task 2 — Research producer/trainer (완료)

`build_decision_experiences`가 별도 ResearchStore에서 existing/read/write를 수행하고, continuous retrain이 같은 store에서 경험을 읽게 한다. 가격·원본 decision read는 기존 reader에 유지한다.

### Task 3 — Operations/Reporting consumer와 façade 제거 (완료)

성과 update와 reporting notification을 read-only ResearchStore로 이관한다. caller 0건 확인 후 Supabase façade의 두 메서드를 삭제하고 AST ownership guard를 강화한다.

### Task 4 — 통합 검증과 원장 (완료)

관련 테스트, architecture/workflow/docs, 가능한 전체 suite를 실행하고 남은 dependency debt와 다음 Data read 후보를 기록한다.
