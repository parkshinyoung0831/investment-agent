# Research evaluation ownership — Implementation Plan

**Goal:** Research가 생산·소비하는 평가 결과와 배당·분할 포함 가격 경로 수익률 계산을 Research owner로 옮겨 일반 Research→Trading 역방향 import 세 쌍을 제거한다.

**Boundary:** 평가 horizon, 수익률·배당·분할 계산, 결과 직렬화, 저장 schema, 실거래 경로는 변경하지 않는다. Trading re-export를 남기지 않는다.

### Task 1 — runtime caller와 계산 계약 검증 (완료)

`EvaluationResult`는 Research `evaluate_case`만 생성한다. `total_return`은 Research `evaluate_case`와 decision experience producer만 호출한다. Trading `contracts.py`와 `evidence/tools.py`는 이 두 계약의 정의 위치였지만 Trading runtime caller는 없었다. 기존 평가기 테스트가 Trading 폴더에 놓여 있어 Research owner 위치로 이동하고 분할·배당 테스트를 추가한다.

### Task 2 — 실패 계약 테스트 후 owner 이관 (완료)

새 owner import와 정확한 pending 세 쌍 제거로 import error·architecture violation을 RED로 확인한다. 평가 결과는 `research.evaluation.outcomes`, 수익률 계산은 `research.evaluation.returns`로 옮기고 Research caller를 직접 연결한다. Trading의 dead 정의를 삭제한다.

### Task 3 — 통합 검증과 인계 (완료)

관련 Research/Trading/architecture/workflow/docs 테스트 132개가 통과했다. 전체 offline suite 3,032개는 기존 기준선과 같은 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개뿐이다. old owner caller 검색 0건과 diff 검증 결과를 진행 원장에 기록하고 독립 커밋으로 닫는다.
