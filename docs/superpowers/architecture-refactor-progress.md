# 의존성 방향 리팩터링 — 진행 원장

> 사용자가 요청한 새 세션 인계 문서다. 이것은 현재 아키텍처 SSOT가 아니다. 새 세션은 `AGENTS.md` → `CLAUDE.md` → `docs/superpowers/specs/2026-09-19-dependency-direction-design.md` → `docs/superpowers/architecture-target.md` → 이 파일 → 현재 계획 순서로 읽는다. 기록보다 Git·코드·테스트의 실제 상태가 우선한다.

## 식별과 현재 상태

- 기준 원격 `main`: `4181f6b53d84105f2b78d78c69e9119c1f55a6cf` (2026-09-20 세션 시작 시 로컬 HEAD와 일치 확인).
- 통합 작업 브랜치: `main`. 모든 phase는 이 브랜치의 연속 커밋과 이 진행 원장 하나로 추적한다. 임시 검증 브랜치를 만들더라도 완료 내용을 `main`에 통합한 뒤 이 원장을 갱신한다.
- 통합 기반 HEAD: `d30e2e5e7ce320641349ceb2d3d5a5c6ddbff6dc`에서 문서 브랜치를 `main`에 fast-forward했고 임시 브랜치를 삭제했다. 이후 커밋은 이 지점부터 이어진다.
- 현재 단계: Phase 3의 Research 공통 serialization import 후속 정리 중. valuation 세 곳 완료, command·RL/backtest·ML 묶음이 남았다.
- 현재 계획: `docs/superpowers/plans/2026-09-20-research-shared-serialization-imports.md` (Task 1 완료, Task 2~4 남음).
- 완료 단계: Phase 1 조사와 Phase 2의 feature snapshot·training label·valuation·event artifact write 직접 이관, 관련 façade 메서드 제거. 현재 `PENDING_DEPENDENCIES`는 68쌍이다.
- maintenance 상태: 확인·설정하지 않았다. 하네스 또는 execution 코드를 수정하기 전에 `harness_switch --maintenance on`을 수행하고 상태를 확인한다. live flag는 변경하지 않는다.

## 검증 기준선

| 검사 | 결과 | 의미 |
|---|---|---|
| `git ls-remote origin refs/heads/main` | 로컬 HEAD와 동일 SHA | 최신 `main` 기준 확인 |
| `python -m unittest tests.investment_agent.test_architecture tests.test_repo_conventions tests.test_workflow_wiring -q` | 100개 통과 | 구조·관례·workflow 현재 기준선 |
| `python -m unittest discover -s tests -t .` | 3,009개, 오류 4개, skip 1개 | 오류는 기준선과 동일한 `test_ml_inference`의 `lightgbm`·`xgboost` 미설치 4개 |
| `tests/investment_agent/test_architecture.py` | `PENDING_DEPENDENCIES` 69쌍 | 줄여야 하는 현재 import 부채 |

## 새 세션 재개 절차

1. `git status --short --branch`, `git branch --show-current`, `git log -1 --oneline`, `git ls-remote origin refs/heads/main`으로 `main` 여부·미커밋 변경·원격 변화를 확인한다. 원격 `main`이 달라졌으면 무조건 자동 rebase하지 말고 차이를 검토한다.
2. 위 문서와 현재 계획을 읽고 마지막 완료 task/phase의 실제 커밋·테스트 출력을 확인한다. 이 파일의 기록만 믿고 이미 완료된 작업을 반복하지 않는다.
3. 각 phase를 시작하기 전에 호출자·대상·삭제 조건을 다시 확인한다. 하네스/실행 코드에는 maintenance 선행.
4. 단계별로 실패 테스트 → 최소 구현 → 대상 테스트 → import/architecture 테스트 → 가능한 전체 테스트를 수행하고 결과를 이 파일에 갱신한다.
5. 각 완료 기록에 `수정 전 호출 관계 / 이유 / 수정 파일 / 이동·삭제 파일 / import 방향 / 테스트 결과 / 남은 부채 / 다음 단계`를 빠짐없이 적는다. 계획의 별도 실행 ledger가 생기면 해당 경로와 task 번호를 함께 적는다.
6. `PENDING_DEPENDENCIES`의 정확한 남은 항목을 확인한다. 새 항목을 기준선에 추가하지 않는다.

## 단일 실행 워크플로

각 구현 묶음은 `현재 caller 재검증 → 실패 테스트 → 최소 이관 → 대상 테스트 → architecture/import 검증 → 가능한 전체 테스트 → 진행 원장 갱신 → 커밋` 순서로 진행한다. 한 단계가 끝나기 전에 다음 영역을 동시에 수정하지 않는다. 중단되면 마지막 커밋과 이 문서의 완료 task가 재개 지점이다.

진행 상태는 이 문서와 현재 plan의 checkbox만 사용한다. 별도의 날짜별 상태 보고서를 늘리지 않는다. 새로운 계획은 이전 계획의 완료 범위와 남은 debt를 입력으로 삼고, 완료된 façade나 테스트를 다시 만들지 않는다.

## 단계 기록

### Phase 1 — 기준 구조와 이관 대상

- 호출 관계: `operations.harness`가 research·trading·execution job을 조립한다. `research.commands.build_features`와 `trading.decision.analysis`가 `trading.supabase_repository.SupabaseRepository`를 사용한다. 승인 후 `operations.commands.create_execution_intent`가 `RiskGate`의 intent 생성 후 execution 원장에 저장하고, `execute_toss_live`가 Toss worker를 호출한다.
- 채택 근거: `SupabaseRepository` 95개 메서드·여러 저장 owner; research→trading 역방향 69쌍 기준선; 실제 worker의 Toss 결합; dashboard의 남은 4개 직접 DB 호출 화면.
- 보류 판단: data `persistence.py` 일괄 삭제, fundamentals 재작성, broker registry 신설, `ResearchStore` 크기만으로 분할은 하지 않는다.
- 수정 파일: 문서 4개(설계·목표·첫 구현 계획·이 원장). 제품 파일 없음.
- 이동·삭제 파일: 없음.
- import 방향 변화: 없음.
- 테스트: 위 기준선 참조.
- 남은 debt: `PENDING_DEPENDENCIES` 69쌍과 나머지 후보 모두 미이관.
- 다음 단계: 첫 구현 계획 검토 후 God repository에서 owner별 저장·읽기 경계의 첫 단위를 TDD로 분리.

### Phase 2 — Research 저장 경계 첫 이관

#### Task 1 — feature snapshot write

- 변경 전 호출 관계: `research.commands.build_features`가 PIT evidence를 읽는 `SupabaseRepository`에 `save_rl_feature_snapshots()`까지 호출했고, façade가 `ResearchStore`로 전달했다. feature entry·resilience·성능 테스트의 fake repository도 read와 write를 함께 흉내냈다.
- 변경 이유: 재계산 가능한 feature snapshot의 owner는 Research DuckDB이며, data/PIT read와 research write를 한 객체 계약으로 묶을 이유가 없다.
- 수정 파일: `src/investment_agent/research/commands/build_features.py`, `tests/investment_agent/research/commands/test_build_features_resilience.py`, `tests/investment_agent/research/features/test_store.py`, `tests/investment_agent/test_read_path_performance.py`, 이 원장.
- 이동·삭제 파일: 없음. façade의 호환 메서드는 Task 2와 호출자 재검증 뒤 Task 3에서 제거한다.
- import·runtime 방향 변화: `build_features`가 read용 `SupabaseRepository`와 write용 `ResearchStore`를 별도 주입받고 feature snapshot을 Research owner에 직접 저장한다. PIT cutoff·계산·batch 원자성·CLI 인자는 바뀌지 않았다. 일반 research→trading import는 아직 남아 있다.
- 테스트 결과: 계약 테스트는 기존 구현에서 `store` 인자 오류 3건으로 RED를 확인했다. 구현 후 feature resilience·store·read performance 40개와 architecture 22개가 통과했다.
- 제거된 debt: feature snapshot production write의 trading façade 경유 1곳.
- 남은 debt: `SupabaseRepository.save_rl_feature_snapshots` 호환 메서드와 테스트 caller 1곳, label write 경유, 나머지 God façade 책임, `PENDING_DEPENDENCIES` 69쌍.
- 다음 독립 작업: Task 2에서 label write를 같은 방식으로 ResearchStore에 직접 연결한다.

#### Task 2 — forward label write

- 변경 전 호출 관계: `research.commands.build_labels`가 snapshot·기존 label·미래 가격을 읽는 `SupabaseRepository`에 `save_rl_training_labels()`까지 호출했고, façade가 `ResearchStore`로 전달했다. label entry 테스트의 fake repository도 조회와 저장을 함께 소유했다.
- 변경 이유: 미래 구간이 닫힌 뒤 생성되는 label은 Research DuckDB 산출물이며, market/PIT read 계약과 write owner를 분리해야 한다.
- 수정 파일: `src/investment_agent/research/commands/build_labels.py`, `tests/investment_agent/research/features/test_store.py`, 이 원장.
- 이동·삭제 파일: 없음. 두 호환 write 메서드는 Task 3에서 실제 caller 0건과 owner guard를 확인한 뒤 제거한다.
- import·runtime 방향 변화: `build_labels`가 read용 `SupabaseRepository`와 write용 `ResearchStore`를 별도 주입받고 label을 Research owner에 직접 저장한다. snapshot cutoff, label cutoff, 미래 가격 window, batch 저장 조건과 CLI 인자는 바뀌지 않았다.
- 테스트 결과: 기존 구현에서 label 계약 5개가 `store` 인자 오류로 RED가 됐다. 구현 후 research feature/store·RL repository 33개와 architecture 22개가 통과했다.
- 제거된 debt: training label production write의 trading façade 경유 1곳.
- 남은 debt: façade의 두 미사용 호환 메서드, feature hash 검증 테스트의 façade caller, 나머지 God façade 책임과 `PENDING_DEPENDENCIES` 69쌍.
- 다음 독립 작업: Task 3에서 두 façade 메서드를 제거하고 Research write ownership guard를 위반 주입으로 검증한다.

#### Task 3 — feature·label write façade 제거

- 변경 전 호출 관계: Task 1·2 뒤 production write caller는 `research.commands.build_features`와 `build_labels`뿐이었지만, `SupabaseRepository`에는 ResearchStore로 전달하는 두 호환 메서드가 남아 있었다. 변조 hash 테스트도 feature owner가 아닌 trading façade를 통해 검증했다.
- 변경 이유: caller가 0인 호환 write를 남기면 이후 코드가 다시 trading façade에 결합할 수 있고, 실제 저장 검증 owner가 테스트에서 가려진다.
- 수정 파일: `src/investment_agent/trading/supabase_repository.py`, `tests/investment_agent/research/rl/test_repository.py`, `tests/investment_agent/trading/test_repository_ownership.py`, 이 원장.
- 이동·삭제 파일: 파일 이동·삭제는 없다. `SupabaseRepository.save_rl_feature_snapshots()`와 `save_rl_training_labels()` 메서드 두 개를 삭제했다.
- import·runtime 방향 변화: feature·label write는 research command → `ResearchStore`로만 흐른다. 변조 hash 검증도 `ResearchStore`를 직접 사용한다. AST ownership guard는 두 write 호출이 `src/investment_agent/research/**` 밖에 생기면 실패한다.
- 테스트 결과: 새 ownership guard가 기존 trading façade 호출 2건으로 RED가 되는 것을 확인했다. 제거 후 관련 63개가 통과했다. trading에 임시 위반 1건을 주입했을 때 guard 실패를 확인하고 원복한 뒤 같은 63개를 다시 통과시켰다.
- 제거된 debt: trading façade의 feature snapshot·training label write 책임과 façade를 통하던 validation test caller.
- 남은 debt: `SupabaseRepository`에는 valuation·event·training sample·promotion 등 다른 Research 저장/조회와 data read·trading/execution 책임이 남아 있다. `build_features`·`build_labels`의 read·계약 import도 trading을 향하므로 `PENDING_DEPENDENCIES` 69쌍은 아직 줄지 않았다.
- 다음 독립 작업: Task 4 통합 검증 후, 현재 caller를 다시 조사해 valuation·event·training sample 중 가장 작은 Research owner 이관 계획을 작성한다.

#### Task 4 — 첫 경계 통합 검증

- 변경 전·후 호출 관계: feature와 label write는 `research command → SupabaseRepository → ResearchStore`에서 `research command → ResearchStore`로 바뀌었다. `SupabaseRepository`의 두 호환 메서드와 이를 호출하는 production·test caller는 0건이다.
- 수정 파일 전체: `research/commands/build_features.py`, `research/commands/build_labels.py`, `trading/supabase_repository.py`, 직접 연결된 research·trading 테스트 5개와 이 원장. 다른 production 영역은 수정하지 않았다.
- 이동·삭제 파일: 파일 이동·삭제 없음. façade 메서드 두 개만 삭제했다. 시작 HEAD 이후 변경은 9개 파일, 209 insertions, 45 deletions다.
- import 방향: write runtime은 Research owner로 바로 향하지만 두 command의 PIT reader·trading 계약 import는 유지했으므로 일반 research→trading dependency debt는 아직 감소하지 않았다. 이를 façade나 alias로 숨기지 않았고 `PENDING_DEPENDENCIES`는 69쌍 그대로다.
- 테스트 결과: architecture·repo convention·workflow 100개 통과. 전체 suite는 3,009개 중 기준선과 동일한 `tests/investment_agent/research/test_ml_inference.py` 선택적 ML 의존성 오류 4개, skip 1개이며 새 실패는 없다. ownership guard는 합성 source와 실제 임시 trading 호출 주입 모두에서 위반을 검출했다.
- 보존 확인: DB schema, PIT/read, feature·label 계산, source kind, CLI 경로, batch write 조건, live flag와 execution/harness는 변경하지 않았다. maintenance 전환이 필요한 코드는 건드리지 않았다.
- 남은 debt: valuation·event·event feature·training sample·training run과 여러 research read가 trading façade를 경유한다. data read·trading 원장·execution snapshot 책임도 같은 façade에 남아 있다.
- 다음 독립 작업: `src/investment_agent/research/commands/build_valuations.py`의 `save_valuation_observations` caller와 `tests/investment_agent/research/valuation/test_inputs.py`, `tests/investment_agent/research/test_historical_replay_pit.py`를 먼저 재검증한다. 이어서 `build_events.py`와 `build_training_samples.py`를 각각 독립 단위로 판단한다.

#### Valuation Task 1 — observation write 직접 연결

- 변경 전 호출 관계: `research.commands.build_valuations`가 가격·재무·발행주식수·split을 읽는 `SupabaseRepository`에 valuation write도 호출했고 façade가 ResearchStore로 전달했다. live·historical 테스트 fake도 read와 write를 함께 소유했다.
- 변경 이유: valuation observation은 PIT 원천을 입력으로 다시 계산할 수 있는 Research 산출물이며, Supabase read interface와 Research DuckDB write interface를 한 객체로 요구할 이유가 없다.
- 수정 파일: `src/investment_agent/research/commands/build_valuations.py`, `tests/investment_agent/research/valuation/test_inputs.py`, `tests/investment_agent/research/test_historical_replay_pit.py`, 이 원장.
- 이동·삭제 파일: 없음. façade 호환 메서드는 다음 task에서 caller 0건을 확인한 뒤 제거한다.
- import·runtime 방향: valuation 계산은 기존 `SupabaseRepository` read를 유지하고 write만 직접 `ResearchStore`로 향한다. historical replay prepare, PIT cutoff, source kind, split restatement, row 형식과 CLI는 변하지 않았다.
- 테스트 결과: 기존 구현에서 9개 계약이 `store` 인자 오류로 RED가 됐다. 구현 후 valuation·historical replay·architecture 55개가 통과했다.
- 제거된 debt: valuation production write의 trading façade 경유 1곳.
- 남은 debt: `SupabaseRepository.save_valuation_observations` 메서드와 다른 Research façade 책임, research→trading read·계약 import, `PENDING_DEPENDENCIES` 69쌍.
- 다음 독립 작업: valuation write owner guard를 확장하고 façade 메서드를 제거한다.

#### Valuation Task 2 — façade 제거와 owner guard

- 변경 전 호출 관계: direct write 이관 뒤 `SupabaseRepository.save_valuation_observations()`의 production caller는 0건이었지만 메서드 body가 ResearchStore에 계속 의존했다.
- 변경 이유: 미사용 호환 write가 남으면 research command가 다시 trading façade로 회귀할 수 있으므로 actual caller 0건 뒤 제거하고 owner 규칙을 확장했다.
- 수정 파일: `src/investment_agent/trading/supabase_repository.py`, `tests/investment_agent/trading/test_repository_ownership.py`, 이 원장.
- 이동·삭제 파일: 파일 이동·삭제 없음. valuation write façade 메서드 1개를 삭제했다.
- import·runtime 방향: `save_valuation_observations` 호출은 `src/investment_agent/research/**` 안에만 존재한다. AST guard가 feature·label과 함께 valuation write owner도 강제한다.
- 테스트 결과: guard 확장 후 기존 façade 호출 1건으로 RED를 확인했다. 제거 후 관련 59개가 통과했고, 임시 trading 위반 1건 주입 시 guard 실패를 확인했다.
- 제거된 debt: trading façade의 valuation write 책임.
- 남은 debt: valuation read와 다른 Research artifact read/write, data read, trading·execution persistence가 façade에 남아 있으며 `PENDING_DEPENDENCIES`는 69쌍이다.
- 다음 독립 작업: 통합 검증 후 event/event feature write caller를 재검증한다.

#### Valuation Task 3 — 통합 검증

- 변경 전·후 호출 관계: valuation write는 `research command → SupabaseRepository → ResearchStore`에서 `research command → ResearchStore`로 바뀌었고 trading façade method·caller는 0건이다.
- 수정 파일 전체: `research/commands/build_valuations.py`, `trading/supabase_repository.py`, valuation·historical replay·ownership 테스트 3개와 이 원장. 파일 이동·삭제와 schema 변경은 없다.
- import 방향: write dependency는 Research owner로 정렬됐다. valuation command가 사용하는 trading contract와 read façade import는 남아 있어 `PENDING_DEPENDENCIES`는 69쌍 그대로다.
- 테스트 결과: architecture·repo convention·workflow 100개와 valuation·historical replay·backfill·ownership 46개가 통과했다. valuation write guard는 실제 임시 trading 위반에서 실패했다.
- 범위 확인: 계획 시작 HEAD 이후 6개 파일, 85 insertions, 27 deletions다. 기존 사용자 변경과 현재 dirty graphify 산출물은 커밋에 섞지 않았다.
- 남은 debt: `SupabaseRepository`의 event/event feature, training sample/run, promotion·evaluation read/write와 data/trading/execution 책임.
- 다음 독립 작업: `src/investment_agent/research/commands/build_events.py`의 `EventRepository` interface와 `tests/investment_agent/research/commands/test_build_events.py`를 다시 읽어 read/source와 two-write atomicity를 분리할 수 있는지 판정한다.

#### Event Task 1 — event artifact write 직접 연결

- 변경 전 호출 관계: `build_events`의 `EventRepository`는 두 Research write만 선언했지만 production adapter는 `SupabaseRepository` 하나였고, command main과 `operations.commands.event_reanalysis`가 tracked ticker reader를 event store로도 재사용했다.
- 변경 이유: cache read와 Research artifact write는 이미 별도 저장소이므로 얕은 pass-through interface와 trading façade 경유를 제거하고 operations는 read 조립만 담당하게 한다.
- 수정 파일: `src/investment_agent/research/commands/build_events.py`, `src/investment_agent/operations/commands/event_reanalysis.py`, `tests/investment_agent/research/commands/test_build_events.py`, 새 `tests/investment_agent/operations/commands/test_event_reanalysis.py`, `tests/investment_agent/test_architecture.py`, 이 원장.
- 이동·삭제 파일: 없음. command-local `EventRepository` Protocol을 제거했다.
- import·runtime 방향: `build_events`는 lazy `ResearchStore` write를 직접 소유하고, main·operations caller의 SupabaseRepository는 tracked ticker read에만 쓴다. Protocol 제거로 `build_events → trading.decision.contracts` import도 사라졌다.
- 테스트 결과: 새 store interface 4건과 operations composition 1건이 RED가 됐다. 구현 후 event·operations·event impact·architecture 36개가 통과했다.
- 제거된 debt: event production write의 trading façade 경유 2곳 중 command caller, 그리고 `PENDING_DEPENDENCIES`의 `build_events → trading.decision.contracts` 1쌍(69→68).
- 남은 debt: façade의 두 event write 메서드와 `build_events`의 trading contracts/cache/Supabase read imports.
- 다음 독립 작업: 두 façade 메서드를 제거하고 event write owner guard를 확장한다.

#### Event Task 2 — façade 제거와 owner guard

- 변경 전 호출 관계: Task 1 뒤 event write production caller는 Research command만 남았지만 trading façade의 두 forwarding method와 그 전용 Event 타입 import가 남아 있었다.
- 변경 이유: caller 0인 event write façade를 제거하고 event artifact write가 Research owner 밖으로 다시 새지 않게 기존 AST guard를 확장한다.
- 수정 파일: `src/investment_agent/trading/supabase_repository.py`, `tests/investment_agent/trading/test_repository_ownership.py`, 이 원장.
- 이동·삭제 파일: 파일 이동·삭제 없음. `save_events`, `save_event_features` façade 메서드와 사용이 끝난 Event 타입 import를 삭제했다.
- import·runtime 방향: 두 event write 호출은 `src/investment_agent/research/**`에만 남는다.
- 테스트 결과: guard 확장 후 기존 façade 2건으로 RED를 확인했다. 제거 후 관련 31개가 통과했고 `save_events`, `save_event_features`를 각각 trading에 임시 주입했을 때 guard가 별도로 실패했다.
- 제거된 debt: trading façade의 event·event feature write 책임.
- 남은 debt: build_events의 trading contracts/cache/Supabase read imports와 다른 Research façade 메서드. `PENDING_DEPENDENCIES`는 68쌍이다.
- 다음 독립 작업: 통합 검증 후 training sample/run manifest write를 재검증한다.

#### Event Task 3 — 통합 검증과 일시 정지 지점

- 변경 전·후 호출 관계: event write는 `research command → SupabaseRepository → ResearchStore`에서 `research command → ResearchStore`로 바뀌었다. operations의 on-demand refresh는 `SupabaseRepository.current_tracked_tickers()`로 ticker만 읽고 event store로 재사용하지 않는다. trading·operations·dashboard·notifications에서 `save_events`와 `save_event_features` façade caller는 0건이다.
- 수정 파일 전체: `research/commands/build_events.py`, `operations/commands/event_reanalysis.py`, `trading/supabase_repository.py`, 직접 연결된 research·operations·trading·architecture 테스트 4개와 이 원장. 새 테스트 파일은 `tests/investment_agent/operations/commands/test_event_reanalysis.py`다.
- 이동·삭제 파일: production/test 파일 이동·삭제와 schema 변경은 없다. command-local `EventRepository` Protocol, trading façade의 event write 메서드 2개와 더 이상 쓰지 않는 `Event` import만 삭제했다.
- import·runtime 방향: event artifact write는 Research owner로 직접 향한다. 얕은 Protocol 제거와 함께 `build_events → trading.decision.contracts` import가 실제로 없어져 pending 1쌍을 삭제했다. `build_events`의 evidence cache·tracked ticker read 관련 trading import는 그대로 남겨 façade나 alias로 숨기지 않았다.
- 테스트 결과: architecture·repo convention·workflow 100개와 event command·operations composition·event impact·ownership 18개가 통과했다. 두 write별 실제 임시 위반 주입에서도 ownership guard 실패를 확인했다.
- 범위 확인: 계획 시작 HEAD `f84a2f8` 이후 제품·직접 테스트·원장 8개 파일, 116 insertions, 42 deletions이다. 기존 사용자 변경과 dirty graphify 산출물은 커밋에 섞지 않았다.
- 제거된 debt: event·event feature write의 trading façade 경유, command-local pass-through Protocol, `PENDING_DEPENDENCIES` 1쌍(69→68).
- 남은 debt: `build_events`의 trading cache/read import와 `SupabaseRepository`의 training sample/run, promotion·evaluation 및 여러 Research read façade가 남아 있다.
- 다음 독립 작업: 재개 시 `build_training_samples.py`를 새 계획으로 분리한다. 현재 이 command는 `SupabaseRepository` 하나에서 membership·feature·label·기간별 scalar·run manifest를 읽고, `save_training_samples()` 성공 뒤에만 `save_training_sample_runs()`를 호출한다. `ResearchStore`에는 sample·run read/write 구현이 이미 있으므로 먼저 `tests/investment_agent/research/commands/test_training_samples.py`에서 read/write store 분리와 저장 실패 시 manifest 미기록, inserted count, 재시작 semantics를 고정한다. `tests/investment_agent/trading/test_training_sample_persistence.py`의 façade 직접 검증도 실제 owner 테스트로 이관할지 caller와 함께 판정한다.

#### Training sample Task 1 — sample·manifest owner 직접 연결

- 변경 전 호출 관계: `build_training_samples`는 membership·feature/label input뿐 아니라 completion manifest read, sample write, manifest write까지 한 `SupabaseRepository`로 수행했다. façade는 후자의 세 메서드를 `ResearchStore`로 전달했다.
- 변경 이유: sample과 completion manifest는 Research DuckDB/Parquet 산출물이다. input reader와 산출물 저장 계약을 분리하면서 sample 성공 후 manifest 기록 순서를 고정해야 한다.
- 수정 파일: `src/investment_agent/research/commands/build_training_samples.py`, `tests/investment_agent/research/commands/test_training_samples.py`, 이 원장.
- 이동·삭제 파일: 없음. façade 호환 메서드 3개는 다음 Task에서 직접 caller 0건 확인 뒤 제거한다.
- import·runtime 방향: command의 universe·feature/label·lightweight input read는 기존 `SupabaseRepository`에 남고, manifest는 기본 `ResearchStore(read_only=True)`로 읽는다. sample이 실제 생성되고 dry-run이 아닐 때만 writable `ResearchStore`를 열어 sample batch 저장 뒤 manifest를 기록한다. 주입 store는 read/write 양쪽에 사용한다.
- 테스트 결과: reader와 store를 분리한 15개 기존 계약이 구현 전 `store` 인자 오류로 RED였고, sample write 실패 시 manifest 미기록 및 저장 순서 계약을 추가했다. 구현 후 training sample·architecture 45개 통과, `git diff --check` 통과.
- 제거된 debt: command runtime의 training sample write와 completion manifest read/write가 trading façade를 경유하던 세 호출.
- 남은 debt: façade의 세 호환 메서드와 이를 직접 검증하는 trading 테스트 1개, Research feature/label read façade, `PENDING_DEPENDENCIES` 68쌍.
- 다음 독립 작업: 직접 Parquet no-rewrite 테스트를 Research owner로 옮긴 뒤 세 façade 메서드를 삭제하고 AST owner guard를 강화한다.

#### Training sample Task 2 — persistence 테스트 owner 이관과 façade 제거

- 변경 전 호출 관계: command가 ResearchStore를 직접 쓰도록 바뀐 뒤에도 `SupabaseRepository`에 sample write·manifest read/write forwarding 세 메서드가 남았고, trading 테스트 하나가 sample write façade를 직접 호출했다.
- 변경 이유: 실제 caller가 없는 호환 메서드가 다시 Research write를 trading façade로 끌어들이지 않게 제거하고, 저장 파일의 idempotency 검증을 실제 Research owner에 둔다.
- 수정 파일: `src/investment_agent/trading/supabase_repository.py`, `tests/investment_agent/trading/test_repository_ownership.py`, 이 원장.
- 이동·삭제 파일: `tests/investment_agent/trading/test_training_sample_persistence.py`를 `tests/investment_agent/research/test_training_sample_persistence.py`로 옮겨 직접 ResearchStore를 검증한다. façade의 세 메서드와 전용 `TrainingSample` import를 삭제했다. 새 schema·저장 구현은 없다.
- import·runtime 방향: sample·manifest read/write의 trading façade 경유가 0건이다. Research write AST guard가 `save_training_samples`, `save_training_sample_runs`를 owner 밖에서 호출하면 실패한다. test fixture의 임시 디렉터리 종료 후 조회는 종료 전에 수행하도록 고쳤다.
- 테스트 결과: guard 확장 직후 기존 trading façade의 두 write 호출 때문에 RED가 됐다. 삭제 후 training command·Research persistence·ownership·architecture 50개가 통과했고 guard의 합성 trading 위반 두 건이 검출된다.
- 제거된 debt: training sample·run manifest façade 메서드 3개와 trading 경로의 Research Parquet 직접 검증 테스트.
- 남은 debt: feature/label/metadata read façade와 기타 Research·Data/Trading/Execution 메서드, `PENDING_DEPENDENCIES` 68쌍.
- 다음 독립 작업: 구조·workflow 및 관련 Research storage 통합 테스트와 façade caller 0건을 재확인한다.

#### Training sample Task 3 — 통합 검증과 다음 read 경계 인계

- 변경 전·후 호출 관계: `build_training_samples → SupabaseRepository → ResearchStore`였던 sample write·manifest read/write는 `build_training_samples → ResearchStore`로 직접 연결됐다. `backfill_research_history`와 harness adapter는 기존 command API를 호출하며 변경하지 않았다.
- 수정 파일 전체: `research/commands/build_training_samples.py`, `trading/supabase_repository.py`, 직접 연결된 training command·Research persistence·ownership 테스트와 이 원장. trading의 persistence 테스트 하나를 Research 경로로 이동했다. schema, 계산, CLI, harness·execution은 변경하지 않았다.
- import·runtime 방향: sample·manifest façade 메서드 3개와 `TrainingSample` 타입 import를 trading에서 제거했다. trading·operations의 세 메서드 호출은 0건이며, test의 합성 위반 문자열만 남는다. feature/label input read는 여전히 trading façade를 거치므로 해당 역방향 dependency는 남는다.
- 테스트 결과: architecture·repo convention·workflow·training command·Research persistence·backfill·RL repository·ownership 147개 통과. `tests/test_docs_consistency.py` 7개 통과. 전체 suite는 3,012개 중 선택적 `lightgbm`·`xgboost` 미설치로 인한 기존 ML inference 오류 4개, skip 1개이며 추가 실패는 없다. 첫 전체 실행에서 과거 진행/계획 문서의 dotted unittest module 이름 11개가 SQL relation으로 오인된 문서 검사 실패 1개를 발견했다. 해당 문서의 명령을 동등한 실행 가능한 파일 경로 표기로 정리한 뒤 문서 검사와 전체 suite에서 이 실패가 사라졌다. repo-wide 테스트 자체는 수정하지 않았다.
- 제거된 debt: sample·run manifest의 trading façade read/write 3개와 잘못 소유된 직접 persistence 테스트. `PENDING_DEPENDENCIES`는 68쌍으로 유지하며 새 허용 항목은 없다.
- 남은 debt: `rl_feature_snapshot_rows`, `rl_training_label_rows`, `training_sample_period_inputs`가 trading façade에 있고 `build_labels`, `build_training_samples`, `export_dataset`, `research/rl/features.py`, `research/ml_serving.py` 등이 사용한다.
- 다음 독립 작업: read migration을 일괄 rename하지 않는다. 먼저 `build_training_samples.py`의 lightweight scalar metadata와 pending 기간의 full payload read를 기준으로 PIT/version/ticker/cutoff 필터와 JSON 복원 회피를 테스트로 고정하고, Research owner read API가 실제로 더 깊은 경계인지 판단한다. 이후 나머지 caller를 각각 조사한다.

#### Training metadata read Task 1 — scalar projection owner 이관

- 변경 전 호출 관계: `build_training_samples`의 lightweight branch가 `SupabaseRepository.training_sample_period_inputs()`를 호출했고, façade가 ResearchStore의 `records_with_payload_fields()` 두 번을 실행해 version·ticker·label cutoff를 필터했다. 해당 façade 메서드의 production caller는 이 command 한 곳뿐이었다.
- 변경 이유: Research 산출물의 scalar projection과 cutoff 판정은 Research owner의 read 계약이며, Trading 구현을 경유할 이유가 없다. 완료 기간에서 full JSON payload를 읽지 않는 성능/재시작 의미를 보존해야 한다.
- 수정 파일: `src/investment_agent/research/storage/repository.py`, `src/investment_agent/research/commands/build_training_samples.py`, `tests/investment_agent/research/commands/test_training_samples.py`, 새 `tests/investment_agent/research/test_training_sample_metadata.py`, 이 원장.
- 이동·삭제 파일: 없음. façade는 다음 Task에서 caller 0건을 확인한 뒤 제거한다.
- import·runtime 방향: command는 이미 manifest read에 쓰던 `ResearchStore` 인스턴스에서 metadata도 읽는다. 기본 경로는 read-only, 주입 경로는 같은 store를 사용하며, sample write만 별도 writable store를 연다. full feature/label row read와 universe read는 기존 reader에 남긴다.
- 테스트 결과: 새 ResearchStore 계약 2개는 메서드 부재로 RED, command lightweight 계약은 기존 trading reader 호출로 RED였다. 구현 후 metadata·training command·record key·architecture 49개 통과. 실제 Parquet scalar projection 결과에 대형 `features`/`forward_return` payload가 없고 filter가 동작함을 확인했다.
- 제거된 debt: lightweight metadata production read의 trading façade 경유 1곳. `PENDING_DEPENDENCIES`는 아직 68쌍이다.
- 남은 debt: façade의 미사용 메서드 하나와 Research feature/label full row read façade, 일반 Research→Trading import.
- 다음 독립 작업: façade 메서드 하나만 삭제하고 owner guard·통합 테스트를 확인한다.

#### Training metadata read Task 2 — façade 제거와 통합 검증

- 변경 전·후 호출 관계: metadata projection은 `build_training_samples → SupabaseRepository → ResearchStore`에서 `build_training_samples → ResearchStore`로 바뀌었다. `SupabaseRepository.training_sample_period_inputs`는 command 이관 뒤 production/test caller 0건이어서 삭제했다.
- 수정 파일 전체: `research/storage/repository.py`, `research/commands/build_training_samples.py`, `trading/supabase_repository.py`, Research command·storage 테스트, `trading/test_repository_ownership.py`, 이 원장. 새 Research metadata 테스트 1개 외 파일 이동·삭제와 schema 변경은 없다.
- import·runtime 방향: scalar metadata read는 Research owner만 정의·호출한다. AST 가드는 owner 밖의 정의와 호출을 모두 검출하며, 기존 trading façade 정의에서 RED 후 삭제로 GREEN이 됐다. `build_training_samples`가 full feature/label rows를 읽는 `SupabaseRepository` import는 그대로 유지돼 `PENDING_DEPENDENCIES`는 68쌍이다.
- 테스트 결과: metadata·training command·record key·backfill·RL repository·ownership·architecture·repo convention·workflow·docs consistency 159개 통과. 전체 suite 3,016개 중 기준선과 같은 `lightgbm`/`xgboost` 미설치 오류 4개, skip 1개이며 새 실패는 없다. 최종 자체 검토에서 같은 ticker의 늦은 label과 window 밖 snapshot fixture를 보강해 cutoff/window 필터가 각각 독립적으로 검증되게 했고 관련 53개를 다시 통과시켰다. `git diff --check` 통과.
- 제거된 debt: 미사용 trading metadata read façade 메서드 하나와 command의 역방향 runtime 경유.
- 남은 debt: `rl_feature_snapshot_rows`, `rl_training_label_rows`는 research의 build_labels·build_training_samples·export_dataset·RL features·ML serving과 일부 테스트에서 사용한다. façade 자체를 제거하려면 각 caller의 version·ticker·availability·label cutoff 필터와 반환 정규화 계약을 먼저 고정해야 한다.
- 다음 독립 작업: full feature/label read의 전체 caller를 조사하고 `ResearchStore`에 실제 공통 read 계약이 필요한지 판단한다. Research command 한 곳만 바꿔 미사용 façade라고 주장하지 않는다.

### Phase 3 — Research 역방향 import 제거

#### Core serialization Task 1 — 공통 owner 직접 import

- 변경 전 호출·import 관계: `research/datasets/contracts.py`, `core.py`, `training.py`, `research/rl/contracts.py`는 `ContractError`, `json_value`, `parse_datetime`를 `trading/contracts.py`에서 import했다. 그 모듈은 세 심볼을 `platform.serialization`에서 그대로 import해 재수출했다.
- 변경 이유: Research 계약의 값·예외·파싱은 Trading 계산에 속하지 않으며 실제 구현 owner인 Platform을 직접 바라볼 수 있다. 새 façade나 alias를 만들지 않고 기존 불필요한 역방향 import 네 개를 제거한다.
- 수정 파일: 위 Research 계약 4개, `tests/investment_agent/test_architecture.py`, 이 원장.
- 이동·삭제 파일: 없음. 금융 계약, DB schema, 계산, 저장, runtime caller는 변경하지 않았다.
- dependency/import 방향: 네 파일의 `research → trading/contracts.py`가 `research → platform.serialization`로 바뀌었고 정확한 pending 네 쌍을 삭제했다. `PENDING_DEPENDENCIES` 68→64.
- 테스트 결과: pending 네 쌍 제거 직후 architecture test에서 정확히 네 위반으로 RED, import 변경 뒤 계약·dataset·RL·training sample·architecture 65개 통과. `ContractError`, `parse_datetime`, `json_value`가 Trading re-export와 동일 객체임을 확인했다.
- 남은 debt: `research.features.layer`의 `EvidenceBundle`, `research.evaluation.evaluator`의 `EvaluationResult`는 실제 Trading 금융 계약이므로 기계적으로 옮기지 않는다. 그 외 순수 serialization import와 수많은 trading algorithm/read 호출은 각각 검증이 필요하다.
- 다음 독립 작업: 통합 검증과 남은 Research→Trading import의 성격 재분류.

#### Core serialization Task 2 — 통합 검증과 남은 import 분류

- 변경 전·후 호출 관계: 네 Research 계약은 공통 에러·파서·JSON 값을 Trading 재수출 대신 Platform 구현에서 직접 읽는다. 다른 Research module이나 runtime caller의 API는 변하지 않았다.
- 수정 파일 전체: `research/datasets/contracts.py`, `core.py`, `training.py`, `research/rl/contracts.py`, architecture test, 이 원장과 계획 문서. 파일 이동·삭제와 schema·계산·실행 안전성 변경은 없다.
- dependency 방향: `PENDING_DEPENDENCIES` 68→64이며 새 pending은 없다. architecture rule은 네 정확한 쌍을 제거하기 전 네 위반으로 실패한 뒤 변경 후 통과했다.
- 테스트 결과: architecture·repo convention·workflow·docs consistency·Research 계약/dataset/RL/backtest 관련 153개 통과. 전체 suite 3,016개에서 이전과 같은 선택적 `lightgbm`·`xgboost` 미설치 오류 4개와 skip 1개 외 새 실패가 없다.
- 제거된 debt: 네 핵심 Research 계약의 불필요한 Trading 재수출 import.
- 남은 debt: 다른 Research 파일의 공통 serialization 심볼 import는 다음 묶음으로 이전 가능하나, `features/layer.py`의 `EvidenceBundle`과 `evaluation/evaluator.py`의 `EvaluationResult`는 실제 Trading 금융 계약이므로 소유권 설계 없이 변경하지 않는다. feature/label full read façade와 Trading 알고리즘 검증 caller도 남는다.
- 다음 독립 작업: 동일한 순수 serialization import를 사용하는 valuation·training·backtest/ML/command 단위를 caller·테스트별로 나누어 제거한다. 금융 계약까지 기계적으로 옮기지 않는다.

#### Shared serialization Task 1 — valuation 세 곳

- 변경 전 호출·import 관계: `research/valuation/engine.py`, `inputs.py`, `research/commands/build_valuations.py`는 공통 `ContractError`/`parse_datetime`를 Trading 계약의 재수출에서 읽었다. command의 `SupabaseRepository` read는 별도 import다.
- 변경 이유: PIT valuation 입력·계산·command의 시각 파싱과 계약 오류는 Platform 구현이며 Trading 금융 계약을 요구하지 않는다.
- 수정 파일: 위 Research 3개, architecture test, 이 원장. 이동·삭제 파일과 schema·계산 변경 없음.
- dependency 방향: 순수 심볼만 `research → platform.serialization`로 바꾸고 정확한 pending 3쌍을 제거했다(64→61). command의 Supabase read 역방향은 그대로 남겼다.
- 테스트 결과: pending 제거 직후 architecture test가 정확히 세 위반으로 RED, import 변경 뒤 valuation·historical replay·backfill·architecture·docs consistency 71개 통과, `git diff --check` 통과.
- 남은 debt: command·RL/training/backtest·ML의 순수 공통 import와 valuation command의 Trading read façade, 실제 금융 계약 import.
- 다음 독립 작업: Research command 일곱 곳을 같은 방식으로 개별 심볼 확인 후 이관한다.

## 향후 milestone

| 묶음 | 해당 phase | 독립 완료 조건 |
|---|---|---|
| 저장·연구 경계 | 2~3 | 연구의 일반 trading import 제거, owner별 저장 경계, 단계별 façade 축소 |
| 판단·실행 경계 | 4~5 | RiskGate가 intent 미생성, broker 계약이 live runtime에서 사용, 안전 테스트 유지 |
| 조회·발송 경계 | 6·8 | dashboard read가 reporting 소유, engine이 Discord 구현을 직접 모름 |
| 저장 관례·운영·정리 | 7·9~10 | 실제 중복만 정리, 불필요한 façade 삭제, architecture 가드 강화 |

각 묶음은 해당 시점의 코드와 caller inventory를 다시 검증해 세부 계획을 작성한다. 목표 구조 문서의 후보 파일명을 완료 사실로 취급하지 않는다.
