# Shared forecast horizon contract — Implementation Plan

**Goal:** Research label/model과 Trading 판단이 쓰는 20거래일 horizon을 어느 한 bounded context의 구현이 아닌 단일 금융 도메인 계약으로 소유하고, Research의 Trading 역방향 import를 제거한다.

**Boundary:** horizon 값·투자 알고리즘·label 정의는 바꾸지 않는다. 범용 설정 framework나 registry를 만들지 않는다. 모든 source/test caller를 같은 작업에서 직접 이관하고 caller 0인 legacy constants 파일은 삭제한다.

### Task 1 — 실제 caller와 owner 판정 (완료)

Research 6곳과 Trading 7곳, Trading decision analysis가 같은 20거래일 값을 소비함을 확인했다. Research model/label이 생산하고 Trading decision/portfolio가 소비하지만 양쪽 모두의 불변값이므로 최상위 금융 도메인 계약이 canonical owner다. Platform은 금융 도메인을 몰라야 하므로 사용하지 않는다.

### Task 2 — 계약 직접 이관과 legacy 삭제 (완료)

`src/investment_agent/forecasting.py`에 단일 정의를 두고 모든 caller를 직접 이관한다. Research pending 여섯 쌍을 RED→GREEN으로 제거한다. `src/investment_agent/trading/decision/constants.py`는 남은 caller가 없고 policy/evaluation 상수도 사용되지 않으므로 alias로 남기지 않고 삭제한다.

### Task 3 — ownership guard와 통합 검증 (완료)

AST guard가 horizon 정의가 정확히 canonical 파일 한 곳뿐임을 강제하고, 임시 중복 정의를 실제로 검출하는지 시험한다. 관련 Research/Trading/architecture/workflow/docs와 전체 suite를 검증한 뒤 진행 원장을 갱신한다.
