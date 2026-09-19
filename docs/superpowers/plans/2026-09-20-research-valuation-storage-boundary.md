# Research valuation 저장 경계 이관 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PIT valuation observation의 저장 호출을 Trading의 `SupabaseRepository`에서 Research의 `ResearchStore`로 직접 옮기고, 사용이 끝난 façade write 메서드를 제거한다.

**Architecture:** 가격·재무·발행주식수·split을 읽는 repository와 재계산 가능한 valuation observation을 쓰는 store를 별도 객체로 주입한다. 계산, PIT cutoff, historical replay 준비, CLI, 저장 row 형식은 유지하며 새로운 interface나 façade는 만들지 않는다.

**Tech Stack:** Python 3.11, `unittest`, Research DuckDB·Parquet, 기존 Supabase owner read, AST ownership guard.

**Spec:** `docs/superpowers/specs/2026-09-19-dependency-direction-design.md`

## Global Constraints

- `AGENTS.md`와 `CLAUDE.md`가 우선이며 실제 source·caller·tests가 판정 근거다.
- DB schema, valuation 계산, PIT cutoff, `source_kind`, batch write, CLI 경로를 바꾸지 않는다.
- `dry_run=True` 또는 빈 row에서는 ResearchStore를 열거나 쓰지 않는다.
- `LIVE_ENABLED`·`TOSS_LIVE_ENABLED`를 바꾸지 않고 harness·execution 코드를 수정하지 않는다.
- `from __future__ import annotations`를 첫 import로 유지하고 주석·docstring은 한국어로 쓴다.
- 실패 테스트 → 최소 구현 → targeted·architecture 검증 → caller 0건 → 진행 원장 → 커밋 순서를 지킨다.
- 새 위반을 `PENDING_DEPENDENCIES`에 추가하지 않는다.

## File Structure

- `src/investment_agent/research/commands/build_valuations.py`: valuation 계산 use case. read repository와 write store를 분리한다.
- `src/investment_agent/research/storage/repository.py`: 기존 valuation 저장 owner. 구현은 재작성하지 않는다.
- `src/investment_agent/trading/supabase_repository.py`: 사용이 끝난 valuation write 호환 메서드만 제거한다.
- `tests/investment_agent/research/valuation/test_inputs.py`: live shadow 계산·저장·dry-run·single batch 계약.
- `tests/investment_agent/research/test_historical_replay_pit.py`: historical replay source kind·split restatement 계약.
- `tests/investment_agent/trading/test_repository_ownership.py`: Research write 호출 owner를 AST로 강제한다.
- `docs/superpowers/architecture-refactor-progress.md`: 실제 호출 관계·검증 결과·남은 debt.

## Review Focus

1. `historical_replay`가 날짜 단위 prefetch를 한 번 수행하고 observation의 `source_kind`를 유지해야 한다.
2. `dry_run=True`에서 store 호출과 `rows_upserted`가 모두 0이어야 한다.
3. 발행주식수나 재무가 부족한 observation도 missing reason과 함께 한 batch로 저장돼야 한다.
4. 230개 row도 store write 한 번으로 저장돼야 한다.
5. trading에 valuation write 호출이 다시 생기면 ownership guard가 실제로 실패해야 한다.

---

### Task 1: valuation write를 ResearchStore로 직접 연결

**Files:**
- Modify: `src/investment_agent/research/commands/build_valuations.py`
- Modify: `tests/investment_agent/research/valuation/test_inputs.py`
- Modify: `tests/investment_agent/research/test_historical_replay_pit.py`
- Modify: `docs/superpowers/architecture-refactor-progress.md`

**Interfaces:**
- Consumes: `ResearchStore.save_valuation_observations(rows: Sequence[dict[str, Any]]) -> None`.
- Produces: `build_valuations(*, as_of_at: datetime, tickers: list[str], source_kind: str = "live_shadow", dry_run: bool = False, repository: SupabaseRepository | None = None, store: ResearchStore | None = None) -> dict[str, object]`.

- [ ] **Step 1: 실패 계약 테스트 작성.** 두 테스트 모듈의 fake repository에서 `saved`, `save_calls`, `save_valuation_observations()`를 제거하고 다음 fake store를 둔다. 모든 `build_valuations()` 호출에 repository와 store를 별도로 넘기며 assertion은 store를 읽는다.

```python
class _ValuationStore:
    def __init__(self):
        self.saved: list[dict] = []
        self.save_calls = 0

    def save_valuation_observations(self, rows):
        self.save_calls += 1
        self.saved.extend(rows)
```

`test_dry_run_writes_nothing`은 store의 `saved == []`와 `save_calls == 0`을 모두 확인한다. historical replay 두 테스트도 별도 store에 저장된 row를 검증한다.

- [ ] **Step 2: RED 확인.** Run: `python -m unittest tests/investment_agent/research/valuation/test_inputs.py tests/investment_agent/research/test_historical_replay_pit.py -q`. Expected: `build_valuations() got an unexpected keyword argument 'store'`.

- [ ] **Step 3: 최소 구현.** `ResearchStore` import와 `store` 인자를 추가하고 write 조건 안에서만 owner를 연다.

```python
from investment_agent.research.storage.repository import ResearchStore

if not dry_run and rows:
    (store or ResearchStore()).save_valuation_observations(rows)
    saved = len(rows)
```

read는 계속 `selected`가 담당하며 historical replay prepare와 모든 valuation input을 변경하지 않는다.

- [ ] **Step 4: GREEN·architecture 확인.** Run: `python -m unittest tests/investment_agent/research/valuation/test_inputs.py tests/investment_agent/research/test_historical_replay_pit.py tests/investment_agent/test_architecture.py -q`. Expected: 모두 통과.

- [ ] **Step 5: 원장·커밋.** 실제 전후 caller, 수정 파일, import 방향, 테스트, 남은 façade를 진행 원장에 기록하고 `git commit -m "refactor: route valuations to research storage"`.

### Task 2: valuation write façade 제거와 owner guard 확장

**Files:**
- Modify: `src/investment_agent/trading/supabase_repository.py`
- Modify: `tests/investment_agent/trading/test_repository_ownership.py`
- Modify: `docs/superpowers/architecture-refactor-progress.md`

**Interfaces:**
- Consumes: Task 1의 direct `ResearchStore.save_valuation_observations` 호출.
- Produces: trading façade에 valuation write가 없고, `save_valuation_observations` 호출은 research owner 안에서만 허용된다.

- [ ] **Step 1: 실패 가드 작성.** `RESEARCH_WRITE_METHODS`에 `save_valuation_observations`를 추가하고 합성 trading source가 이 호출로 위반되는지 검증한다. 현재 façade body가 실제 위반으로 잡혀야 한다.

```python
RESEARCH_WRITE_METHODS = frozenset({
    "save_rl_feature_snapshots",
    "save_rl_training_labels",
    "save_valuation_observations",
})
```

- [ ] **Step 2: RED 확인.** Run: `python -m unittest tests/investment_agent/trading/test_repository_ownership.py -q`. Expected: `trading/supabase_repository.py`의 valuation write 호출 1건으로 실패.

- [ ] **Step 3: 최소 구현.** `SupabaseRepository.save_valuation_observations()` 정의 전체만 삭제한다. `_research_store()`와 다른 façade 메서드는 현재 caller가 있으므로 유지한다.

- [ ] **Step 4: caller·GREEN 확인.** Run: `rg -n 'save_valuation_observations' src/investment_agent tests/investment_agent --glob '*.py'`. Expected: ResearchStore, research command, research test store와 guard만 남고 trading façade 호출은 0건. Run: `python -m unittest tests/investment_agent/research/valuation/test_inputs.py tests/investment_agent/research/test_historical_replay_pit.py tests/investment_agent/trading/test_repository_ownership.py tests/investment_agent/test_architecture.py -q`. Expected: 모두 통과.

- [ ] **Step 5: 실제 위반 주입.** trading façade에 valuation write 호출을 임시로 한 건 추가하고 ownership test가 실패함을 확인한 뒤 즉시 원복한다. 최종 GREEN command를 다시 실행한다.

- [ ] **Step 6: 원장·커밋.** 제거된 façade 메서드, 남은 dependency debt와 테스트를 기록하고 `git commit -m "refactor: remove valuation write from trading facade"`.

### Task 3: 통합 검증과 다음 Research write 인계

**Files:**
- Modify: `docs/superpowers/architecture-refactor-progress.md`

**Interfaces:**
- Consumes: Task 1·2의 valuation 저장 방향과 guard.
- Produces: event/event feature 또는 training sample 중 다음 실제 caller 단위의 재검증 입력.

- [ ] **Step 1: 구조 검증.** Run: `python -m unittest tests.investment_agent.test_architecture tests.test_repo_conventions tests.test_workflow_wiring -q`. Expected: 100개 이상 통과.

- [ ] **Step 2: 관련 전체 검증.** Run: `python -m unittest tests/investment_agent/research/valuation/test_inputs.py tests/investment_agent/research/test_historical_replay_pit.py tests/investment_agent/research/commands/test_backfill_research_history.py tests/investment_agent/trading/test_repository_ownership.py -q`. Expected: 모두 통과.

- [ ] **Step 3: 범위·debt 확인.** 시작 HEAD 이후 diff, `git status`, `PENDING_DEPENDENCIES` 수, valuation façade caller 0건을 확인한다. 기존 사용자 미커밋 변경과 graphify 산출물은 이 계획 커밋에 섞지 않는다.

- [ ] **Step 4: 인계·커밋.** 진행 원장에 완료/미완료 범위와 다음 exact caller를 기록하고, 문서만 남으면 `git commit -m "docs: record valuation storage checkpoint"`.

## 다음 계획의 경계

다음 후보는 `research/commands/build_events.py`의 `save_events`·`save_event_features`와 `research/commands/build_training_samples.py`의 `save_training_samples`·`save_training_sample_runs`다. 두 경로는 각각 event source interface와 재시작 manifest semantics가 있으므로 하나의 generic writer로 합치지 않고 caller·tests를 다시 읽은 뒤 별도 task로 결정한다.
