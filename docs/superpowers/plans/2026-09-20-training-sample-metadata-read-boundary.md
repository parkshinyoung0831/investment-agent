# Training sample metadata read owner — Implementation Plan

> 현재 Git·실제 caller·tests를 목표 문서보다 우선한다. `main`에서 inline 실행하며 각 Task 뒤 원장을 갱신한다.

**Goal:** `training_sample_period_inputs`의 scalar projection·PIT cutoff 조회를 Trading façade에서 ResearchStore로 옮기고 command가 실제 owner를 호출하게 한다.

**Architecture:** `build_training_samples`는 universe와 full feature/label row read를 아직 SupabaseRepository에서 읽지만, 이미 주입된 ResearchStore를 completion manifest와 scalar metadata read에 함께 사용한다. ResearchStore는 기존 `records_with_payload_fields`를 그대로 사용해 대형 JSON payload 복원을 피한다. feature/label full read 이동은 다른 caller가 있으므로 이번 계획에 섞지 않는다.

**Constraints:** sample 계산·signature·재시작·PIT/label cutoff·batch 저장 순서·DB schema·CLI·harness는 변경하지 않는다. 새 wrapper/interface/alias는 만들지 않는다. 새 pending dependency 예외도 추가하지 않는다.

### Task 1 — metadata 조회 계약을 ResearchStore에 구현하고 command 이관

**Files:** `src/investment_agent/research/storage/repository.py`, `src/investment_agent/research/commands/build_training_samples.py`, `tests/investment_agent/research/commands/test_training_samples.py`, 새 Research storage test, 진행 원장.

- [ ] ResearchStore의 scalar read가 version·ticker·label cutoff·window를 보존하고 full JSON payload를 복원하지 않는 실패 계약 테스트를 작성한다.
- [ ] command의 lightweight 경로가 trading reader가 아닌 Research store를 호출하고, 완료 기간에서는 full feature/label read를 하지 않는 실패 계약을 확인한다.
- [ ] 기존 façade 구현의 필터·검증을 ResearchStore에 최소한으로 옮긴다. `ResearchStore(read_only=True)` 기본 조회, 주입 store reuse, write 시 별도 writable store 의미는 유지한다.
- [ ] targeted·architecture 테스트, caller 검색, 원장 갱신 후 커밋한다.

### Task 2 — 사용이 끝난 façade 제거와 통합 검증

**Files:** `src/investment_agent/trading/supabase_repository.py`, Research ownership/architecture tests, 진행 원장.

- [ ] production/test caller 0건을 확인한 뒤 `SupabaseRepository.training_sample_period_inputs`만 삭제한다.
- [ ] 실제 owner 경계를 강제하는 test와 합성 위반 주입을 검증한다. 다른 feature/label read façade를 삭제하지 않는다.
- [ ] architecture·workflow·관련 Research tests 및 가능한 전체 suite를 기준선과 비교한다. 원장에 변경 전후·삭제 파일·남은 debt를 기록한다.
