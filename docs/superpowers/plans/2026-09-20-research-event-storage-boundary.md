# Research event 저장 경계 이관 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** event와 event feature write를 ResearchStore가 직접 소유하게 하고, command·operations runtime caller를 이관한 뒤 trading façade의 두 호환 메서드를 제거한다.

**Architecture:** `LocalEvidenceCache` read와 ResearchStore write는 이미 다른 저장소이므로 `build_events`의 얕은 `EventRepository` pass-through를 제거하고 store를 별도 주입한다. tracked ticker read는 현재 caller의 `SupabaseRepository`에 유지해 이번 변경에서 PIT/read와 event 계산을 섞지 않는다.

**Tech Stack:** Python 3.11, `unittest`, Intelligence DuckDB cache, Research DuckDB, AST ownership guard.

**Spec:** `docs/superpowers/specs/2026-09-19-dependency-direction-design.md`

## Global Constraints

- source·runtime caller·tests가 문서보다 우선한다.
- event extraction, tracked ticker filter, cutoff, row 형식, 두 write의 기존 순서와 오류 전파를 바꾸지 않는다.
- `dry_run=True`에서는 ResearchStore를 생성하거나 호출하지 않는다.
- DB schema, live flag, harness·execution, 투자 알고리즘을 변경하지 않는다.
- 새 interface·registry·façade를 만들지 않고 `PENDING_DEPENDENCIES`에 새 예외를 추가하지 않는다.
- 각 task는 RED → 최소 구현 → targeted·architecture 검증 → caller 검색 → 진행 원장 → 커밋으로 끝낸다.

## File Structure

- `src/investment_agent/research/commands/build_events.py`: cache read·event 계산·ResearchStore write use case.
- `src/investment_agent/operations/commands/event_reanalysis.py`: on-demand refresh의 outer composition caller.
- `src/investment_agent/trading/supabase_repository.py`: 두 event write 호환 메서드 제거 대상.
- `tests/investment_agent/research/commands/test_build_events.py`: cutoff·filter·two-write·dry-run 계약.
- `tests/investment_agent/operations/commands/test_event_reanalysis.py`: reader와 event store use case 조립 계약.
- `tests/investment_agent/trading/test_repository_ownership.py`: owner 밖 Research write 호출 금지.
- `docs/superpowers/architecture-refactor-progress.md`: 단계 원장.

## Review Focus

1. untracked ticker는 저장 전 제거되고 글로벌 event의 `ticker=None`은 유지돼야 한다.
2. cutoff 뒤 수집 content는 event에 들어가면 안 된다.
3. `dry_run=True`에서 event·snapshot write가 모두 0이어야 한다.
4. operations refresh는 tracked ticker reader를 write store로 재사용하지 않아야 한다.
5. event write 두 메서드 중 하나라도 trading에 재도입되면 guard가 실패해야 한다.

---

### Task 1: build_events와 operations caller를 ResearchStore write로 이관

**Files:**
- Modify: `src/investment_agent/research/commands/build_events.py`
- Modify: `src/investment_agent/operations/commands/event_reanalysis.py`
- Modify: `tests/investment_agent/research/commands/test_build_events.py`
- Create: `tests/investment_agent/operations/commands/test_event_reanalysis.py`
- Modify: `docs/superpowers/architecture-refactor-progress.md`

**Interfaces:**
- Consumes: `ResearchStore.save_events(events)`와 `save_event_features(snapshots)`.
- Produces: `build_events(*, cache: LocalEvidenceCache, as_of_at: str, tickers: Sequence[str], window_days: int = DEFAULT_WINDOW_DAYS, dry_run: bool = False, store: ResearchStore | None = None) -> dict[str, Any]`.

- [ ] **Step 1: 실패 테스트 작성.** research 테스트의 `_Repository`를 `_EventStore`로 바꾸고 모든 호출에서 `store=store`를 넘긴다. 저장·filter·cutoff assertion은 store를 읽고 dry-run은 두 collection이 비었는지 확인한다.

operations test는 `_refresh_events()`가 `SupabaseRepository.current_tracked_tickers()`를 읽되 `build_events`에 `repository`를 넘기지 않는 계약을 고정한다. `LocalEvidenceCache`와 `build_events`를 patch하고 아래를 확인한다.

```python
kwargs = build.call_args.kwargs
self.assertEqual(kwargs["tickers"], ["AAPL"])
self.assertNotIn("repository", kwargs)
```

- [ ] **Step 2: RED 확인.** Run: `python -m unittest tests.investment_agent.research.commands.test_build_events tests.investment_agent.operations.commands.test_event_reanalysis -q`. Expected: `build_events() got an unexpected keyword argument 'store'` 또는 operations caller의 `repository` assertion 실패.

- [ ] **Step 3: 최소 구현.** `EventRepository` Protocol과 관련 import를 제거하고 `ResearchStore | None` store 인자를 추가한다. `if not dry_run:` 안에서만 `selected_store = store or ResearchStore()`를 만든 뒤 기존 순서대로 events와 snapshots를 저장한다. `main()`과 `_refresh_events()`는 tracked reader를 ticker 조회에만 쓰고 `build_events`의 `repository=` 인자를 제거한다.

- [ ] **Step 4: GREEN·architecture 확인.** Run: `python -m unittest tests.investment_agent.research.commands.test_build_events tests.investment_agent.operations.commands.test_event_reanalysis tests.investment_agent.trading.decision.test_event_impact tests.investment_agent.test_architecture -q`. Expected: 모두 통과.

- [ ] **Step 5: 원장·커밋.** `git commit -m "refactor: route event artifacts to research storage"`.

### Task 2: event write façade 제거와 owner guard 확장

**Files:**
- Modify: `src/investment_agent/trading/supabase_repository.py`
- Modify: `tests/investment_agent/trading/test_repository_ownership.py`
- Modify: `docs/superpowers/architecture-refactor-progress.md`

**Interfaces:**
- Consumes: Task 1의 direct ResearchStore event writes.
- Produces: `save_events`와 `save_event_features` 호출은 research owner 안에만 존재한다.

- [ ] **Step 1: 실패 가드 작성.** `RESEARCH_WRITE_METHODS`에 `save_events`, `save_event_features`를 추가하고 합성 trading source의 두 호출을 detector가 반환하는지 검증한다.

- [ ] **Step 2: RED 확인.** Run: `python -m unittest tests/investment_agent/trading/test_repository_ownership.py -q`. Expected: trading façade의 기존 두 호출로 실패.

- [ ] **Step 3: 최소 구현.** `SupabaseRepository.save_events()`와 `save_event_features()` 정의만 삭제한다.

- [ ] **Step 4: caller·GREEN 확인.** Run: `rg -n 'save_(events|event_features)' src/investment_agent tests/investment_agent --glob '*.py'`. Expected: ResearchStore·research command·test store·guard만 남는다. Run: `python -m unittest tests/investment_agent/research/commands/test_build_events.py tests/investment_agent/operations/commands/test_event_reanalysis.py tests/investment_agent/trading/test_repository_ownership.py tests/investment_agent/test_architecture.py -q`. Expected: 모두 통과.

- [ ] **Step 5: 실제 위반 주입.** trading façade에 각 write를 한 건씩 별도로 임시 주입해 guard 실패를 확인하고 원복한다. 최종 GREEN을 다시 실행한다.

- [ ] **Step 6: 원장·커밋.** `git commit -m "refactor: remove event writes from trading facade"`.

### Task 3: event 경계 통합 검증과 training sample 인계

**Files:**
- Modify: `docs/superpowers/architecture-refactor-progress.md`

**Interfaces:**
- Consumes: Task 1·2의 event write 방향과 operations caller.
- Produces: training sample/run manifest 경계의 다음 계획 입력.

- [ ] **Step 1: Run:** `python -m unittest tests.investment_agent.test_architecture tests.test_repo_conventions tests.test_workflow_wiring -q`. Expected: 100개 이상 통과.
- [ ] **Step 2: Run:** `python -m unittest tests/investment_agent/research/commands/test_build_events.py tests/investment_agent/operations/commands/test_event_reanalysis.py tests/investment_agent/trading/decision/test_event_impact.py tests/investment_agent/trading/test_repository_ownership.py -q`. Expected: 모두 통과.
- [ ] **Step 3: 시작 HEAD 이후 diff·status·pending 수·event façade caller 0건을 확인하고 사용자 변경과 graphify 산출물을 제외한다.
- [ ] **Step 4: 진행 원장에 완료 범위와 `build_training_samples.py`의 정확한 read/write·manifest caller를 기록하고 `git commit -m "docs: record event storage checkpoint"`.

## 다음 계획의 경계

`build_training_samples.py`는 sample 저장 결과의 inserted count와 날짜별 completion manifest를 함께 사용한다. event처럼 기계적으로 두 메서드만 옮기지 말고, sample 저장 실패 시 run manifest가 기록되지 않는 현재 순서와 재시작 semantics를 먼저 테스트로 고정한다.
