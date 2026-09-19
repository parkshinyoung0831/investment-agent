# 의존성 방향 리팩터링 — 진행 원장

> 사용자가 요청한 새 세션 인계 문서다. 이것은 현재 아키텍처 SSOT가 아니다. 새 세션은 `AGENTS.md` → `CLAUDE.md` → `docs/superpowers/specs/2026-09-19-dependency-direction-design.md` → `docs/superpowers/architecture-target.md` → 이 파일 → 현재 계획 순서로 읽는다. 기록보다 Git·코드·테스트의 실제 상태가 우선한다.

## 식별과 현재 상태

- 기준 원격 `main`: `4181f6b53d84105f2b78d78c69e9119c1f55a6cf` (2026-09-20 세션 시작 시 로컬 HEAD와 일치 확인).
- 통합 작업 브랜치: `main`. 모든 phase는 이 브랜치의 연속 커밋과 이 진행 원장 하나로 추적한다. 임시 검증 브랜치를 만들더라도 완료 내용을 `main`에 통합한 뒤 이 원장을 갱신한다.
- 통합 기반 HEAD: `d30e2e5e7ce320641349ceb2d3d5a5c6ddbff6dc`에서 문서 브랜치를 `main`에 fast-forward했고 임시 브랜치를 삭제했다. 이후 커밋은 이 지점부터 이어진다.
- 현재 단계: Phase 2의 feature·label·valuation write 이관 완료, event·event feature write 이관 착수.
- 현재 계획: `docs/superpowers/plans/2026-09-20-research-event-storage-boundary.md` (Task 1~3 미착수).
- 완료 단계: Phase 1 조사와 Phase 2의 feature snapshot·training label write 직접 이관 및 두 façade 메서드 제거.
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
- 테스트 결과: architecture·repo convention·workflow 100개 통과. 전체 suite는 3,009개 중 기준선과 동일한 `tests.investment_agent.research.test_ml_inference` 선택적 ML 의존성 오류 4개, skip 1개이며 새 실패는 없다. ownership guard는 합성 source와 실제 임시 trading 호출 주입 모두에서 위반을 검출했다.
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

## 향후 milestone

| 묶음 | 해당 phase | 독립 완료 조건 |
|---|---|---|
| 저장·연구 경계 | 2~3 | 연구의 일반 trading import 제거, owner별 저장 경계, 단계별 façade 축소 |
| 판단·실행 경계 | 4~5 | RiskGate가 intent 미생성, broker 계약이 live runtime에서 사용, 안전 테스트 유지 |
| 조회·발송 경계 | 6·8 | dashboard read가 reporting 소유, engine이 Discord 구현을 직접 모름 |
| 저장 관례·운영·정리 | 7·9~10 | 실제 중복만 정리, 불필요한 façade 삭제, architecture 가드 강화 |

각 묶음은 해당 시점의 코드와 caller inventory를 다시 검증해 세부 계획을 작성한다. 목표 구조 문서의 후보 파일명을 완료 사실로 취급하지 않는다.
