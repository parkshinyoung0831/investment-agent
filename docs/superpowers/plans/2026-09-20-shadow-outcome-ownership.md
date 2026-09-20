# Shadow trade outcome ownership — Implementation Plan

**Goal:** Research shadow-fill 평가에서만 쓰는 거래 단위 PnL 계약을 실제 caller의 owner로 옮기고 Research→Trading 역방향 import 한 쌍을 제거한다.

**Boundary:** 계산식, 검증, ID, 비용, serializer, DB schema, live execution은 변경하지 않는다. 호환 alias는 만들지 않는다.

### Task 1 — caller와 계약 재확인 (완료)

`trading.performance.pnl`의 production caller는 `research.evaluation.shadow_fill` 한 곳이다. Trading 성과 runtime은 `performance.ledger`·`service`·`attribution`을 사용한다. `performance.__init__`은 이 계약을 재수출하고 native test 한 곳이 그 경로를 사용했다. Research shadow-fill과 training-sample tests는 비용·PnL·outcome ID 동작을 이미 검증한다.

### Task 2 — 소유 위치 이관 (완료)

native test의 owner import와 정확한 pending 한 쌍 제거로 RED를 확인한다. 원본 계약을 `research.evaluation.outcomes`로 옮기고 shadow-fill import를 직접 연결한다. caller가 없는 Trading `pnl.py`와 package re-export는 제거한다.

### Task 3 — 통합 검증과 인계 (완료)

Research sample/native/architecture/workflow/docs tests 109개가 통과했다. 전체 offline suite 3,031개는 기존 기준선과 동일한 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개뿐이다. legacy import caller 0건과 `git diff --check`를 확인하고 진행 원장에 남은 debt를 기록한다.
