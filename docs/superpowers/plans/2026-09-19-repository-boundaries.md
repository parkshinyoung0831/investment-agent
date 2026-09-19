# Research 저장 경계 첫 이관 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Research feature·label 저장 호출을 Trading의 `SupabaseRepository`에서 Research의 `ResearchStore`로 직접 옮기고, 해당 호환 메서드 두 개를 제거한다.

**Architecture:** data/PIT 읽기와 Research DuckDB 쓰기를 별도 객체로 주입한다. 기존 계산·저장 데이터 형식·CLI 인자는 유지하고, 먼저 테스트에서 쓰기 경계 분리를 요구한 다음 구현한다. 이 계획은 Phase 2의 첫 독립 단위이며 research→trading 전체 해소나 God repository 전체 삭제를 완료했다고 주장하지 않는다.

**Tech Stack:** Python 3.11 기준, `unittest`, Research DuckDB·Parquet, 기존 Postgres owner read, AST architecture test.

**Spec:** `docs/superpowers/specs/2026-09-19-dependency-direction-design.md`

## Global Constraints

- `AGENTS.md`와 `CLAUDE.md`가 우선이다. 영구 architecture SSOT는 현재 코드·영역 문서에 둔다.
- `LIVE_ENABLED`·`TOSS_LIVE_ENABLED`를 코드가 자동으로 바꾸지 않는다.
- 하네스·execution 코드를 고치기 전 maintenance를 켠다. 이 계획은 그 코드를 고치지 않는다.
- DB schema, 투자 계산, PIT cutoff, source kind, 저장 batch 원자성, CLI 경로를 바꾸지 않는다.
- 대량 읽기에서 `select_all_paged()`를 유지한다. `.env`·비밀값은 추가·커밋하지 않는다.
- `from __future__ import annotations`를 첫 import로 둔다. 주석·docstring은 한국어다.
- 각 task는 RED → GREEN → 해당 경로 import/architecture 검증 → 커밋 → 진행 원장 갱신으로 끝낸다.
- 기준선 전체 테스트의 기존 오류 4개는 `lightgbm`·`xgboost` 미설치다. 최종 검증에서 동일 여부를 확인하고 새 회귀와 구분한다.

## File Structure

- `src/investment_agent/research/commands/build_features.py`: PIT 읽기 `repository`와 feature 저장 `store`를 구분하는 유스케이스.
- `src/investment_agent/research/commands/build_labels.py`: PIT·미래 가격 읽기와 label 저장을 구분하는 유스케이스.
- `src/investment_agent/research/storage/repository.py`: 기존 검증·batch 저장 owner. 이 계획에서 구현을 재작성하지 않는다.
- `src/investment_agent/trading/supabase_repository.py`: feature·label write 호환 메서드 제거. 나머지 façade는 후속 계획이 소유한다.
- `tests/investment_agent/research/commands/test_build_features_resilience.py`, `tests/investment_agent/research/features/test_store.py`: 쓰기 대상·failure·dry-run·PIT 계약.
- `tests/investment_agent/research/rl/test_repository.py`, `tests/investment_agent/trading/test_repository_ownership.py`: 저장 검증 owner와 façade 축소.
- `tests/investment_agent/test_architecture.py`: 실제 남은 dependency와 무관한 허용 목록 변경을 하지 않는다. 새 가드가 필요하면 호출자 0건을 검사하고 위반 주입으로 검증한다.
- `docs/superpowers/architecture-refactor-progress.md`: 각 task의 커밋·테스트·남은 부채 인계.

## Review Focus

1. `dry_run=True`와 빈 결과에서 Research DB를 열거나 쓰지 않아야 한다. Task 1·2 테스트에서 store의 호출 0건으로 고정한다.
2. 저장 실패 때 성공 행 수를 보고하거나 부분 batch로 성공 처리하지 않아야 한다. Task 1의 150종목 예외 테스트를 유지한다.
3. forward window가 열려 있는 label을 저장하지 않아야 한다. Task 2의 기존 pending-window 테스트와 store 호출 0건을 확인한다.
4. feature/label batch의 중복 identity나 변조된 hash가 검증 전에 DB에 쓰이면 안 된다. Task 3에서 ResearchStore의 기존 검증 테스트를 실행한다.
5. façade를 제거한 뒤 동적 호출이나 테스트 alias가 남아 import error를 만들 수 있다. Task 3에서 production·tests 전체 호출자 검색과 관련 unittest를 실행한다.

---

### Task 1: feature snapshot 저장을 Research owner로 직접 연결

**Files:**
- Modify: `src/investment_agent/research/commands/build_features.py:15-20,95-107,153-157,190-201`
- Modify: `tests/investment_agent/research/commands/test_build_features_resilience.py:14-70`
- Modify: `docs/superpowers/architecture-refactor-progress.md`

**Interfaces:**
- Consumes: 기존 `ResearchStore.save_rl_feature_snapshots(rows: Sequence[dict[str, Any]]) -> None`.
- Produces: `build_features(*, as_of_at: datetime, tickers: list[str], source_kind: str = "live_shadow", dry_run: bool = False, repository: SupabaseRepository | None = None, store: ResearchStore | None = None, workers: int | None = None) -> dict[str, object]`.

- [ ] **Step 1: 실패 테스트 작성.** `_CountingRepository`에서 `save_rl_feature_snapshots` 구현을 없애고 별도 `_CountingStore`를 주입한다. 기존 250종목·실패 테스트를 다음 계약으로 바꾼다.

```python
class _CountingStore:
    def __init__(self, *, fail_saving: bool = False):
        self.saved = []
        self.fail_saving = fail_saving

    def save_rl_feature_snapshots(self, rows):
        if self.fail_saving:
            raise OSError("research store is busy")
        self.saved.append(list(rows))

store = _CountingStore()
payload = build_features(as_of_at=AS_OF, tickers=tickers, repository=_CountingRepository(), store=store)
self.assertEqual([len(batch) for batch in store.saved], [250])

failing_store = _CountingStore(fail_saving=True)
with self.assertRaises(OSError):
    build_features(as_of_at=AS_OF, tickers=[f"T{i:03d}" for i in range(150)],
                   repository=_CountingRepository(), store=failing_store)
self.assertEqual(failing_store.saved, [])

dry_store = _CountingStore()
build_features(as_of_at=AS_OF, tickers=["AAA"], dry_run=True,
               repository=_CountingRepository(), store=dry_store)
self.assertEqual(dry_store.saved, [])
```

기존 테스트의 저장 assertion은 모두 별도 store를 대상으로 옮긴다.

- [ ] **Step 2: RED 확인.** Run: `python -m unittest tests.investment_agent.research.commands.test_build_features_resilience -q`. Expected: `build_features() got an unexpected keyword argument 'store'`.
- [ ] **Step 3: 최소 구현.** `ResearchStore`를 import하고 위 인터페이스의 `store`를 추가한다. 저장 조건 안에서만 `(store or ResearchStore()).save_rl_feature_snapshots(rows)`를 호출한다. `repository`는 기존 PIT read·ContextBuilder용으로 유지한다. CLI `main()`은 기존 인자를 유지하되 `build_features`가 기본 store를 열게 한다.

```python
from investment_agent.research.storage.repository import ResearchStore

if not dry_run and rows:
    (store or ResearchStore()).save_rl_feature_snapshots(rows)
    saved = len(rows)
```

- [ ] **Step 4: GREEN·import 확인.** Run: `python -m unittest tests.investment_agent.research.commands.test_build_features_resilience tests.investment_agent.research.features.test_store -q`. Expected: 모두 통과. Run: `python -m unittest tests.investment_agent.test_architecture -q`. Expected: 모두 통과.
- [ ] **Step 5: 커밋·인계.** 변경 소스·테스트·진행 원장만 stage하고 `git commit -m "refactor: route feature snapshots to research storage"`. 원장에는 수정 전/후 호출·테스트·남은 façade 메서드를 기록한다.

### Task 2: label 저장을 Research owner로 직접 연결

**Files:**
- Modify: `src/investment_agent/research/commands/build_labels.py:15-25,72-88,200-209,250-260`
- Modify: `tests/investment_agent/research/features/test_store.py:340-380`
- Modify: `docs/superpowers/architecture-refactor-progress.md`

**Interfaces:**
- Consumes: `ResearchStore.save_rl_training_labels(rows: Sequence[dict[str, Any]]) -> None`.
- Produces: `build_labels(*, as_of_at: datetime, horizon_days: int, lookback_days: int, benchmark: str = DEFAULT_BENCHMARK, dry_run: bool = False, repository: SupabaseRepository | None = None, store: ResearchStore | None = None) -> dict[str, object]`.

- [ ] **Step 1: 실패 테스트 작성.** `_LabelRepository`의 저장 메서드를 별도 `_LabelStore`로 옮기고 `_run()`이 둘을 분리해 주입하도록 바꾼다. 기존 정상 label·pending-window·단일 batch 검증을 모두 store 기준으로 수정한다.

```python
class _LabelStore:
    def __init__(self):
        self.saved = []
        self.save_calls = 0

    def save_rl_training_labels(self, rows):
        self.save_calls += 1
        self.saved.extend(rows)

store = _LabelStore()
payload = build_labels(
    as_of_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
    horizon_days=5, lookback_days=90, repository=_LabelRepository(forward_days=8), store=store,
)
self.assertEqual(store.save_calls, 1)
self.assertEqual(payload["detail"]["built"], 1)

pending_store = _LabelStore()
build_labels(as_of_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
             horizon_days=5, lookback_days=90,
             repository=_LabelRepository(forward_days=3), store=pending_store)
self.assertEqual(pending_store.save_calls, 0)

dry_store = _LabelStore()
build_labels(as_of_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
             horizon_days=5, lookback_days=90, dry_run=True,
             repository=_LabelRepository(forward_days=8), store=dry_store)
self.assertEqual(dry_store.save_calls, 0)
```

기존 `_run()`은 `store`를 생성해 위 코드와 동일한 `as_of_at`·`horizon_days`·`lookback_days`·`repository`·`store` 인자로 `build_labels`를 호출하고 `(payload, store)`를 반환하게 바꾼다. 해당 클래스의 기존 테스트 assertion도 반환된 store의 `saved`·`save_calls`를 읽는다.

- [ ] **Step 2: RED 확인.** Run: `python -m unittest tests.investment_agent.research.features.test_store -q`. Expected: `build_labels() got an unexpected keyword argument 'store'`.
- [ ] **Step 3: 최소 구현.** `ResearchStore` import, 위 인터페이스의 `store` 인자, 저장 조건 안의 `(store or ResearchStore()).save_rl_training_labels(rows)`를 추가한다. 기존 `selected`의 PIT read와 forward-price read는 변경하지 않는다.

```python
from investment_agent.research.storage.repository import ResearchStore

if not dry_run and rows:
    (store or ResearchStore()).save_rl_training_labels(rows)
    saved = len(rows)
```

- [ ] **Step 4: GREEN·import 확인.** Run: `python -m unittest tests.investment_agent.research.features.test_store tests.investment_agent.research.rl.test_repository -q`. Expected: 모두 통과. Run: `python -m unittest tests.investment_agent.test_architecture -q`. Expected: 모두 통과.
- [ ] **Step 5: 커밋·인계.** `git commit -m "refactor: route forward labels to research storage"`. 진행 원장에 저장 호출 방향과 PIT/read 변화 없음, 테스트 결과, 남은 façade를 기록한다.

### Task 3: 사용이 끝난 feature·label 호환 쓰기 메서드 제거

**Files:**
- Modify: `src/investment_agent/trading/supabase_repository.py:1229-1234`
- Modify: `tests/investment_agent/research/rl/test_repository.py:260-267`
- Modify: `tests/investment_agent/trading/test_repository_ownership.py:7-38`
- Modify: `docs/superpowers/architecture-refactor-progress.md`

**Interfaces:**
- Consumes: Task 1·2에서 직접 사용하는 `ResearchStore.save_rl_feature_snapshots`와 `ResearchStore.save_rl_training_labels`.
- Produces: `SupabaseRepository`에 `save_rl_feature_snapshots`와 `save_rl_training_labels`가 없음. 다른 façade API는 그대로다.

- [ ] **Step 1: 실패 가드 작성.** `RepositoryOwnershipTest`에 현재 façade의 두 연구 write가 없는지 검사한다. 변조 hash 테스트는 임시 ResearchStore 경로를 사용해 owner를 직접 호출하도록 바꾼다.

```python
def test_research_feature_and_label_writes_are_not_on_trading_facade(self):
    from investment_agent.trading.supabase_repository import SupabaseRepository

    self.assertFalse(hasattr(SupabaseRepository, "save_rl_feature_snapshots"))
    self.assertFalse(hasattr(SupabaseRepository, "save_rl_training_labels"))
```

```python
with tempfile.TemporaryDirectory() as temporary:
    store = ResearchStore(Path(temporary) / "research.duckdb")
    with self.assertRaisesRegex(RuntimeError, "input_hash"):
        store.save_rl_feature_snapshots([row])
```

- [ ] **Step 2: RED 확인.** Run: `python -m unittest tests/investment_agent/trading/test_repository_ownership.py -q`. Expected: 위 `assertFalse`가 두 기존 메서드에서 실패.
- [ ] **Step 3: 최소 구현.** `SupabaseRepository`의 `save_rl_feature_snapshots`와 `save_rl_training_labels` 메서드 정의 전체만 삭제한다. `_research_store()`는 다른 메서드가 사용하므로 삭제하지 않는다. 테스트 파일에 필요한 `tempfile`, `Path`, `ResearchStore` import를 추가한다.

```python
from investment_agent.research.storage.repository import ResearchStore

# SupabaseRepository에는 이 두 Research write 메서드가 더는 존재하지 않는다.
assert not hasattr(SupabaseRepository, "save_rl_feature_snapshots")
assert not hasattr(SupabaseRepository, "save_rl_training_labels")
```

- [ ] **Step 4: 전체 호출자·GREEN 확인.** Run: `rg -n 'save_rl_(feature_snapshots|training_labels)' src/investment_agent tests/investment_agent --glob '*.py'`. Expected: ResearchStore 소유 메서드와 직접 호출, 새 가드만 남고 `SupabaseRepository` 호출은 0건. Run: `python -m unittest tests/investment_agent/research/commands/test_build_features_resilience.py tests/investment_agent/research/features/test_store.py tests/investment_agent/research/rl/test_repository.py tests/investment_agent/trading/test_repository_ownership.py tests/investment_agent/test_architecture.py -q`. Expected: 모두 통과.
- [ ] **Step 5: 새 가드 위반 주입.** 테스트 전용 임시 파일 또는 mock class에 제거한 메서드 하나를 되살려 위 가드가 실패함을 확인하고 원복한다. 하나씩 주입한다. 최종 위 GREEN command를 다시 실행한다.
- [ ] **Step 6: 커밋·인계.** `git commit -m "refactor: remove feature and label writes from trading facade"`. 원장에는 두 제거 메서드, 남은 `SupabaseRepository` 책임, `PENDING_DEPENDENCIES`가 아직 69쌍인 이유를 명시한다.

### Task 4: 첫 경계의 전체 검증과 다음 계획 인계

**Files:**
- Modify: `docs/superpowers/architecture-refactor-progress.md`

**Interfaces:**
- Consumes: Task 1~3의 저장 호출 방향과 테스트 결과.
- Produces: 다음 계획이 읽을 완료 기록. 후속 대상은 valuations·events·training samples 등 아직 façade를 통해 ResearchStore로 위임하는 연구 경로다.

- [ ] **Step 1: 검증.** Run: `python -m unittest tests.investment_agent.test_architecture tests.test_repo_conventions tests.test_workflow_wiring -q`. Expected: 기준선 99개 이상 통과. Run: `python -m unittest discover -s tests -t .`. Expected: 기존 선택적 ML 의존성 4개 오류를 제외한 새 오류 0개. 전체 출력의 error test 이름을 기준선과 대조한다.
- [ ] **Step 2: 최종 import·변경 범위 확인.** Run: `git diff 53b232bb1547a57d53dd45fa940c2f135c742edc --stat`와 `git status --short`. Expected: 연구 저장 경계·해당 테스트·진행 문서 외 제품 영역 변경 없음. `PENDING_DEPENDENCIES` 항목을 임의로 추가하지 않음.
- [ ] **Step 3: 인계 기록.** 진행 원장에 Phase 2의 완료 범위/미완료 범위, 호출 관계 전후, 수정·삭제 파일, import 변화, 테스트 결과, 기존 환경 오류, 다음 소단위의 정확한 파일명을 적는다. 기록 자체만 변경됐다면 `git commit -m "docs: record research storage migration checkpoint"`.

## 다음 계획의 경계

이 계획의 완료는 God repository 해체의 시작이지 완료가 아니다. 다음 계획은 `save_valuation_observations`, `save_events`, `save_event_features`, `save_training_samples`, `save_training_sample_runs` 등의 production 호출자와 테스트를 조사해 독립 수행한다. 이후 research의 일반 trading import 제거, execution 경계, broker, dashboard/reporting, notification, 관례 정리와 최종 façade 삭제·architecture 가드는 `architecture-target.md`의 순서를 따른다. 새 계획은 그 시점의 원격 `main`·작업 브랜치·변경된 caller를 다시 확인한다.
