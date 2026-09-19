# Research core serialization import 정리 — Implementation Plan

> 현재 코드·import·테스트가 목표 문서보다 우선한다. 이 계획은 `main`에서 작은 단위로 inline 실행한다.

**Goal:** Research의 네 핵심 계약 파일이 Trading의 재수출을 거쳐 공통 직렬화 유틸리티를 읽는 역방향 import를 실제 owner인 `platform.serialization`로 직접 연결한다.

**Scope:** `research/datasets/contracts.py`, `research/datasets/core.py`, `research/datasets/training.py`, `research/rl/contracts.py`의 `ContractError`, `json_value`, `parse_datetime`만 대상이다. `trading.contracts.EvidenceBundle`나 `EvaluationResult` 같은 금융 계약, `trading.portfolio`·알고리즘·저장 경계는 이 계획 밖이다.

**Proof:** `trading/contracts.py`가 이 세 심볼을 `platform.serialization`에서 그대로 import한다. 따라서 타입 정체성과 검증 의미는 바뀌지 않는다. 임시 alias/re-export를 추가하지 않는다.

### Task 1 — 네 core import와 정확한 pending 항목 제거

- [ ] 네 파일의 runtime/import caller와 관련 계약 테스트를 확인한다.
- [ ] `tests/investment_agent/test_architecture.py`에서 정확한 네 pending 쌍을 먼저 제거해 RED를 확인한다. 새 위반은 추가하지 않는다.
- [ ] 네 파일의 import를 `platform.serialization`로 직접 바꾼다. 구현·값·예외 메시지는 변경하지 않는다.
- [ ] 계약·dataset·RL·architecture tests와 직접 import/identity 검증, caller 검색, 원장 갱신 후 커밋한다.

### Task 2 — 통합 검증과 다음 묶음 판정

- [ ] architecture·workflow·관련 Research tests 및 가능한 전체 suite를 기준선과 비교한다.
- [ ] `PENDING_DEPENDENCIES`가 네 쌍만 감소했는지 확인한다. 남은 `research→trading.contracts` 중 순수 공통 유틸리티와 실제 Trading 계약을 다시 분류한다.
- [ ] 진행 원장에 변경 전후·수정 파일·테스트·남은 debt를 기록하고 커밋한다.
