# Risk decision → execution intent ownership — Implementation Plan

**Goal:** Trading RiskGate가 `RiskDecision`까지만 만들고, 승인된 결정을 `ExecutionIntent`로 직렬화하는 책임은 Execution이 소유하도록 한다.

**Safety boundary:** 현재 maintenance hold·kill switch 상태를 유지한다. 승인, snapshot/promotion 재검증, deterministic intent ID, TTL, weight 검증, 저장 순서, live flag, DB schema를 바꾸지 않는다.

### Task 1 — runtime·maintenance 확인 (완료)

하네스 STOPPED, maintenance hold ON, kill switch ON, Toss live FALSE를 읽기 전용으로 확인했다. production caller는 `operations.commands.create_execution_intent` 한 곳이며, 승인·snapshot·promotion 확인 후 RiskGate factory를 호출하고 `ExecutionRepository.save_intent`로 저장한다. 기존 고정 입력의 intent ID `intent_dead29f28555f242e886db0f`와 만료 시각을 기록했다.

### Task 2 — 실패 계약과 소유권 이관 (완료)

Execution의 승인 거절·TTL·동일 ID 계약 테스트를 먼저 추가하고 architecture pending 한 쌍을 제거해 새 factory 부재와 위반으로 RED를 확인했다. Trading RiskGate의 intent factory를 삭제하고 `ExecutionIntent.from_approved_decision`으로 구현을 옮겼다. Operations는 이미 재구성·검증한 `RiskDecision.to_dict()`를 전달한다. Trading test의 기존 safety case는 Execution factory의 승인 거절 테스트로 이관했다.

### Task 3 — 통합 검증과 인계 (완료)

Execution 210개, Operations command 19개, architecture/workflow/docs 83개가 각각 통과했다. 전체 offline suite 3,036개는 기존 기준선과 같은 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개뿐이다. 이전 Trading factory caller 검색 0건과 diff를 확인한다. hold를 임의로 해제하거나 하네스를 재기동하지 않는다. 진행 원장 갱신 후 독립 커밋으로 닫는다.
