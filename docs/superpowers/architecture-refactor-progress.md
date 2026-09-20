# 의존성 방향 리팩터링 — 진행 원장

> 사용자가 요청한 새 세션 인계 문서다. 이것은 현재 아키텍처 SSOT가 아니다. 새 세션은 `AGENTS.md` → `CLAUDE.md` → `docs/superpowers/specs/2026-09-19-dependency-direction-design.md` → `docs/superpowers/architecture-target.md` → 이 파일 → 현재 계획 순서로 읽는다. 기록보다 Git·코드·테스트의 실제 상태가 우선한다.

## 식별과 현재 상태

- 기준 원격 `main`: `b0d0786ae64aa21579bdacb7e19e0d6d05b8368b` (2026-09-20 재개 세션 시작 시 로컬 HEAD·`origin/main`과 일치, 작업 트리 깨끗). 이전 원장이 적은 `4181f6b`는 이 HEAD의 조상이다. 재개 세션 프롬프트는 Task 1~4가 미착수라고 서술했으나 실제로는 모두 완료돼 있었고, 실제 상태를 따랐다.
- 통합 작업 브랜치: `main`. 모든 phase는 이 브랜치의 연속 커밋과 이 진행 원장 하나로 추적한다. 임시 검증 브랜치를 만들더라도 완료 내용을 `main`에 통합한 뒤 이 원장을 갱신한다.
- 통합 기반 HEAD: `d30e2e5e7ce320641349ceb2d3d5a5c6ddbff6dc`에서 문서 브랜치를 `main`에 fast-forward했고 임시 브랜치를 삭제했다. 이후 커밋은 이 지점부터 이어진다.
- 현재 단계: 계층 의존성 pending 0쌍(배치 E)과 승인된 조립 예외를 남겨두고, 실제 runtime caller를 확인하며 조회·발송 및 실행 경계를 배치별로 정리한다.
- 현재 작업 방식: 같은 책임 경계의 독립 변경 2~3개를 한 배치로 묶고, 관련·architecture/import 테스트를 배치 안에서 실행한다. 전체 suite는 배치 종료, 실행·승인·risk 안전 변경, 최종 통합 때 실행한다. 완료 task마다 별도 plan 문서를 만들지 않는다.
- 완료 단계: Phase 1 조사, Phase 2의 feature snapshot·training label·valuation·event·training sample·decision experience owner 이관, Phase 3 공통 serialization·forecast·평가 계약 및 일부 Data read 역방향 import 정리, production Trading 알고리즘 검증의 명시적 경계 설정, Phase 4 RiskGate→ExecutionIntent 생성 책임 이관. Research 사건 feature·계약 배치까지 `PENDING_DEPENDENCIES`는 16쌍이다.
- 단일 브랜치 통합 점검(2026-09-20): 로컬·GitHub의 실제 브랜치는 `main` 하나였다. 남아 있던 `phase-source/main` 추적 참조(`e9f6fc5`)의 10개 커밋은 `git range-diff 5801357..phase-source/main baf40e2..d2a0315`에서 `main`의 대응 커밋 10개와 일대일로 확인했다(8개 동일, 2개는 선행 Research factor 소유 경로에 맞춰 적용). 이전 코드를 재병합하지 않고 오래된 참조만 정리한다.
- 단일 브랜치 통합 검증: `docs/GRAPHIFY_MCP.md` 제목 계약을 바로잡고, Git에서 생성 Graphify HTML 2개만 추적 해제해 `.gitignore`에 명시했다(로컬 파일은 보존). 관련 계약 2개 통과. 전체 오프라인 suite는 3,058개 중 실패 1개·skip 1개: 별도 미커밋 `docs/SYSTEM_ARCHITECTURE.md:22`가 선언되지 않은 시스템 로그 채널을 언급한다. 해당 다른 작업 파일은 이 통합에서 수정·커밋하지 않는다. Architecture pending은 16쌍으로 변화 없다.
- maintenance 상태: `harness_switch --status`로 STOPPED·hold ON(reason=원본 사본 architecture refactor Phase 1-10 이식)·kill switch ON·Toss live FALSE를 확인했다. 이미 걸린 hold는 변경하지 않으며 임의로 해제/재기동하지 않는다.

## 검증 기준선

| 검사 | 결과 | 의미 |
|---|---|---|
| `git ls-remote origin refs/heads/main` | 로컬 HEAD와 동일 SHA | 최신 `main` 기준 확인 |
| `python -m unittest tests.investment_agent.test_architecture tests.test_repo_conventions tests.test_workflow_wiring -q` | 100개 통과 | 구조·관례·workflow 현재 기준선 |
| `python -m unittest discover -s tests -t .` | 3,071개 통과, skip 1개 (재개 세션 배치 A 종료 시점) | 이 환경에서는 `lightgbm`·`xgboost` 오류도 재현되지 않았다. 최초 기준선은 3,009개 중 오류 4개(ML 미설치)였다 |
| `tests/investment_agent/test_architecture.py` | `PENDING_DEPENDENCIES` 0쌍(최초 69쌍) + `COMPOSITION_ROOTS` 8개 파일 | 줄여야 하는 현재 import 부채와, 사용자가 승인한 좁은 조립 예외 |

## 새 세션 재개 절차

1. `git status --short --branch`, `git branch --show-current`, `git log -1 --oneline`, `git ls-remote origin refs/heads/main`으로 `main` 여부·미커밋 변경·원격 변화를 확인한다. 원격 `main`이 달라졌으면 무조건 자동 rebase하지 말고 차이를 검토한다.
2. 위 문서와 현재 계획을 읽고 마지막 완료 task/phase의 실제 커밋·테스트 출력을 확인한다. 이 파일의 기록만 믿고 이미 완료된 작업을 반복하지 않는다.
3. 각 phase를 시작하기 전에 호출자·대상·삭제 조건을 다시 확인한다. 하네스/실행 코드에는 maintenance 선행.
4. 각 배치에서 caller 확인 → 필요할 때만 RED 계약 테스트 → 최소 변경 → 관련·architecture/import 테스트 → 배치 종료 전체 suite를 실행한다. 예상 밖 실패가 나오면 다음 변경을 멈추고 원인을 확인한다.
5. 핵심 근거·변경 파일·테스트 결과·남은 부채를 이 파일에 간결히 기록한다. 별도 완료 plan은 만들지 않는다.
6. `PENDING_DEPENDENCIES`의 정확한 남은 항목을 확인한다. 새 항목을 기준선에 추가하지 않는다.

## 단일 실행 워크플로

각 배치는 `현재 caller 재검증 → 필요한 계약 RED → 최소 변경 → 관련·architecture/import 검증 → 배치 종료 전체 suite → 원장 갱신 → 커밋`으로 진행한다. 한 배치 안에서는 같은 책임 경계의 독립 변경 2~3개를 처리하며, 예상 밖 실패·runtime 관계가 드러나면 조사 전 다른 변경을 시작하지 않는다.

진행 상태는 이 문서와 현재 plan의 남은 작업만 사용한다. 별도 완료 plan·날짜별 상태 보고서를 늘리지 않는다.

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

#### Shared serialization Task 2 — Research command 일곱 곳

- 변경 전 호출·import 관계: `adopt_ml_model`, `build_events`, `build_features`, `build_labels`, `build_training_samples`, `export_dataset`, `ml_challengers` command가 공통 `ContractError`/`parse_datetime`를 Trading 계약 재수출에서 읽었다. 각 command의 별도 Trading read/algorithm import는 이번 변경과 무관하다.
- 변경 이유: 공통 시각 파싱과 오류 타입의 실제 구현은 Platform이다. command가 Trading 구현에 의존하는 원인을 하나씩 줄이되 실제 금융 계약은 유지한다.
- 수정 파일: 위 Research command 7개, architecture test, 이 원장. 이동·삭제 파일, 저장/schema·계산·CLI 변경 없음.
- dependency 방향: 일곱 순수 import를 `research → platform.serialization`로 직접 연결하고 정확한 pending 7쌍을 삭제했다(61→54). 기존 Supabase read·decision constants·evidence import pending은 그대로다.
- 테스트 결과: pending 제거 직후 architecture test가 정확히 7개 위반으로 RED, 구현 후 command·feature·workflow·architecture·docs consistency 156개 통과, `git diff --check` 통과.
- 남은 debt: RL·training·backtest·ML의 순수 serialization import와 Research의 Trading 금융/read/algorithm 역방향 의존성.
- 다음 독립 작업: RL·training·backtest 일곱 곳을 같은 방식으로 검사한다.

#### Shared serialization Task 3 — RL·training·backtest 일곱 곳

- 변경 전 호출·import 관계: `research/rl/{baseline,features,leakage}.py`, `research/training/{baseline,walk_forward}.py`, `research/backtest/{contracts,engine}.py`는 공통 `ContractError`/`json_value`/`parse_datetime`를 Trading 계약 재수출에서 읽었다. 일부 파일의 Trading portfolio 금융 계약 import는 별도로 남아 있다.
- 변경 이유: 공통 직렬화와 PIT 시각 파싱은 Platform owner이므로 Research 계산이 Trading 구현 모듈을 통과할 이유가 없다.
- 수정 파일: 위 Research 7개, architecture test, 이 원장. 이동·삭제 파일과 알고리즘/schema 변경 없음.
- dependency 방향: 공통 import만 Platform 직접 경로로 바꾸고 정확한 pending 7쌍을 제거했다(54→47). `trading/portfolio/` import는 그대로 유지했다.
- 테스트 결과: pending 제거 직후 architecture test가 정확히 7개 위반으로 RED, 변경 후 RL·training·backtest·architecture·docs consistency 69개 통과, `git diff --check` 통과.
- 남은 debt: ML 3곳의 공통 import, 실제 금융/portfolio 계약과 Trading algorithm/read 호출.
- 다음 독립 작업: ML 세 파일의 정확한 심볼을 확인하고 선택적 ML 패키지 오류 기준선과 구분해 검증한다.

#### Shared serialization Task 4 — ML 세 곳과 통합 검증

- 변경 전 호출·import 관계: `research/ml_inference.py`, `ml_serving.py`, `models/baselines.py`는 공통 `ContractError` 또는 `parse_datetime`를 Trading 재수출에서 읽었다. ML 모델 학습·serving 구현은 Research 내부에 그대로 있다.
- 변경 이유: 공통 검증/시각 파싱의 실제 owner는 Platform이며 Trading 금융 판단 구현을 요구하지 않는다.
- 수정 파일: 위 ML 3개, architecture test, 이 원장. 이동·삭제 파일, ML 알고리즘·artifact·schema 변경 없음.
- dependency 방향: 세 순수 import가 Platform 직접 경로로 바뀌고 정확한 pending 3쌍을 제거했다(47→44). 전체 후속 계획에서는 valuation 3, command 7, RL·training·backtest 7, ML 3으로 총 20쌍(64→44)을 제거했고 새 pending은 없다.
- 테스트 결과: pending 제거 직후 architecture test에서 정확한 세 위반으로 RED, 이후 ML serving·baseline·architecture·docs consistency 42개와 선택적 booster 없이 실행 가능한 inference 6개가 통과했다. 전체 suite 3,016개에서 기존과 같은 `lightgbm`/`xgboost` 미설치 오류 4개, skip 1개 외 새 실패 없음. `git diff --check` 통과.
- 제거된 debt: 순수 공통 심볼 때문에 Research가 Trading 계약을 import하던 20곳. 현재 Research에서 남은 `trading/contracts.py` 직접 import는 `features/layer.py`의 `EvidenceBundle`(같은 줄의 `parse_datetime`는 나중에 독립 정리 가능)과 `evaluation/evaluator.py`의 `EvaluationResult` 두 곳뿐이다.
- 남은 debt: 실제 Trading 금융 계약·portfolio·risk·system 구현을 Research가 참조하는 경로, Supabase read façade, event evidence cache 및 backtest/system validation 경계. 이들을 단순 Platform 이동이나 re-export로 숨기지 않는다.
- 다음 독립 작업: feature/label full read façade의 모든 caller와 PIT filter를 다시 검증한 뒤 Research owner read 계약 이관 여부를 결정한다. 실제 production Trading algorithm 검증은 필요할 때에만 `research/system_validation` 경계로 별도 분리한다.

#### Full read Task 1 — Research owner 조회 계약

- 변경 전 실제 호출 관계: `build_labels`, `build_training_samples`, `export_dataset`, RL 학습 loader, ML serving이 `SupabaseRepository.rl_feature_snapshot_rows` 또는 `rl_training_label_rows`를 호출했다. façade가 Research DuckDB의 원시 `records()`를 읽고 version·ticker·window·availability·label cutoff를 필터한 뒤 hash/label ID를 재검증했다. ResearchStore에는 동일한 검증 helper와 write 계약만 있었다.
- 변경 이유: feature/label payload의 PIT read와 저장 무결성 판정은 Trading 영구 원장이 아니라 Research DuckDB owner의 책임이다. 기존 caller를 한꺼번에 변경하면 학습·serving 동작이 흔들릴 수 있어 owner API를 먼저 고정했다.
- 수정 파일: `src/investment_agent/research/storage/repository.py`, `src/investment_agent/trading/supabase_repository.py`, `tests/investment_agent/research/test_rl_full_reads.py`, `tests/investment_agent/research/rl/test_repository.py`, 현재 계획과 이 원장. 이동·삭제 파일과 DB schema 변경 없음.
- import·runtime 방향: façade는 read-only ResearchStore를 열어 두 조회를 직접 위임한다. 필터와 변조 거부는 ResearchStore가 소유하며 Trading façade의 중복 변환 함수를 제거했다. production caller는 아직 façade 경유이므로 research→trading pending은 이 Task에서 줄이지 않았다.
- 테스트 결과: 새 owner 계약 4개가 메서드 부재로 RED, 구현 후 owner·기존 façade·metadata·architecture 38개 통과. 전체 suite 3,020개는 기존과 동일한 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개 외 새 실패가 없었다. `git diff --check` 통과.
- 제거된 debt: Trading 모듈 안에 있던 Research artifact full read 필터·무결성 검증 구현 중복. `PENDING_DEPENDENCIES`는 44쌍 유지.
- 남은 debt: 다섯 production caller 묶음이 Trading façade를 호출하며 façade의 두 호환 메서드가 남는다. RL membership과 ML serving의 상위 조립 caller는 owner 이관 전에 재확인해야 한다.
- 다음 독립 작업: Task 2에서 `build_labels`의 feature/label read를 먼저 ResearchStore로 직접 연결하고, 명령의 가격·membership 조회와 쓰기 순서를 유지하는 테스트를 갱신한다.

#### Full read Task 2a — build_labels read 이관

- 변경 전 실제 호출 관계: `build_labels`가 membership·가격과 함께 feature snapshot·기존 label까지 `SupabaseRepository`에서 읽고, 새 label만 별도 ResearchStore에 저장했다. 테스트 대역도 Trading reader에 두 Research 조회를 구현했다.
- 변경 이유: 기존 label 존재 여부와 snapshot payload는 Research DuckDB의 canonical read이며, 시장 가격·membership 조회와 변경 이유가 다르다.
- 수정 파일: `src/investment_agent/research/commands/build_labels.py`, `tests/investment_agent/research/features/test_store.py`, 이 원장. 이동·삭제 파일과 schema·계산 변경 없음.
- import·runtime 방향: command는 주입된 ResearchStore 또는 기본 `ResearchStore(read_only=True)`에서 feature/label을 읽는다. 기본 write는 기존처럼 writable store를 별도로 열고, 주입 store는 read/write를 함께 수행한다. `SupabaseRepository`는 membership과 가격 read에만 남는다.
- 테스트 결과: Trading reader fake에서 두 메서드를 제거한 계약이 기존 구현에서 5개 오류로 RED였다. 구현 후 label/feature owner·architecture·workflow 101개 통과.
- 제거된 debt: `build_labels`의 두 Trading façade read caller. `PENDING_DEPENDENCIES`는 해당 파일의 다른 실제 Trading imports 때문에 44쌍 유지.
- 남은 debt: `build_training_samples`, `export_dataset`, RL training loader, ML serving이 두 façade 중 하나 이상을 사용한다. façade는 아직 삭제할 수 없다.
- 다음 독립 작업: `build_training_samples`의 lightweight/full hydration 두 경로가 같은 ResearchStore를 사용하도록 테스트와 runtime을 이관한다.

#### Full read Task 2b — build_training_samples read 이관

- 변경 전 실제 호출 관계: completion 판정용 scalar metadata와 run manifest는 ResearchStore에서 읽었지만, metadata 미지원 fallback과 변경된 기간의 full payload hydration은 `SupabaseRepository.rl_feature_snapshot_rows`·`rl_training_label_rows`로 되돌아갔다.
- 변경 이유: 한 학습 표본 실행 안에서 같은 Research artifact를 서로 다른 owner API로 읽으면 필터·무결성 계약이 갈라지고 Trading façade 제거가 불가능하다.
- 수정 파일: `src/investment_agent/research/commands/build_training_samples.py`, `tests/investment_agent/research/commands/test_training_samples.py`, 이 원장. 이동·삭제 파일, schema, 비용·label 계산 변경 없음.
- import·runtime 방향: metadata 지원 여부와 무관하게 full feature/label payload는 `selected_store`에서 읽는다. universe membership만 Trading/Data reader에 남고, 재시작 signature·변경 기간만 hydrate·sample batch 후 manifest 기록 순서는 유지된다.
- 테스트 결과: test fake의 Trading full read를 제거한 뒤 기존 구현에서 14개 오류로 RED였다. 구현 후 training sample owner·metadata·persistence·architecture 48개, Research command 89개, architecture·workflow·docs 81개 통과.
- 제거된 debt: `build_training_samples`의 네 full-read 호출 지점(초기 fallback 2, 선택 기간 hydration 2)이 Trading façade에서 분리됐다. pending은 파일의 다른 Trading imports 때문에 44쌍 유지.
- 남은 debt: `export_dataset`, RL training loader, ML serving이 façade를 사용한다. `build_training_samples`도 universe reader 타입이 구체 `SupabaseRepository`이므로 일반 Research→Trading 역방향은 별도 작업이다.
- 다음 독립 작업: `export_dataset`이 universe membership reader와 ResearchStore를 별도 주입받도록 이관한다.

#### Full read Task 2c — export_dataset read 이관

- 변경 전 실제 호출 관계: `export_dataset`이 기간 membership과 feature/label full payload를 모두 `SupabaseRepository`에서 읽었다. dataset 결합·purged split 테스트의 한 fake도 universe와 Research artifact를 함께 구현했다.
- 변경 이유: export가 결합하는 두 원장 payload는 ResearchStore의 검증된 canonical read이며, universe membership은 별도 입력이다.
- 수정 파일: `src/investment_agent/research/commands/export_dataset.py`, `tests/investment_agent/research/commands/test_dataset_export.py`, 현재 계획과 이 원장. 이동·삭제 파일, JSON 형식, 계산, schema 변경 없음.
- import·runtime 방향: command는 membership에 기존 reader를 쓰고, feature/label에는 주입 store 또는 기본 `ResearchStore(read_only=True)`를 쓴다. label cutoff, 동일 시점 imputation, excess-return target과 출력 형식은 유지된다.
- 테스트 결과: store 주입 계약 4개가 기존 구현의 인자 오류로 RED였고, 구현 후 dataset export·purged split·owner·architecture·workflow 88개 통과.
- 제거된 debt: 세 Research command의 full feature/label read가 Trading façade에서 모두 분리되어 계획 Task 2가 완료됐다. pending은 구체 universe reader와 다른 Trading imports 때문에 44쌍 유지.
- 남은 debt: `research/rl/features.py`를 사용하는 training runtime과 `research/ml_serving.py`의 serving runtime이 façade를 사용한다.
- 다음 독립 작업: Task 3에서 `load_historical_training_set`의 feature/label repository와 membership repository가 실제 상위 caller에서 어떻게 조립되는지 추적한 뒤 owner를 분리한다.

#### Full read Task 3a — RL training runtime 조립

- 변경 전 실제 호출 관계: `load_training_set`이 한 repository에서 feature·label·historical membership 세 갈래를 읽었고, 유일한 production caller `continuous_retrain._training_set`이 `SupabaseRepository` 하나를 넘겼다. decision experience 기반 학습은 별도 우선 경로였다.
- 변경 이유: full feature/label은 ResearchStore가 소유하지만 historical membership은 PIT universe read다. loader의 protocol만 나누고 실제 조립을 그대로 두면 역방향 runtime dependency가 숨겨지므로 production caller까지 함께 변경했다.
- 수정 파일: `src/investment_agent/research/rl/features.py`, `src/investment_agent/research/commands/continuous_retrain.py`, RL loader·continuous retrain·exit-code 테스트 3개, 이 원장. 이동·삭제 파일과 학습/승격 계산 변경 없음.
- import·runtime 방향: `load_training_set(repository, store=...)`에서 store가 feature/label을, repository가 membership을 읽는다. continuous retrain은 주입 store 또는 기본 `ResearchStore(read_only=True)`를 조립한다. decision experience 경로는 기존처럼 trading artifact rows만 사용하고 ResearchStore를 열지 않는다.
- 테스트 결과: split fake와 store 인자를 먼저 적용해 기존 구현에서 15개 인자 오류로 RED, 구현 후 RL loader·continuous retrain·architecture·workflow 94개 통과. Research 전체 310개는 기존과 동일한 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개 외 새 실패 없음.
- 제거된 debt: RL historical training의 feature/label runtime read가 Trading façade에서 분리됐다. membership façade와 continuous retrain의 lazy Trading repository import는 실제 남은 dependency라 pending 44쌍은 유지했다.
- 남은 debt: ML serving의 feature snapshot read가 마지막 production façade caller다. 테스트 direct caller도 owner 경계로 이동해야 한다.
- 다음 독립 작업: `champion_forecast`의 tracked ticker provider와 Research feature store를 분리하고, Trading system 상위 caller에서 read-only store를 조립해 fail-closed 동작을 유지한다.

#### Full read Task 3b — ML serving runtime 조립

- 변경 전 실제 호출 관계: `champion_forecast`가 같은 repository에서 현재 tracked ticker와 feature snapshot을 읽었다. Trading system은 이 함수를 기본 forecast로 호출하고, Research ablation은 replay repository로 같은 경로를 재현했다.
- 변경 이유: tracked ticker는 universe 입력이지만 feature snapshot은 Research artifact다. serving 함수 내부의 기본 owner까지 바꾸면 Trading system caller API를 흔들지 않고 실제 production read를 분리할 수 있다.
- 수정 파일: `src/investment_agent/research/ml_serving.py`, `src/investment_agent/research/ablation.py`, `tests/investment_agent/research/test_ml_serving.py`, 이 원장. 모델 파일·계산·system target·schema 변경 없음.
- import·runtime 방향: `champion_forecast`는 repository에서 ticker 목록만 읽고, 주입 store 또는 기본 `ResearchStore(read_only=True)`에서 feature를 읽는다. adopted model 부재·잘못된 label/horizon 경로는 store를 열기 전에 기존처럼 반환한다. ablation은 replay repository를 명시적 feature store로 주입해 historical replay 의미를 유지한다.
- 테스트 결과: split fake와 store 인자를 먼저 적용해 기존 구현에서 5개 인자 오류로 RED, 구현 후 ML serving·ablation·Trading system portfolio·architecture 64개 통과.
- 제거된 debt: ML serving의 마지막 production Trading façade feature read caller. source 검색상 façade 두 메서드의 남은 caller는 `SupabaseRepository` 자체와 호환 경계를 직접 검증하는 테스트뿐이다.
- 남은 debt: façade와 직접 테스트, Trading 모듈의 Research adapter import가 남는다. Task 4에서 caller 0을 고정한 뒤 삭제한다.
- 다음 독립 작업: Trading façade 두 메서드와 해당 직접 테스트를 제거하고, Research full reads가 Trading 밖에 정의·호출되지 못하도록 architecture ownership guard를 추가한다.

#### Full read Task 4 — 호환 façade 제거와 최종 검증

- 변경 전 실제 호출 관계: 모든 production caller 이관 뒤 `SupabaseRepository.rl_feature_snapshot_rows`와 `rl_training_label_rows`는 ResearchStore로 전달하는 호환 구현만 남았고, Research RL repository 테스트 한 곳이 이를 직접 호출했다.
- 변경 이유: caller 0인 façade를 남기면 새 코드가 다시 God repository에 결합할 수 있고, 동일한 이름의 owner가 둘이라 AI와 개발자가 canonical 위치를 오판한다.
- 수정 파일: `src/investment_agent/trading/supabase_repository.py`, `tests/investment_agent/research/rl/test_repository.py`, `tests/investment_agent/trading/test_repository_ownership.py`, 현재 계획과 이 원장. façade 메서드 2개와 façade 전용 label fixture/test를 삭제했다. 파일 이동과 schema 변경 없음.
- import·runtime 방향: full feature/label read의 정의·호출은 `src/investment_agent/research/**`에만 존재한다. AST guard는 세 Research read 메서드의 owner 밖 정의와 호출을 모두 거부하며, 주입한 Trading 위반이 검출되는 테스트를 포함한다.
- 테스트 결과: guard 확장 직후 기존 façade의 정의·호출 4곳을 정확히 검출해 RED, 제거 후 관련 owner·command·RL·ML serving·Trading system·architecture·workflow·docs 175개 통과. 전체 suite 3,020개에서 기준선과 같은 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개 외 새 실패 없음. caller 검색과 `git diff --check` 통과.
- 제거된 debt: Trading God repository의 feature/label full-read 책임과 호환 façade 2개. write, metadata, full read 모두 이제 ResearchStore가 canonical owner다. `PENDING_DEPENDENCIES`는 실제 import 위반과 무관한 runtime façade 제거이므로 44쌍 유지한다.
- 남은 debt: Research command의 구체 universe/price Trading reader imports, 실제 금융 계약·portfolio/risk imports, membership façade, Trading God repository의 다른 bounded-context 책임이 남는다.
- 다음 독립 작업: 현재 pending 44쌍 중 일반 Research command의 `SupabaseRepository` import를 data/universe·market read owner별로 더 줄일지 caller와 기존 repository API를 조사한다. 실제 금융 알고리즘 검증은 별도 system_validation 경계로 판단한다.

#### Data read Task 1 — build_events current universe

- 변경 전 실제 호출 관계: `build_events.main`이 `SupabaseRepository`를 생성해 `current_tracked_tickers()` 한 메서드만 호출했다. 실제 event 계산 함수는 이미 tickers를 명시적으로 받고, operations on-demand 경로도 tickers를 넘겼다.
- 변경 이유: live CLI의 현재 tracked universe는 `data.universe.persistence.select_tracked_tickers()`가 이미 소유한다. Trading God façade를 경유할 runtime/PIT 이유가 없다.
- 수정 파일: `src/investment_agent/research/commands/build_events.py`, `tests/investment_agent/test_architecture.py`, 새 Data read 계획과 이 원장. 이동·삭제 파일, event 계산·저장·schema 변경 없음.
- import·runtime 방향: CLI가 `research → data.universe`로 직접 읽는다. operations caller의 명시 ticker 흐름은 그대로다. 정확한 pending 한 쌍을 먼저 제거해 RED를 확인한 뒤 source import를 변경했다.
- 테스트 결과: architecture test가 제거한 한 위반을 정확히 검출해 RED, 구현 후 build-events·architecture·workflow·docs 85개 통과.
- 제거된 debt: `research/commands/build_events.py → trading/supabase_repository.py` pending 한 쌍. `PENDING_DEPENDENCIES` 44→43, 새 pending 없음.
- 남은 debt: event command는 `LocalEvidenceCache`와 event 금융 계약 때문에 Trading imports 두 곳이 남는다. 이들은 ticker read와 다른 책임이므로 이번 단위에서 숨기지 않았다.
- 다음 독립 작업: 각 Research command의 Supabase usage를 메서드 단위로 inventory하고, local mirror/PIT historical replay 의미가 없는 단순 Data owner read부터 선택한다.

#### Decision experience Task 1~3 — owner read/write와 consumer 이관

- 변경 전 실제 호출 관계: `build_decision_experiences`가 원본 decision·가격·기존 experience read·experience write를 모두 `SupabaseRepository`에서 수행했다. continuous retrain, Operations 성과 갱신, Reporting 알림도 façade의 `decision_experience_rows()`를 읽었다. façade는 실제로 ResearchStore records/save를 전달했다.
- 변경 이유: decision experience는 원본 판단과 사후 가격으로 재계산하는 Research artifact다. Trading decision ledger와 달리 최초 관측 보존과 label availability cutoff를 ResearchStore가 소유해야 한다.
- 수정 파일: `src/investment_agent/research/storage/repository.py`, `research/commands/build_decision_experiences.py`, `research/commands/continuous_retrain.py`, `operations/commands/update_performance.py`, `reporting/notifications/investment/performance.py`, `trading/supabase_repository.py`, Research owner/command 테스트, Trading ownership/decision 테스트, `tests/test_performance_service.py`, 현재 계획과 이 원장.
- 이동·삭제: Trading façade의 `decision_experience_rows`·`save_decision_experiences` 두 메서드와 façade 직접 테스트를 삭제했다. owner 계약과 producer split 테스트를 Research tests에 추가했다. 파일 이동·schema 변경 없음.
- import·runtime 방향: producer는 원본 decision·가격 reader와 ResearchStore를 분리한다. continuous retrain은 이미 주입된 store에서 경험을 읽고, Operations/Reporting은 `ResearchStore(read_only=True)`를 사용한다. Reporting/Operations는 허용된 read-only consumer이며 Trading에서 같은 메서드를 정의·호출하면 AST guard가 실패한다.
- 테스트 결과: canonical read 테스트는 메서드 부재로 RED, producer split 테스트 2개는 store 인자 부재로 RED, ownership guard는 façade read/write를 정확히 검출해 RED였다. 구현·삭제 후 owner·producer·trainer·performance·architecture·workflow 105개 통과. 전체 suite 3,022개는 문서의 dotted path 오탐 1개를 발견해 slash 경로로 고친 뒤 docs·owner·performance·architecture 46개가 통과했다. 코드 회귀는 없고 기존 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개만 남았다. `git diff --check` 통과.
- 제거된 debt: Decision experience read/write의 Trading God façade 책임과 consumer 결합. pending 43쌍은 build command의 원본 Trading read import가 실제 남아 있어 유지한다.
- 남은 debt: 원본 decision cases는 Trading owner, price path는 Data market owner인데 producer가 아직 하나의 Supabase reader로 받는다. 이 read split은 별도 작업이다.
- 다음 독립 작업: 전체 검증 후 decision experience 계획을 닫고, build command의 decision source와 market price source를 실제 owner API로 분리할지 조사한다.

#### Data read Task 2 — training/export/retrain universe owner 직접 연결

- 변경 전 실제 호출 관계: `build_training_samples`와 `export_dataset`은 feature/label을 이미 ResearchStore에서 읽었지만 universe membership만 `SupabaseRepository`에서 읽었다. `continuous_retrain`도 decision experience가 없을 때 현재 ticker와 historical membership을 위해 lazy Trading façade를 만들었다. façade는 local mirror가 없으면 Data universe owner의 현재 ticker·PIT snapshot 조회에 위임했다.
- 변경 이유: 세 기본 live runtime이 요구하는 입력은 Data owner의 canonical universe read뿐이다. 반면 `backfill_research_history`는 기존 repository를 명시 주입하므로 historical replay local mirror를 그대로 보존할 수 있다. Trading façade를 유지할 구체 책임이 없는 세 import만 제거했다.
- 수정 파일: `src/investment_agent/research/datasets/universe.py`, `research/commands/build_training_samples.py`, `research/commands/export_dataset.py`, `research/commands/continuous_retrain.py`, 새 `tests/investment_agent/research/test_universe_reader.py`, architecture test, Data read 계획과 이 원장.
- 이동·삭제 파일: 없음. schema·계산·저장·CLI·harness·execution은 변경하지 않았다.
- import·runtime 방향: 기본 경로는 `research → data/universe/persistence.py`로 현재 ticker와 PIT membership을 읽는다. concrete `DataUniverseReader`가 기존 정렬·대문자화와 RL membership row 형식을 보존한다. 명시 주입 repository 경로는 그대로라 historical replay mirror 의미가 바뀌지 않는다.
- 테스트 결과: 새 reader가 없어 import error 1건, pending 세 쌍을 먼저 지운 architecture test에서 정확한 위반 3건으로 RED를 확인했다. 구현 후 universe reader·training sample·dataset export·continuous retrain·RL loader·architecture·workflow·docs 130개가 통과했다. 전체 suite 3,026개는 기준선과 같은 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개 외 새 실패가 없었다. caller 검색과 `git diff --check`도 통과했다.
- 제거된 debt: 세 command의 `research → trading/supabase_repository.py` 역방향 import. `PENDING_DEPENDENCIES` 43→40, 새 pending 없음.
- 남은 debt: `build_labels`, `build_features`, `build_valuations`, `build_decision_experiences` 등은 universe 외에도 price/fundamental/decision/local mirror 책임을 같은 façade에서 사용한다. 이름만 바꾸지 않고 각 read 계약과 replay cutoff를 먼저 분리해야 한다.
- 다음 독립 작업: caller/import 0건과 전체 suite를 확인한 뒤 이 단위를 커밋한다. 다음에는 남은 Research command 중 owner API와 local mirror 의미를 안전하게 분리할 수 있는 최소 후보를 다시 조사한다.

#### Data read Task 3 — factor research Market/Universe owner 직접 연결

- 변경 전 실제 호출 관계: factor research CLI가 `SupabaseRepository`를 만들고 `trading_dates`, `closes_on_date`, `sp500_sector_map`만 호출했다. 이 CLI는 historical mirror를 준비하지 않아 façade의 live fallback이 기존 Market/Universe persistence를 호출했다.
- 변경 이유: factor IC 계산의 입력은 가격·거래일·분류 Data이며 Trading 판단이나 원장이 아니다. sector map 투영만 façade 안에 남아 있어 canonical Data owner API로 이동하고 두 runtime이 공유하게 했다.
- 수정 파일: `src/investment_agent/data/universe/persistence.py`, `data/market/persistence.py`, `trading/supabase_repository.py`, `research/commands/factor_research.py`, Data universe·factor CLI·architecture 테스트, Data read 계획과 이 원장.
- 이동·삭제 파일: 없음. factor 계산·artifact 형식·schema·harness·execution은 변경하지 않았다.
- import·runtime 방향: factor CLI는 `research → data/market`과 `research → data/universe`로 직접 읽는다. Trading façade의 sector map 메서드는 replay mirror 분기를 유지하고 live fallback만 새 owner 함수에 위임한다. Market owner의 이미 존재하던 두 public read도 export 목록에 명시했다.
- 테스트 결과: owner 함수 부재 1건과 pending 제거 후 정확한 architecture 위반 1건으로 RED를 확인했다. 구현 후 Data persistence·factor research·Trading system·architecture·workflow·docs 140개가 통과했고, CLI wiring 테스트가 세 owner 호출과 결과 파일 생성을 직접 검증한다. 전체 suite 3,028개는 기준선과 같은 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개 외 새 실패가 없었다. caller 검색과 `git diff --check`도 통과했다.
- 제거된 debt: `research/commands/factor_research.py → trading/supabase_repository.py` 한 쌍. `PENDING_DEPENDENCIES` 40→39, 새 pending 없음.
- 남은 debt: label·feature·valuation producer는 local mirror/PIT cutoff와 여러 owner를 함께 사용하며, decision/evaluation/promotion/ablation은 실제 Trading 원장 또는 알고리즘을 소비한다. 이들을 단순 Data read처럼 치환하지 않는다.
- 다음 독립 작업: 관련/전체 suite와 caller 검색 후 커밋한다. 이후 남은 producer 중 explicit read interfaces를 분리해 historical replay를 보존할 수 있는 후보를 다시 설계한다.

#### Shared forecast horizon Task 1~2 — canonical 계약 이관과 legacy 삭제

- 변경 전 실제 import 관계: Research의 model adoption, historical backfill, decision experience, label, dataset export, ML serving 여섯 파일이 `trading/decision/constants.py`의 `SIGNAL_HORIZON_DAYS`를 역방향 import했다. Trading decision agents·alpha·system target·analysis도 같은 값을 사용했고, legacy 파일의 다른 policy/evaluation 상수는 source/test caller가 없었다.
- 변경 이유: 20거래일은 Research label/model과 Trading 판단·optimizer가 같은 단위로 기대수익을 다루게 하는 금융 도메인 불변값이다. Research 또는 Trading 구현에 소유시키거나 값을 복제하면 dependency 역전 또는 조용한 horizon drift가 생긴다. Platform은 금융 도메인을 몰라야 한다.
- 수정 파일: 새 `src/investment_agent/forecasting.py`, Research caller 6개, Trading caller 8개, ML serving·architecture·새 forecasting 계약 테스트, 새 계획과 이 원장.
- 이동·삭제 파일: caller 0을 확인한 `src/investment_agent/trading/decision/constants.py`를 삭제했다. 호환 re-export나 alias는 남기지 않았다.
- import·runtime 방향: Research와 Trading 모두 최상위 금융 계약을 직접 소비한다. horizon 값 20, label/forecast 검증, agent prompt, system target, decision case key는 변하지 않았다. Research pending 정확한 여섯 쌍을 먼저 제거해 RED를 확인한 뒤 import를 이관했다.
- 테스트 결과: canonical 모듈 부재 1건과 architecture 위반 정확히 6건으로 RED를 확인했다. 이관 후 forecasting·Research label/dataset/experience/ML serving·Trading alpha/decision/system·architecture·workflow·docs·packaging 245개가 통과했다. AST ownership guard는 정의가 canonical 파일 한 곳뿐인지 검사하고 임시 중복 정의도 검출한다. 전체 suite 3,031개는 기준선과 같은 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개 외 새 실패가 없었다. source/test legacy import 0건과 `git diff --check`를 확인했다.
- 제거된 debt: 여섯 Research 파일의 `research → trading/decision/constants.py` 역방향 import와 caller 없는 legacy constants module. `PENDING_DEPENDENCIES` 39→33, 새 pending 없음.
- 남은 debt: Research의 Trading algorithm/contract/ledger import와 producer façade가 남는다. local replay와 실제 production validation 의미를 먼저 분리해야 하며, shared top-level 계약을 임의의 공용 dumping ground로 확장하지 않는다.
- 다음 독립 작업: 이 단위를 커밋한 뒤 Data read 계획 Task 4로 돌아가 남은 producer façade와 actual Trading validation import를 구분한다.

#### Shadow outcome Task 1~3 — Research 평가 계약 소유 위치 이관

- 변경 전 실제 호출 관계: `research.evaluation.shadow_fill`이 `trading.performance.pnl`의 `TradeOutcome`·`make_trade_outcome`을 가져와 비용 반영 shadow 결과를 만들었다. Trading 성과 runtime은 별도 ledger/service/attribution 경로를 사용하며 PnL 계약을 사용하지 않았다. Trading package 재수출과 native test 한 곳만 추가 caller였다.
- 변경 이유: 평가 artifact의 유일한 production 소비자·계산 책임이 Research인데 Trading 내부 구현을 import해 일반 Research→Trading 역방향 의존성이 생겼다. 계산식을 공유시키려고 새 공용 추상화를 만들 근거는 없다.
- 수정 파일: `src/investment_agent/research/evaluation/shadow_fill.py`, `trading/performance/__init__.py`, `tests/investment_agent/test_architecture.py`, `tests/native/test_native_core.py`, 새 shadow outcome 계획과 이 원장.
- 이동·삭제 파일: `trading/performance/pnl.py`의 원본 계약을 `research/evaluation/outcomes.py`로 이동했고, Trading package의 미사용 재수출을 삭제했다. DB schema·실행 코드·계산식·ID·비용 계약은 바뀌지 않았다.
- import·runtime 방향: Research shadow-fill과 native integration test가 Research owner를 직접 import한다. Trading PnL 구현 경유가 없어졌고 compatibility alias는 없다.
- 테스트 결과: owner import가 없는 상태에서 native import error와 정확한 architecture 위반 한 건으로 RED였다. 구현 후 Research training sample·native·architecture·workflow·docs 109개 통과. 전체 offline suite 3,031개는 기존과 같은 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개 외 새 실패가 없다. legacy import 검색 0건과 `git diff --check` 통과.
- 제거된 debt: `research/evaluation/shadow_fill.py → trading/performance/pnl.py` 한 쌍. `PENDING_DEPENDENCIES` 33→32, 새 pending 없음.
- 남은 debt: 32쌍 중 일반 Research→Trading 29쌍, Trading→Execution 3쌍. 숫자에는 아직 phase가 완료되지 않은 broker runtime·dashboard read·notification engine·ResearchStore/operations ownership 같은 구조 작업이 포함되지 않는다.
- 다음 독립 작업: Research의 남은 façade·알고리즘/계약 imports를 실제 caller와 replay/PIT 의미에 따라 분류한다. 안전한 owner 직접 read부터 선택하고 production Trading 알고리즘 검증은 별도 경계로 판정한다.

#### Research evaluation Task 1~3 — 결과·가격 경로 계산 owner 이관

- 변경 전 실제 호출 관계: `research.evaluation.evaluator`만 Trading `contracts.EvaluationResult`를 생성했다. Trading `evidence.tools.total_return`은 Research evaluator와 decision experience producer 두 곳만 호출했다. 기존 evaluator test는 Trading portfolio 테스트 폴더에 있었다.
- 변경 이유: 두 계약의 production 계산·소비자는 Research 평가이며 Trading 의사결정·LLM용 계산의 일부로 둘 필요가 없다. 실제 Trading caller가 없는 정의를 옮겨 일반 Research→Trading 역방향 세 쌍을 제거한다.
- 수정 파일: `src/investment_agent/research/evaluation/outcomes.py`, `research/evaluation/evaluator.py`, `research/commands/build_decision_experiences.py`, `trading/contracts.py`, `trading/evidence/tools.py`, architecture test, 새 평가 ownership 계획과 이 원장.
- 이동·삭제 파일: 새 `research/evaluation/returns.py`를 만들고 Trading tools의 사용되지 않는 `total_return` 정의를 삭제했다. Trading contracts의 `EvaluationResult` 정의를 Research outcomes로 이동했다. `tests/investment_agent/trading/portfolio/test_evaluator.py`를 `tests/investment_agent/research/evaluation/test_evaluator.py`로 이동해 분할·배당 계약을 추가했다. schema·실행·수치 계산은 그대로다.
- import·runtime 방향: evaluator와 decision experience producer가 Research owner를 직접 호출한다. 결과 직렬화·기본 평가 시각, 가격 path의 split ratio·dividend 처리 및 기존 예외 메시지를 유지하고 호환 re-export는 만들지 않았다.
- 테스트 결과: 새 owner import error와 제거한 pending의 정확한 위반 3건으로 RED였다. 구현 후 Research evaluation·decision experience·training sample·Trading evidence·architecture·workflow·docs 132개 통과. 전체 offline suite 3,032개는 이전과 동일한 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개 외 새 실패가 없다. old import·old definition 검색은 0건이다.
- 제거된 debt: Research→Trading 3쌍. `PENDING_DEPENDENCIES` 32→29, 새 pending 없음.
- 남은 debt: 일반 Research→Trading 26쌍과 Trading→Execution 3쌍. `evaluate` command의 decision case/read-write façade는 실제 Trading 원장과 연관돼 별도 read/write 경계 검증이 필요하다. broker/dashboard/notification 등 숫자 밖의 phase도 남았다.
- 다음 독립 작업: remaining Research import 중 단순 계약과 실제 Trading 알고리즘 검증을 구별한다. 특히 `trading.evidence.cache`는 Research event builder가 읽지만 별도 Intelligence Parquet 저장소와 생명주기가 달라 이름만 보고 합치지 않는다.

#### System ablation Task 1~3 — 운영 알고리즘 검증 경계 명시

- 변경 전 실제 호출 관계: 이전 `research/ablation.py`는 운영 Trading의 AlphaPolicy, portfolio 현금 계약, risk benchmark, System Portfolio 계산·엔진·SQLite store·target을 직접 import해 같은 PIT replay에서 variant를 돌렸다. production caller는 `research.commands.system_ablation` 한 곳, 관련 test는 Research ablation과 Trading system 격리 guard였다. 운영 원장 write는 replay adapter에서 차단했다.
- 변경 이유: 이 코드는 일반 Research feature/model 계산이 아니라 production Trading 알고리즘을 실제로 검증하는 system validation이다. 독립 구현으로 교체하면 검증 대상과 운영 코드가 달라진다. 따라서 허용된 명시적 검증 경계로 이동하되 예외를 단일 파일·실제 7개 import로 제한한다.
- 수정 파일: `src/investment_agent/research/commands/system_ablation.py`, Trading decision/risk 설명 2곳, `tests/investment_agent/test_architecture.py`, Trading system 격리 test, 새 plan과 이 원장.
- 이동·삭제 파일: `research/ablation.py`를 `research/system_validation/ablation.py`로, `tests/investment_agent/research/test_ablation.py`를 같은 owner의 `system_validation/test_ablation.py`로 이동했다. package init 2개를 추가했다. 이전 module alias는 없다. CLI module path·artifact 출력·schema·algorithm·risk·execution 코드는 변경하지 않았다.
- import·runtime 방향: CLI는 새 검증 모듈을 직접 호출한다. 일반 Research→Trading 의존성은 금지 그대로이며, 해당 검증 파일만 명시 7개 production Trading import를 허용한다. 임시 `system_validation/probe.py`에서 Trading engine을 import하면 guard가 실패하는 테스트를 추가했다.
- 테스트 결과: test owner import error 1건과 제거한 pending 정확한 7건으로 RED였다. 구현 후 ablation·Trading system·architecture·workflow·docs 96개 통과. 전체 offline suite 3,034개는 기준선과 같은 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개 외 새 실패가 없다. legacy source/test caller 검색 0건.
- 제거된 debt: 일반 Research namespace에 있던 production Trading algorithm import 7쌍. `PENDING_DEPENDENCIES` 29→22, 새 pending 없음. 이 7개는 사라진 의존성이 아니라 명시적으로 제한된 system validation 의존성이다.
- 남은 debt: 일반 Research→Trading 19쌍, Trading→Execution 3쌍. 검증 경계 자체도 architecture 예외로 문서화해야 하고, broker/dashboard/notification/operations 등 pending 집합 밖 단계는 여전히 남았다.
- 다음 독립 작업: 19쌍의 Research import를 저장 원장·PIT/replay reader·Trading 계약별로 다시 분류한다. 별개로 Phase 4~8의 실제 runtime caller를 조사해 안전한 다음 구현 단위를 선택한다.

#### Risk/Execution Task 1~3 — intent 생성 책임 이관

- 변경 전 실제 호출 관계: `operations.commands.create_execution_intent`가 승인된 risk row와 proposal을 읽고 snapshot·scope·manual promotion을 재검증했다. 그런 다음 `DeterministicRiskGate.create_execution_intent`가 `ExecutionIntent`를 구성했고 Operations가 `ExecutionRepository.save_intent`로 저장했다. RiskGate factory의 production caller는 이 한 곳이었다.
- 변경 이유: Trading RiskGate의 본래 책임은 결정론적 `RiskDecision`이다. TTL·execution mode·intent ID·ExecutionIntent 구성은 Execution owner가 담당해야 Trading이 Execution 구현을 import하지 않는다.
- 수정 파일: `src/investment_agent/execution/orders/intents.py`, `trading/risk/gate.py`, `operations/commands/create_execution_intent.py`, Execution intent·Trading risk·architecture tests, 새 risk/intent 계획과 이 원장.
- 이동·삭제 파일: `RiskGate.create_execution_intent` 메서드와 그 위치의 직접 safety test를 삭제하고, 같은 거절·TTL·ID 계약을 Execution factory tests로 옮겼다. 파일 이동, DB schema·risk 수치·live flag 변경 없음.
- import·runtime 방향: RiskGate는 `RiskDecision`까지만 만들며 Execution implementation import가 없다. Operations가 기존처럼 승격·snapshot·승인과 `RiskDecision` 유효성을 검사한 뒤 `ExecutionIntent.from_approved_decision(decision.to_dict())`를 호출하고, 그 결과를 기존 순서로 저장한다. 새 factory는 승인 여부를 다시 거절하고 기존 payload로 stable ID를 만든다.
- 테스트 결과: 새 factory 부재와 정확한 pending 위반 1건으로 RED였다. 고정 입력의 이전 `intent_dead29f28555f242e886db0f`, TTL 15분, 승인 거절을 Execution owner test에서 검증했다. 구현 후 Execution 210개, Operations command 19개, architecture/workflow/docs 83개 각각 통과. 전체 offline suite 3,036개는 이전과 같은 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개 외 새 실패가 없다. 이전 RiskGate factory caller 검색 0건.
- 제거된 debt: `trading/risk/gate.py → execution/orders/intents.py` 한 쌍. `PENDING_DEPENDENCIES` 22→21, 새 pending 없음.
- 남은 debt: 일반 Research→Trading 19쌍, `trading/supabase_repository.py → execution/db.py`와 `→ execution/orders/snapshots.py` 2쌍. Execution과 live broker, dashboard, notifications, operations 등 pending 집합 밖 단계도 남는다.
- 다음 독립 작업: Trading Supabase façade가 실제 Execution snapshot/DB를 어느 메서드에서 쓰는지 caller를 좁히고 owner별 분리 가능성을 평가한다. Execution 변경 전 다시 maintenance 상태를 확인한다.

#### Execution persistence 배치 — decision row read + 계좌 snapshot write

- 근거·변경 전 caller: intent 명령은 Trading `SupabaseRepository.risk_decision/portfolio_proposal`을 불렀지만 둘 다 ExecutionRepository Runtime SQLite read에 즉시 전달했다. System 추종 `plan_follow`은 같은 Trading façade의 `save_portfolio_snapshot`을 통해 Execution account/position snapshot을 기록했다. Toss 승인 기본 경로는 이미 ExecutionRepository로 decision row를 읽고 있었다.
- 변경 파일·방향: `operations/commands/create_execution_intent.py`가 주입·기본 ExecutionRepository 하나로 risk/proposal read와 intent write를 수행한다. `trading/my_portfolio.py`는 명시적 `save_snapshot` callback을 받으며 `operations/adapters/trading.py`가 Data security ID 조회와 Execution snapshot 저장을 조립한다. `trading/supabase_repository.py`의 해당 forwarding/read/write 3메서드와 Execution imports를 삭제했다. Trading 계획의 skip 판정, 저장 시점·순서, 계좌 hash·position payload, PIT/read 저장소는 유지했다. 변경 테스트는 Operations intent·snapshot, Trading follow, architecture이다.
- 검증: fake owner 분리에서 RED, snapshot writer 부재·architecture 위반 정확히 2건으로 RED 확인. 관련·architecture·workflow·docs 107개 통과. 전체 offline suite 3,039개는 이전과 같은 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개 외 새 실패가 없다. skip 시 snapshot write 0건, account hash/security ID/비중, runtime callback wiring 검증. maintenance hold ON·kill switch ON·Toss live FALSE 유지.
- 남은 부채: `PENDING_DEPENDENCIES` 21→19, 모두 일반 Research→Trading imports다. Execution DB/snapshot의 Trading façade caller/import는 0건. Broker runtime, dashboard read, notification channel, ResearchStore·Operations 경계와 최종 architecture guard는 아직 완료되지 않았다. 다음 배치는 실제 caller를 확인해 같은 책임 경계의 독립 후보 2~3개를 묶는다.

#### Notification channel 배치 — 공유 전송 계약 + 운영 조립 분리

- 근거: 알림 엔진이 Discord 모듈의 전송 결과·오류·스레드·nonce 상한과 `DiscordChannel` 생성에 결합돼 있었다. 13개 알림 producer와 4개 Operations caller가 `engine.default_context`를 사용했고, 실제 production 채널은 Discord 하나다.
- 변경 파일·방향: `notifications/channels/contracts.py`에 기존 결과·오류·스레드·25자 nonce 계약과 최소 `NotificationChannel` protocol을 두고 engine·Discord adapter·producer·직접 테스트가 이를 소비한다. `notifications/context.py`가 기존 Postgres ledger + Discord channel을 조립하고 모든 기존 caller를 직접 이관했다. `engine`의 Discord import와 legacy `default_context`를 삭제했다. `tests/investment_agent/test_architecture.py`, 알림 계약 테스트, `tests/test_repo_conventions.py`의 공유 조립 경계만 갱신했다. DB schema·알림 내용·발송/재시도·결과 불명 규칙은 불변이다.
- 검증: concrete import architecture guard는 RED 후 GREEN이며 합성 위반도 검출한다. 알림 251개, architecture·workflow·Discord 91개, repository owner 재검증 30개 통과. 첫 전체 suite에서 repository 패키지 규칙이 새 공유 조립 모듈을 producer로 오분류한 실패 1건을 조사·수정했고, 재실행 3,043개는 기준선과 같은 선택적 `lightgbm`/`xgboost` 미설치 오류 4개·skip 1개 외 새 실패가 없다. source/test의 이전 `engine.default_context`·Discord 계약 import caller 0건.
- 남은 부채: `PENDING_DEPENDENCIES` 19쌍 불변. 아직 broker runtime, dashboard reporting read, ResearchStore·Operations ownership과 최종 architecture guard가 남는다. 다음 배치는 현재 caller를 다시 확인해 broker 또는 dashboard read 중 동일 책임 경계 2~3개를 묶는다.

#### Portfolio dashboard read 배치 — 계좌·System·승인 목표

- 근거: `dashboard/app_pages/portfolio.py`만 `dashboard.db`의 최신 계좌 스냅샷, System Portfolio 비교, 승인 목표 read 세 함수를 호출했다. 세 함수 모두 기존 `reporting.readers.runtime.read_runtime_rows`와 Reporting 모델을 사용했고 DB write는 없었다.
- 변경 파일·방향: 세 read를 `reporting/readers/dashboard.py`로 옮기고 Portfolio 화면 및 직접 테스트가 Reporting owner를 호출한다. `dashboard/db.py`의 원본·export를 제거했고 호환 alias는 없다. 계좌 최신시각·안전 필드, System/My 독립성, 오프라인 상태, 승인된 System 목표만 고르는 필터와 cache TTL은 유지했다. Reporting 계약 테스트 3개와 Portfolio 화면의 legacy import architecture guard를 추가했다. `dashboard/db.py`는 earnings·intelligence·ai_approval caller가 남아 유지한다.
- 검증: Portfolio legacy import guard RED 후 GREEN 및 합성 위반 검출. Reporting/기존 DB 계약·architecture 34개, page wiring 7개 통과. 전체 suite는 현재 HEAD `6cc373a`에서 3,052개 중 실패 3개·skip 1개로 끝났다. 세 실패는 함께 반영된 별도 문서/Graphify 작업의 `docs/SYSTEM_ARCHITECTURE.md` 미선언 채널, `docs/GRAPHIFY_MCP.md` 제목 형식, 추적 Graphify HTML 2개와 repo 테스트 기대치 불일치다. Portfolio/Reporting 회귀는 보고되지 않았다. 관련 파일은 다른 작업의 미커밋 변경까지 있어 임의 수정하지 않았다.
- 남은 부채: `PENDING_DEPENDENCIES` 19쌍 불변. Dashboard 직접 DB caller 세 화면, broker runtime, ResearchStore/Operations 경계가 남는다. 현재 HEAD의 통합 테스트 실패 3건도 별도 소유 작업에서 정리해야 한다.

#### Dashboard migrated-read 정리 배치 — Alpha Lab alias + 종목 목록 중복

- 근거: 실제 화면은 Alpha Lab와 종목 목록을 이미 Reporting reader에서 읽었지만 `dashboard/db.py`에 Alpha Lab 재노출과 별도 raw-table 종목 목록 구현이 남아 있었다. `load_ai_data`는 로컬 decision과 canonical security identity를 결합하므로 이번 단순 정리 대상에서 제외했다.
- 변경 파일·방향: `dashboard/app_pages/intelligence.py`가 Alpha Lab를 Reporting에서 직접 import하고, `dashboard/db.py`의 재노출과 미사용 종목 목록 구현·전용 chunk helper를 삭제했다. `tests/investment_agent/test_dashboard_readonly.py`의 종목 계약은 실제 `reporting.securities` view와 전체 공개 컬럼을 검증하도록 옮겼고, architecture test가 두 legacy 이름의 재등장을 막는다. 다른 화면·DB schema·read 계산은 불변이다.
- 검증: legacy reader guard RED→GREEN, 합성 alias 위반 검출. Dashboard·Reporting guard·architecture·page wiring 66개 통과, import/legacy caller 검색 0건. 전체 suite 3,054개 중 이전과 동일한 별도 문서/Graphify 실패 3건·skip 1건 외 새 실패가 없다.
- 남은 부채: `PENDING_DEPENDENCIES` 19쌍 불변. `dashboard/db.py`는 earnings와 canonical identity가 필요한 AI 화면 caller가 남아 유지한다. 서로 의미가 다른 execution/guru/price/strategy 동명 read도 자동 삭제하지 않는다. broker runtime·ResearchStore/Operations 및 외부 문서/Graphify 실패 3건은 별도 후속이다.

#### Research feature 입력 배치 — 테마 taxonomy와 PIT 증거 입력

- 근거·변경 전 caller: `research.features.event_intelligence`가 Trading의 `tag_themes`를 호출했지만 분류 결과는 Research event metadata로 저장됐다. Trading의 재분석은 별도 ETF proxy 선택·시장확인·민감도 계산을 수행한다. `FeatureLayer.build`는 Trading `EvidenceBundle`을 타입으로만 import하고 실제로는 정해진 증거 필드만 읽었다.
- 변경 파일·방향: `research/features/themes.py`가 기존 키워드·순서·테마 이름의 원본을 소유하고, `trading/decision/event_impact.py`는 기존 ETF 매핑만 소유한다. `trading/supabase_repository.py`도 해당 매핑을 읽는다. `research/features/layer.py`는 읽는 필드만 기술한 입력 Protocol과 Platform 시간 파서를 사용한다. 관련 Research/Trading 테스트는 분류-ETF 대응 및 Trading 클래스가 아닌 구조적 입력의 동일 snapshot ID를 검증한다. Trading의 미사용 `tag_themes`/`GlobalTheme`/`THEME_BY_NAME` API는 caller 0건 확인 후 제거했다. DB schema·PIT cutoff·event ID·feature hash·재분석 판단은 변경하지 않았다.
- 검증: pending 두 항목 제거 시 정확한 architecture 위반 2건과 새 owner 모듈 import 오류로 RED 확인. 관련 Research·Operations·Trading·native·architecture 81개 통과. 전체 오프라인 suite 3,056개는 이전과 동일한 별도 문서/Graphify 실패 3건·skip 1건 외 새 실패가 없다. 두 이전 production import 및 사용처 검색 0건.
- 남은 부채: `PENDING_DEPENDENCIES` 19→17쌍. `event_intelligence`의 Event 계약은 아직 Trading 소유라 별도 검증이 필요하다. Broker runtime, Dashboard의 earnings/AI read, ResearchStore·Operations 소유권 및 별도 문서/Graphify 실패 3건이 남는다. 다음 배치는 Event 계약과 나머지 Research import를 실제 caller·검증 helper 사용 범위부터 다시 조사한다.

#### Research 사건 계약 배치 — Event와 EventFeatureSnapshot 소유권

- 근거·변경 전 caller: `Event`와 `EventFeatureSnapshot`의 production 생성·소비는 `research.features.event_intelligence`뿐이었다. Trading decision은 두 클래스를 사용하지 않았고, native test의 Trading `Event` import도 미사용이었다. Research가 Trading 계약을 역방향 import한 실제 한 쌍이었다.
- 변경 파일·방향: 두 dataclass와 기존 검증·PIT·직렬화·hash 식을 `research/features/event_contracts.py`로 이동하고 `event_intelligence.py`가 직접 import한다. Trading contracts의 원본·export 및 미사용 `_EVENT_TYPES`, native test의 미사용 import를 제거했다. 호환 alias·DB schema·사건 계산·Trading 재분석 계산 변경 없음. 새 Research owner test는 기존 고정 input hash, source 정렬과 시각 거절을 검증한다.
- 검증: 새 owner import 오류와 pending 한 건의 정확한 위반으로 RED 확인. Research event·Trading 재분석·native·architecture 50개 통과. repo/packaging/architecture 62개 중 기존 Graphify 추적 파일 불일치 1건 외 새 실패 없음. 전체 suite 3,058개는 이전과 동일한 별도 문서/Graphify 실패 3건·skip 1건 외 새 실패가 없다. 이전 Trading 사건 계약 caller 검색 0건.
- 남은 부채: `PENDING_DEPENDENCIES` 17→16쌍. Research 명령의 Trading Supabase façade 및 backtest/RL의 Trading portfolio/risk import는 별도 caller·행동 검증 후 이관해야 한다. 별도 문서/Graphify 통합 실패 3건도 남아 있다.

#### 재개 세션 배치 A — 원장 보정 + 비중 벡터 계약 공유 + RL 경계 (2026-09-20)

- 원장 보정: 이전 원장이 적지 않은 `f7efdb5`가 이미 evidence cache를 `trading/evidence`에서 `intelligence/evidence_cache.py`로 옮기고 `intelligence` 계층 금지 규칙을 추가했으며 pending 1쌍(`build_events → trading.evidence.cache`)을 제거했다(16→15). 같은 커밋이 추가한 `docs/SYSTEM_ARCHITECTURE.md`가 문서 형식 검사 2건(제목에 em dash 없음, 선언되지 않은 채널 언급)을 깨뜨리고 있어 제목과 채널 문구만 고쳤다(내용·다이어그램 불변). 이 원장의 같은 채널 문구도 함께 고쳤다.
- 변경 전 호출 관계: research backtest·RL 4개 파일과 trading 8개 모듈이 `trading.portfolio.contracts`에서 `CASH_SYMBOL`·`validated_weights`를 가져왔다. execution과 reporting·notifications는 각자 사본을 이미 갖고 있다. execution의 `validated_weights`는 `IntentError`·티커 정규식 `{0,11}`·안전 주석이 다른 **의도된 별도 계약**이라 통합하지 않았다. `WeightConstraints.from_policies()`는 optimizer·RiskGate 기본 정책 인스턴스에서 min/max로 값을 만들어 기본값으로 쓰고 있었고, 이를 검사하던 테스트는 같은 정책에서 파생한 값을 그 정책과 비교해 실패할 수 없는 동어반복이었다. `BaselinePolicyModel.infer_proposal`의 production caller는 0개(테스트 1곳)였다.
- Ruling 1 — 공유 계약 위치: Trading은 Research를 import할 수 없고(`FORBIDDEN["trading"]`, 어댑터 예외 제외) Platform은 금융 도메인을 몰라야 하므로, 비중 벡터 primitive는 선례인 `forecasting.py`와 같이 최상위 공유 모듈 `src/investment_agent/portfolio_weights.py`에 둔다(`CASH_SYMBOL`, `TICKER_RE`, `validated_weights`). trading 8개 모듈과 research 5개 파일이 직접 import하며 `trading.portfolio.contracts`에는 재수출이 없다. execution·reporting·notifications 사본은 건드리지 않았다.
- Ruling 2 — `from_policies()` 제거: Research가 실제 정책을 import하는 대신 기존 리터럴 기본값(0.10/0.05/25/0.005, 현재 정책 값과 일치 확인)을 그대로 쓰고, 정책과의 일치는 테스트가 지킨다. 테스트는 `WeightConstraints()`를 실제 정책과 비교하도록 바꿔 처음으로 실패할 수 있게 됐다(RiskGate `max_symbol_weight`를 임시로 0.05로 바꾸면 실패함을 확인 후 원복). 런타임 자동 추종은 사라졌으므로, 정책을 바꾸는 사람은 이 테스트에서 멈춘다. RL 호출자 5곳은 전부 기본값을 쓰고 operations 주입 경로가 없어 인자 관통은 하지 않았다.
- Ruling 3 — `infer_proposal` 이관: caller 0이지만 테스트가 `execution_eligible=False`·부분 coverage 불변식을 검증하므로 삭제하지 않고 `trading/portfolio/rl_challenger.py`의 `rl_challenger_proposal(...)`로 옮겼다. Trading 함수는 Research 타입을 받지 않고 값만 받는다. 기존 Research 테스트는 실제 baseline 비중을 이 함수에 통과시키는 연결 검증을 유지한다. **사용자 판단 대기: 이 경로는 production에서 쓰이지 않는 죽은 코드일 수 있어, 필요 없으면 함수·테스트를 함께 삭제하면 된다.**
- 수정 파일: 새 `portfolio_weights.py`, 새 `trading/portfolio/rl_challenger.py`, 새 테스트 2개(`tests/investment_agent/test_portfolio_weights_contract.py`, `tests/investment_agent/trading/portfolio/test_rl_challenger.py`), trading 8개(`portfolio/contracts.py`, `market_risk.py`, `optimizer.py`, `risk/gate.py`, `risk/stress.py`, `system/accounting.py`, `system/engine.py`, `system/target.py`)와 `my_portfolio.py`, research 5개(`backtest/contracts.py`, `backtest/simulator.py`, `rl/baseline.py`, `rl/environment.py`, `system_validation/ablation.py`), `tests/investment_agent/test_architecture.py`, `test_contracts_hypothesis.py`, `research/rl/test_baseline.py`, `research/rl/test_weight_constraints.py`, 문서 2개.
- 삭제·이동: 파일 삭제 없음. `trading/portfolio/contracts.py`의 `CASH_SYMBOL`·`validated_weights` 정의를 `portfolio_weights.py`로 옮겼고(본문 동일), `BaselinePolicyModel.infer_proposal`과 `WeightConstraints.from_policies`를 삭제했다.
- import 방향 변화: research→trading 6쌍 제거(`backtest/contracts`, `backtest/simulator`, `rl/baseline`, `rl/environment`의 contracts·optimizer·risk.gate). 시스템 검증 예외 목록에서 `trading.portfolio.contracts`도 제거(7→6 import). 새 pending 없음. `PENDING_DEPENDENCIES` 15→11(같은 커밋 이전 16→15 포함 시 누적 16→11).
- 테스트 결과: 계약 테스트는 모듈 부재로 RED, 소유권 guard는 `trading/portfolio/contracts.py`의 두 정의를 검출해 RED, 제거한 pending 세 쌍은 정확한 위반 세 건으로 RED, `rl_challenger` 테스트는 모듈 부재로 RED였다. 위반 주입: research에 `validated_weights` 재정의 파일 → 소유권 guard 실패, research가 `trading.portfolio.contracts` import → architecture 실패(둘 다 원복). 최종 전체 offline suite 3,071개 OK, skip 1개.
- 남은 dependency debt(11쌍, 모두 Research→Trading): `commands/{backfill_research_history,build_decision_experiences,build_features(×2: evidence.context·supabase_repository),build_labels,build_valuations,evaluate,system_ablation}`과 `promotion/cli`가 `trading/supabase_repository.py`(또는 `trading/evidence/context.py`)를 가져온다. 대부분 CLI `main()`이 구체 `SupabaseRepository()`를 만드는 자리이므로 이것은 operations 조립 책임일 가능성이 크다. 다만 이 CLI 모듈 경로는 하네스·workflow가 호출하므로 경로 호환을 함께 검증하는 설계가 필요하다. 그 밖에 broker runtime(Phase 5), `dashboard/db.py` 잔여 화면 3개(Phase 6), ResearchStore 분리 판단(Phase 7), 최종 architecture guard 강화(Phase 10)가 남았다.
- 다음 재개 지점: 위 11쌍을 메서드 단위로 분류한다. `build_labels`/`build_valuations`/`build_features`는 가격·재무·membership·local mirror(PIT replay)를 함께 읽으므로 read 계약을 먼저 고정하고, `evaluate`·`promotion/cli`·`system_ablation`·`backfill_research_history`·`build_decision_experiences`의 CLI 조립부는 operations로 옮길 수 있는지 workflow·하네스 호출 경로와 함께 재검증한다.
- 관련 커밋: `088ed3a`(코드·테스트·문서). 로컬 `main`이 원격보다 앞서 있고 아직 push하지 않았다(원격 `b0d0786`).
- 사용자 결정 대기(다음 배치 진입 전): 남은 pending 11쌍 중 `evaluate`·`promotion/cli`·`system_ablation`·`backfill_research_history`·`build_decision_experiences`·`build_features`·`build_labels`·`build_valuations`는 CLI `main()`이 구체 `SupabaseRepository()`를 조립하는 자리다. 이 모듈 경로는 `operations/harness_adapters.py`·`operations/adapters/research.py`(하네스 코드, maintenance 선행 필요)와 `docs/OPERATIONS.md`·research/trading README 여러 곳이 명령으로 호출한다. (A) 조립부를 operations 명령으로 옮기고 경로를 함께 바꾸거나, (B) system_validation처럼 조립 진입점만 좁은 예외로 선언하는 두 방향 중 무엇으로 갈지 정해야 한다.

#### 재개 세션 배치 B — CLI 조립 진입점 예외 선언 (2026-09-20, 사용자 승인: 방향 B)

- 변경 전 호출 관계: 남은 pending 11쌍 중 10쌍이 `trading/supabase_repository.py`의 구체 `SupabaseRepository`를 가져오는 자리였다. 8개 Research 모듈(`commands/{backfill_research_history,build_decision_experiences,build_features,build_labels,build_valuations,evaluate,system_ablation}`, `promotion/cli`)은 모두 `main()`을 가진 CLI 진입점이며 `repository or SupabaseRepository()`나 `main()`에서 구체 저장소를 만든다. 순수 계산은 이미 repository를 주입받는다. 이 모듈 경로를 `operations/harness_adapters.py`·`operations/adapters/research.py`가 하네스 명령으로, `docs/OPERATIONS.md`와 research·trading README 여러 곳이 사람이 실행하는 명령으로 호출한다.
- 사용자 결정: 조립을 operations로 옮기면 하네스 코드와 명령 경로·문서가 함께 바뀌고 maintenance가 필요하다. 사용자가 이를 옮기지 않고, `system_validation`처럼 조립 진입점만 좁은 예외로 선언하기로 승인했다(방향 B). 이 예외는 완전한 해소가 아니라 **의도적으로 남긴 조립 경계**이며 최종 보고의 남은 debt에 포함한다.
- 변경: `tests/investment_agent/test_architecture.py`에 `COMPOSITION_ROOTS`(8개 파일 경로)와 `COMPOSITION_REPOSITORY`(구체 저장소 모듈 하나)를 두고 `_is_allowed`가 두 값의 **정확한 일치**만 허용한다. 새 테스트 3개: 각 예외 모듈이 `main()`을 정의하고 실제로 그 저장소를 import하는지(쓰지 않는 예외 방지), 목록에 없는 새 Research 모듈이 같은 import를 하면 실패하는지, 예외 모듈이 다른 Trading 구현(`evidence.context` 등)이나 하위 경로로 넓어지지 않는지. 제품 코드·명령 경로·하네스·문서는 변경하지 않았다.
- import 방향 변화: 없음(선언만 바뀜). `PENDING_DEPENDENCIES` 11→1.
- 테스트 결과: 예외 없이 8쌍을 pending에서 지운 상태에서 architecture 4건 실패(RED), `_is_allowed` 추가 후 33개 통과. 위반 주입: 예외 모듈 `evaluate.py`에 `trading.evidence.tools` import를 추가하면 실패함을 확인하고 원복했다.
- 남은 dependency debt: (1) `research/commands/build_features.py → trading/evidence/context.py`(`ContextBuilder`). Trading 판단(`trading/decision/analysis.py`)과 Research feature build가 함께 쓰는 PIT 증거 조립이며 `EvidenceBundle` 계약과 함께 소유권을 정해야 한다. 기계적으로 옮기지 않았다. (2) `COMPOSITION_ROOTS` 8개는 승인된 예외다. (3) 시스템 검증 예외 6개 import(`research/system_validation/ablation.py`). (4) broker runtime(Phase 5), `dashboard/db.py` 잔여 화면(Phase 6), ResearchStore 분리 판단(Phase 7), 최종 guard 강화(Phase 10).
- Phase 6 사전 조사(코드 수정 없음): `dashboard/db.py`는 1,772줄이며 화면 caller는 `app_pages/ai_approval.py`·`intelligence.py`의 `load_ai_data`와 `app_pages/earnings.py`의 earnings 로더 묶음(`load_earnings_data`·`load_earnings_discord_support`·`load_earnings_extended`, 합쳐 약 500줄)뿐이다. `calculations/strategy.py`는 `load_price_history` 계약을 주석으로만 언급한다. 파일에는 SELECT 전용 안전 경계(`SelectOnlyGateway`, RPC 전부 거부)와 canonical 재무·처리·segment·주식수·가격 행 정규화 helper가 함께 있다. 옮길 때는 (1) gateway 경계와 helper의 동등한 보존 위치를 먼저 정하고, (2) earnings 로더를 화면 단위로 나눠 reporting reader/service 계약 테스트를 먼저 고정하며, (3) `load_ai_data`는 로컬 decision과 canonical security identity 결합이라 단순 이관 대상이 아니다.
- 다음 재개 지점: Phase 5·6 조사. Phase 5는 하네스·execution 코드를 만지므로 시작 전에 `harness_switch --status`를 확인하고 정비 보류가 걸려 있는지 본다(이미 걸린 hold는 임의 해제하지 않는다). `ContextBuilder` 소유권은 별도 설계 결정으로 다룬다.

#### 재개 세션 배치 C — pending 0쌍, broker 계약 판단 (2026-09-20, 사용자 지시: 권장 방향으로 전부 진행)

- `ContextBuilder`(마지막 pending 1쌍): Trading 판단(`trading/decision/analysis.py`)과 Research feature build가 같은 PIT 증거 조립기를 써서 학습·서빙 일관성을 만든다. 조립기 안에는 LLM 프롬프트 공시 행 수 상한(`FILING_ROWS_IN_PROMPT`) 같은 Trading 정책이 있어 Research로 통째로 옮기면 그 정책이 딸려 간다. Ruling: `build_features`는 이미 저장소를 만드는 조립 진입점이므로 `COMPOSITION_ROOTS`를 "파일 → 허용 모듈 집합" 정확 매핑으로 일반화하고 이 파일에만 `trading/evidence/context.py`를 추가했다. 새 파라미터·추상화는 만들지 않았다. 다른 진입점은 이 예외를 물려받지 않으며(`build_labels`에 주입해 실패 확인 후 원복), 예외 모듈이 실제로 그 import를 쓰는지도 검사한다. **`PENDING_DEPENDENCIES`는 0쌍이 됐다.** 다만 이는 해소가 아니라 승인된 조립 예외 8개(+ `ContextBuilder` 1개)와 시스템 검증 예외로 남은 것이다. 증거 조립기·`EvidenceBundle` 계약의 소유권은 아직 Trading에 있다.
- Phase 5(broker 계약): `execution/brokers/contracts.py`의 9개 이름(`BrokerAdapter`, `CanonicalOrderRequest`, `BrokerOrder` 등)은 패키지 `__init__` 재수출 외에 production·test 호출자가 0개였고 구현체도 없었다. 실주문 worker는 `TossOrderApi`·`TossOrderCommand`·`TossManualSnapshot`으로 수량·수수료·매수 가능액·정규장·수동 handoff를 검증하며 이 의미가 전부 Toss 전용이다. `test_toss_only.py`는 이미 KIS 어댑터·`BrokerRouter`가 없음을 강제하고 있다. Ruling: 실주문 worker를 broker 중립 계약으로 바꾸는 것은 broker가 하나인 지금 위험만 늘리므로 하지 않고, 호출자 0인 broker 중립 계약 파일을 삭제했다. 두 번째 broker가 실제로 생기면 그때 worker의 공통 부분을 나눈다(execution README에 명시).
- 수정 파일: `tests/investment_agent/test_architecture.py`(조립 예외 일반화·pending 0), `tests/investment_agent/execution/test_toss_only.py`(broker 중립 계약 부재 테스트), `src/investment_agent/execution/brokers/__init__.py`, `src/investment_agent/execution/README.md`.
- 삭제: `src/investment_agent/execution/brokers/contracts.py`(호출자 0 확인). worker·주문 원장·reconciliation·`TOSS_LIVE_ENABLED`·maintenance hold는 변경하지 않았다. hold(정비 보류·kill switch ON·lockdown)는 그대로다.
- 테스트: 새 broker 중립 계약 부재 테스트는 삭제 전 RED, 삭제 후 통과. execution 전체 211개, architecture·docs 통과.
- 남은 debt: Phase 6(dashboard read 이관), Phase 7(ResearchStore), Phase 9(`SupabaseRepository` God façade 1,344줄 분해: 데이터 읽기 조립·후보 선정·Trading 원장 쓰기·모델 승격·research 읽기가 섞임), Phase 10(가드 강화).

#### 재개 세션 배치 D — Phase 6·7·8·9·10 (2026-09-20, 사용자 지시: 권장 방향으로 전부 진행)

- Phase 6(dashboard read): `dashboard/db.py`를 AST로 검사해 화면 caller가 없는 죽은 사본 6개(`load_macro_data`, `load_execution_data`, `load_guru_data`, `load_strategy_data`, `load_price_history`, `load_reporting_view`)와 전용 helper·상수를 찾았다. 화면은 이미 `reporting/readers/dashboard.py`의 같은 이름 reader를 쓰고 있었는데, 그 reader에는 전용 테스트가 하나도 없었고 계약 테스트는 죽은 사본만 보호했다. 그대로 지우면 실제 화면 로더가 무방비가 되므로 순서를 뒤집었다. 새 `tests/investment_agent/reporting/test_dashboard_reader_contracts.py` 10개가 살아 있는 reader의 계약(실제 SQLite로 execution 관측·raw broker 미노출, 가격 yfinance 모양·잘못된 종목/기간 거절, guru payload 키·reporting view만 요청, strategy 상태, macro 범위)을 먼저 고정했고, 통과를 확인한 뒤 사본과 그 전용 테스트를 삭제했다. `test_dashboard_readonly.py`의 오프라인 경계 테스트는 삭제하지 않고 살아 있는 reader에 다시 걸었으며 중복 가드 `_KNOWN_OVERLAP`는 빈 집합이 됐다. `scripts/verify_integration.py`는 두 모듈의 `load_*`를 모두 순회한다. `dashboard/db.py` 1,772→약 1,380줄, 남은 로더는 `load_ai_data`·earnings 3종·`load_ticker_data_quality`뿐이다.
- Phase 6 판단 — `dashboard/db.py` 유지: 남은 파일은 SELECT 전용 gateway(`SelectOnlyGateway`, RPC 전면 거부)와 화면 3개(`ai_approval`, `intelligence`, `earnings`)가 쓰는 로더다. dashboard→reporting 방향은 이미 맞아 방향 위반이 아니고, 파일을 reporting으로 옮기는 것은 안전 경계 파일의 대규모 이동이며 CLAUDE.md·README·정적 경계 테스트의 경로 문자열이 함께 바뀐다. 이동 이득은 응집도뿐이라 이번에는 하지 않았다. 옮길 때는 gateway·canonical helper의 동등한 위치를 먼저 정하고 earnings 로더를 화면 단위로 나눈다.
- Phase 7(ResearchStore) 판단 — 분리하지 않음: 1,105줄이지만 한 DuckDB 파일·Parquet 뿌리·연결 수명·마이그레이션을 공유하는 단일 저장소이고, 표 구조는 CLAUDE.md가 의도된 모양으로 보호한다. 메서드 수로 나누면 연결·마이그레이션 소유가 갈라지고 generic `records()` 엔진이 중복된다.
- Phase 8 잔여(reporting→notifications): `notifications/earnings_report/capital.py`(DB 없는 순수 값 읽기 32줄)가 reporting 두 파일에서 거꾸로 import되고 있었다. `reporting/services/financial_row.py`로 옮기고 세 importer를 갱신해 알림이 reporting을 소비하는 방향이 됐다(알림 카드 계산·DB schema 불변).
- Phase 9(façade 정리): `SupabaseRepository`의 public 메서드 중 src caller가 0인 것은 `case_exists` 하나(정의 외 참조 0)뿐이라 삭제했고 미사용 `canonical_json` import를 지웠다. 나머지 public 메서드는 전부 caller가 있으며, God façade(약 1,340줄)의 실질 분해는 데이터 읽기 조립·후보 선정·Trading 원장 쓰기·모델 승격이 뒤섞여 있고 Research 조립 진입점 8개가 이 façade에 의존하므로 여러 배치가 필요하다.
- Phase 10(가드 강화): 패키지 간 실제 import 행렬을 AST로 계산해 목표 방향과 대조했다. `LayerDirectionTest.FORBIDDEN`에 `reporting`(notifications·dashboard·execution·operations 금지), `notifications`(trading·execution·dashboard·operations), `dashboard`(trading·execution·operations·data), `research`(+reporting·notifications·dashboard·execution), `trading`(+operations·reporting), `execution`(+reporting·intelligence)을 추가했다. 새 규칙 10개를 위반 주입으로 검증했고 모두 실패했다. `SharedTopLevelModulesTest`가 최상위 공유 모듈을 `{bootstrap, config, forecasting, portfolio_weights}`로 고정하고 공유 계약이 platform만 import하도록 강제하며 임시 `utils.py` 주입으로 실패를 확인했다. CLAUDE.md의 "일부러 다르게 둔 모양" 표에 조립 예외·공유 계약 위치·execution 비중 검증 분리 근거 3행을 추가했다.
- 새 규칙이 드러낸 기존 부채(pending 1쌍): `trading/supabase_repository.py → reporting/readers/runtime.py`. 후보 선정(`_candidate_last_analyzed`, `_last_attempted`)이 Trading 자신의 로컬 판단 원장을 reporting reader(`read_local_rows("security_decisions", canonical_db=…)`)로 읽는다. 올바른 방향은 Trading이 그 읽기(security_id→ticker 신원 해석과 evidence 요약 결합)를 소유하고 reporting reader가 그것을 소비하는 것이다. 후보 선정은 과거에 PGRST106 장애가 있었던 자리이고 `test_candidate_ranker.py`가 "신원 조회기를 받아야 한다"는 동작을 고정하고 있어, Trading 로컬 원장 쿼리 빌더 계약(`in_` 지원 등)을 확인한 뒤 별도 단위로 처리해야 한다.
- 수정·삭제·이동 파일: 새 `tests/investment_agent/reporting/test_dashboard_reader_contracts.py`, `reporting/services/financial_row.py`(`notifications/earnings_report/capital.py`에서 이동), `dashboard/db.py`(사본·상수·import 삭제), `test_dashboard_readonly.py`, `scripts/verify_integration.py`, `trading/supabase_repository.py`, `test_architecture.py`, `CLAUDE.md`, 이 원장.
- 테스트: 신규 reader 계약 10개 통과, dashboard readonly 19개 통과, 규칙 강화 직후 실제 위반 3건 RED(reporting→notifications 2, trading→reporting 1), 수정 후 architecture 36개 통과. 사본 삭제 후 전체 suite 3,080개 OK(skip 1)였고, 이후 변경(façade 정리·capital 이동·가드) 뒤의 전체 실행 결과는 아래 최종 검증에 기록한다.
- 남은 dependency debt: (1) pending 1쌍(위). (2) `COMPOSITION_ROOTS` 8개 파일과 `build_features`의 `ContextBuilder`(승인된 예외, 증거 조립기·`EvidenceBundle` 소유권은 Trading). (3) 시스템 검증 예외 6개 import. (4) `dashboard/db.py` 잔여 로더 이동, `SupabaseRepository` God façade 분해.

#### 재개 세션 배치 E — Trading 판단 원장 읽기 소유권 (2026-09-20)

- 변경 전 호출 관계: 후보 선정(`SupabaseRepository._candidate_last_analyzed`, `_last_attempted`)이 Trading 자신의 로컬 판단 원장을 `reporting.readers.runtime.read_local_rows("security_decisions", canonical_db=…)`로 읽었다. Trading이 reporting을 역방향 import하는 유일한 자리였고 배치 D의 강화된 규칙이 이를 pending 1쌍으로 드러냈다.
- 변경: `TradingRepository.security_decision_attempts()`(security_id·status·as_of_at)가 판단 원장 읽기를 소유한다. `SupabaseRepository._decision_attempts()`가 그 행에 Data owner의 `select_tickers_by_security_id`로 ticker를 붙이고, 신원을 못 찾는 행이 있으면 기존과 같이 `RuntimeError("local decisions reference unknown securities")`로 실패한다(조용히 버리면 coverage가 어긋난다). 원장이 비어 있으면 신원 조회를 하지 않는다. 성공·기권만 coverage로 세고 실패는 순환용 마지막 시도로만 세며 as_of 이후 판단은 무시하는 의미는 그대로다. reporting의 `read_local_rows("security_decisions")`는 화면 read model로 그대로 남는다.
- 테스트: 새 `TradingRepository` 읽기 계약 2개와 후보 coverage 테스트 재작성(경계 두 개만 대체) 포함 9건이 메서드 부재로 RED였고 구현 후 통과했다. 소스 import 제거 뒤 pending 쌍이 "해소된 부채" 실패(RED)를 냈고 삭제 후 architecture 36개 통과. 실제 로컬 SQLite에서 새 읽기가 `{'security_id': 7, 'status': 'completed', 'as_of_at': …}`를 돌려주는 것을 확인했다.
- import 방향 변화: `trading → reporting` 0건. `PENDING_DEPENDENCIES`는 빈 집합이다.

#### 재개 세션 배치 F — 남은 응집도 항목의 판단 (2026-09-20)

배치 E 뒤 `PENDING_DEPENDENCIES`는 0쌍이다. 남은 세 항목은 의존성 방향 위반이 아니라 응집도·소유권 문제이며, 각각 실제 호출자를 확인한 결과 지금 움직이면 판단·실행 인접 코드의 시그니처가 넓게 바뀐다.

- `SupabaseRepository` God façade 분해(보류): public 메서드 중 caller 0은 배치 D에서 지웠다. 남은 것은 세 군이다. (A) Trading 원장 forwarding 15개는 호출자가 `trading/decision/analysis.py`·`trading/my_portfolio.py`·`trading/system/engine.py`이고 데이터 읽기와 같은 `repository` 객체로 받으므로 분리하면 시그니처와 테스트 fake가 넓게 바뀐다. (C) 후보 선정 358줄은 façade 밖 멤버를 `current_tracked_tickers`·`market_prices`·`sp500_sector_map`·`_memo`·`_trading_repository`만 쓰는 응집된 조각이지만, 그중 `factor_cross_section`·`thesis_views`를 `trading/system/engine.py`(System Portfolio 실행)와 `research/system_validation/ablation.py`의 replay 어댑터가 같은 `repository` 객체의 메서드로 호출한다. 추출하려면 `run_system`의 인자와 replay 의미를 바꿔야 한다. (B) 데이터 읽기 조립(`market_prices`·`fundamentals`·`macro`·`segment`·`guru`·`econ`·replay mirror)은 Research 조립 진입점이 Trading 객체를 쓰는 이유지만, 이것을 Research 소유로 옮기면 `architecture-target.md`가 `trading/evidence`에 둔 증거 조립 설계를 뒤집는 것이라 사용자 결정이 필요하다. 재개 시 (C)를 하려면 `run_system`에 후보 원천을 주입하는 인자를 먼저 도입하고 replay 어댑터를 그 인자로 옮긴 뒤 façade 위임을 지운다.
- `dashboard/db.py` 잔여 로더 이동(보류): dashboard→reporting 방향은 이미 맞다. 남은 파일은 SELECT 전용 gateway와 화면 3개가 쓰는 로더이며, 이동은 안전 경계 파일의 대규모 이동이라 CLAUDE.md·README·정적 경계 테스트의 경로 문자열이 함께 바뀌고 이득은 응집도뿐이다.
- dashboard earnings 화면의 `notifications/earnings_report/` import(유지): 이 화면은 Discord 카드 미리보기이며 `card`·`charts`·`candidates`를 그대로 써서 "화면에 보이는 것이 실제로 발송되는 카드"를 보장한다. 계산을 reporting으로 복제하면 미리보기와 발송이 어긋날 수 있다.
- 다음 재개 지점: 사용자가 (B) 증거 조립 소유권을 정하면 그에 따라 Research 조립 예외 8개(`COMPOSITION_ROOTS`)를 줄일 수 있다. 그 결정이 없으면 이 문서의 나머지는 응집도 개선 후보로만 남는다.

#### 배치 G1 — PIT 증거 계약·조립기·통계를 Research로 (2026-09-20, 사용자 지시: 전 권한 위임, 남은 항목 전부 진행)

- 결정: 사용자가 전 권한을 위임해 배치 F가 보류한 "증거 조립 소유권"을 Research로 확정한다. 근거: Research feature와 Trading 판단이 같은 PIT 사실을 읽는 것이 학습·서빙 일관성의 핵심이고, 방향은 data → research → trading이므로 두 소비자의 공통 원천은 위쪽(Research)이 갖는 것이 맞다. 이것은 `architecture-target.md`가 `trading/evidence`에 적었던 후보를 뒤집는 결정이다. Trading 전용인 dossier·renderer·history·builder는 `trading/evidence`에 남는다.
- 이동: `EvidenceItem`·`EvidenceBundle`(`trading/contracts.py`) → `research/evidence/contracts.py`, `trading/evidence/context.py`(`ContextBuilder`) → `research/evidence/context.py`, `trading/evidence/tools.py`(가격·재무·품질·추정 통계) → `research/evidence/statistics.py`. `ContextBuilder`가 쓰던 `REQUIRED_BARS`는 어댑터가 아니라 `research/features/layer.py`에서 직접 읽는다. 호환 재수출은 만들지 않았다.
- 소비 방식: Trading 파일 11개는 기존 공개 계약 `research/adapters/trading.py`(exact 예외)에서만 새 이름을 가져온다(`ContextBuilder`, `EvidenceBundle`, `EvidenceItem`, `FILING_ROWS_IN_PROMPT`, 통계 4종). 그 밖의 소비자는 새 모듈을 직접 가리킨다. 재작성된 import 파일은 24개다.
- 테스트: `tests/investment_agent/research/evidence/test_evidence_ownership.py`가 세 클래스의 정의가 새 위치에만 있고 옛 Trading 모듈이 없음을 AST로 강제한다(RED 6건 후 통과, 합성 중복 정의 검출 포함). 증거 테스트 4개는 Trading 테스트 폴더에서 Research로 옮겼다. `COMPOSITION_ROOTS`에서 `build_features`의 `ContextBuilder` 예외를 제거했다. 전체 suite 3,110 OK(skip 1).
- 남은 일: 조립기가 쓰는 데이터 읽기 조립(`SupabaseRepository`의 market·fundamentals·macro·segment·guru·econ·replay mirror)을 Research reader로 옮기는 G2, Trading 원장을 다루는 CLI 진입점을 operations로 옮기는 G3.

#### 배치 G2 — PIT 데이터 읽기 조립을 Research reader로 (2026-09-20)

- 변경 전: `SupabaseRepository`(Trading)가 market·fundamentals·macro·segment·guru·econ 읽기, 판단 시각 재사용 캐시, 과거 재현 mirror를 구현했고 Research feature·label·valuation·backfill 진입점이 이 Trading 객체를 조립했다.
- 변경: 그 읽기 30개 메서드와 `PointInTimeReaderCache`, 공유 helper(`guru_candidate_signals`)를 `research/evidence/reader.py`의 `PitReader`로 옮겼다(약 650줄). `SupabaseRepository`는 `PitReader`를 **상속**하고 Trading 원장 위임·후보 선정만 갖는다(약 780줄). Trading은 기존 공개 계약 `research/adapters/trading.py`로만 `PitReader`를 가져온다. reader는 Trading을 import하지 않으며 어댑터도 거치지 않는다(`normalize_ticker`는 동일한 platform 함수, 기술지표는 `research/features/db.py` 직접).
- 조립 예외 축소: `build_features`·`build_labels`·`build_valuations`·`backfill_research_history`가 `PitReader`를 직접 만든다. `COMPOSITION_ROOTS`는 8개에서 4개(`build_decision_experiences`, `evaluate`, `system_ablation`, `promotion/cli`)로 줄었다. 이 네 진입점은 Trading 원장을 읽고 쓰는 job이라 G3에서 다룬다.
- 테스트: 소유권 가드(`test_evidence_ownership.py`)가 `PitReader`·캐시 정의 위치, Trading 저장소가 PIT 메서드를 재정의하지 않고 상속만 하는지, `research/evidence`가 Trading을 import하지 않는지를 강제한다. `SupabaseRepository`에 `market_prices`를 재정의해 넣으면 실패함을 확인하고 원복했다. 예외 4개를 먼저 뺀 상태에서 architecture가 RED였고 import 전환 뒤 통과했다. 옛 모듈을 patch하던 테스트는 새 소유 위치(`research.evidence.reader`)를 가리키게 고쳤고, econ·mirror 테스트는 `PitReader`를 직접 검증한다. 전체 suite 3,110 OK.
- 남은 일: G3(Trading 원장 job의 진입점을 operations로), 후보 선정 분리, `dashboard/db.py` 이동.

#### 배치 G3 — Trading 원장 job의 진입점을 operations로 (2026-09-20)

- 변경 전: `research/commands/{evaluate,system_ablation,build_decision_experiences}`와 `research/promotion/cli.py`의 `main()`이 구체 `SupabaseRepository`로 Trading 판단 원장을 읽고 써서 Research의 조립 예외 4개로 남아 있었다. 이 경로는 하네스 허용 목록·어댑터·문서·테스트가 명령으로 직접 호출한다.
- 변경(정비 보류가 걸린 상태에서 하네스 코드 수정, hold·kill switch·`TOSS_LIVE_ENABLED` 불변): `evaluate.py` → `operations/commands/evaluate_decisions.py`, `promotion/cli.py` → `operations/commands/promote_model.py`, `system_ablation.py` → `operations/commands/system_ablation.py`로 이동했다. `build_decision_experiences`는 경험 계산(`run`·`build_experience`)을 Research에 두고 `main()`만 `operations/commands/build_decision_experiences.py`로 분리했다. 하네스 허용 목록(`harness_adapters.py`)과 어댑터(`operations/adapters/research.py`)의 모듈 문자열, 문서 명령 8곳, 하네스 단계 테스트를 새 경로로 갱신했다. 옛 경로 호환 shim은 없다.
- 테스트: 프로모션 CLI 테스트를 `tests/investment_agent/operations/commands/test_promote_model.py`로 옮겼다. 마지막 조립 예외 4개를 먼저 뺀 상태에서 architecture가 RED였고 이동 뒤 통과했다. 비어 버린 조립 예외 메커니즘(`COMPOSITION_ROOTS`와 전용 테스트 2개)은 삭제하고 "Research 모듈이 구체 Trading 저장소를 import하면 실패한다"는 주입 테스트만 남겼다. CLAUDE.md의 조립 예외 행을 현재 사실로 바꿨다. 전체 suite 3,110 중 실패 1건은 사용자 동시 작업인 `data/news/` 디렉터리를 금지하는 intelligence 가드이며 이 변경과 무관하다.
- 결과: Research → Trading import 예외는 `research/system_validation/ablation.py`의 6개 import뿐이다. 조립 예외는 0개다.
- 남은 일: 후보 선정·Trading 원장 위임 분리, `dashboard/db.py` 이동.

#### 배치 G4 — 후보 선정을 `trading/decision/candidates.py`로 (2026-09-20)

- 변경 전: G2 뒤에도 `SupabaseRepository`(781줄)에 Trading 판단 로직인 후보 선정(약 360줄)과 판단 원장 위임이 섞여 있었다. 배치 F는 `run_system` 인자와 replay 의미를 바꿔야 한다고 보류했다.
- 변경: 호출자 API를 바꾸지 않는 방식으로 후보 선정 16개 메서드(`candidate_tickers`, `event_reanalysis_priorities`, `factor_cross_section`, `thesis_views`, 마지막 분석·시도 시각, 판단 시도 행 ticker 해석 등)와 helper 2개를 `trading/decision/candidates.py`의 `CandidateSelection`으로 이동했다. `SupabaseRepository`는 `PitReader`(Research)와 `CandidateSelection`(Trading 판단)을 합성하고 Trading 원장 위임 메서드만 직접 가진다. 그 결과 `supabase_repository.py`는 약 1,340줄에서 300줄이 됐고, `run_system`·ablation replay 어댑터·operations 호출자는 바뀌지 않았다.
- 테스트: 소유권 가드(`test_repository_ownership.py`)가 후보 선정 메서드의 정의가 `CandidateSelection`에만 있고 `SupabaseRepository`가 재정의하지 않음을 강제하며, 재정의를 넣으면 실패함을 확인하고 원복했다. 옛 모듈을 patch하던 테스트 5개는 새 위치를 가리키게 고쳤고 `research_store_read_paths` 가드는 `reader.py`·`candidates.py`·`supabase_repository.py`를 모두 검사한다. 전체 suite 3,110 중 실패 1건은 사용자 동시 작업 `data/news/`를 금지하는 intelligence 가드다.
- 남은 일: `dashboard/db.py` 이동, Trading 원장 위임 15개를 호출자가 `TradingRepository`를 직접 쓰게 하는 정리(호출자가 데이터 읽기와 같은 객체를 받으므로 별도 배치).

#### 배치 G5 — dashboard의 저장소 접근을 reporting으로 (2026-09-20)

- 변경 전: `dashboard/db.py`(약 1,380줄)가 SELECT 전용 gateway와 화면 3개(`ai_approval`·`intelligence`·`earnings`)의 로더를 함께 갖고 있어 화면 패키지가 저장소를 직접 열었다.
- 변경: 파일을 세 reporting reader로 나눴다. `reporting/readers/select_only.py`(`SelectOnlyGateway`와 공통 helper, 약 250줄), `reporting/readers/earnings.py`(실적 로더 묶음과 `load_ticker_data_quality`), `reporting/readers/ai.py`(`load_ai_data`). 화면 3개는 새 reader를 import하고 `dashboard/db.py`는 삭제했다. 공통 helper는 공개 이름이 됐다(`open_gateway`·`preflight`·`latest_at`·`security_identity` 등, 지역 변수 `gateway`와의 충돌을 피해 `_gateway`는 `open_gateway`로).
- 안전 계약의 강화: 호출자가 0개이고 allowlist가 비어 있던 RPC 경로(`select_function_rows`, `READ_ONLY_FUNCTIONS`)를 삭제했다. 이제 gateway에는 RPC 능력이 코드에 없고, allowlist 테스트 3개는 "gateway에 그 메서드가 없다"와 "reader·화면 소스 어디에도 `.rpc()`·`select_function_rows` 호출이 없다"는 계약으로 바뀌었다. dashboard 정적 경계 테스트의 `.rpc()` 예외도 사라져 예외 없이 금지다.
- 가드: reporting 읽기 전용 가드(`test_reporting_guards.py`)에 gateway 예외를 좁게 추가했다 — `select_only.py`의 `.table()`은 반드시 `.select()`가 바로 이어져야 하고 `.execute()`는 `SelectOnlyGateway.select_rows` 안에서만 허용한다. 예외를 깨뜨리는 주입 5건(다른 메서드의 execute, table().insert, table().select().upsert, rpc, 다른 파일에서 같은 코드)이 모두 실패한다. 실제 gateway 파일에 `.upsert`를 넣으면 가드가 실패함을 확인하고 원복했다. architecture의 `DashboardReportingBoundaryTest`는 "dashboard에 `db.py`가 없고 `investment_agent.dashboard.db`·`platform.db`를 import하는 모듈이 없다"로 강화했다(주입 2건 검증).
- 테스트·문서: `test_gateway_in_chunks.py`를 reporting 테스트로 옮기고 dashboard 로더 테스트·소스 경로 참조 테스트 3개를 새 위치로 갱신했다. CLAUDE.md·`docs/README.md`·reporting/dashboard README·`scripts/verify_integration.py`를 새 구조로 고쳤다. 전체 suite 3,109 중 실패 1건은 사용자 동시 작업 `data/news/`를 금지하는 intelligence 가드다.
- 결과: dashboard 패키지에는 저장소 접근 코드가 0개다. dashboard→notifications 1건(earnings 카드 미리보기)만 의도적 예외로 남는다.

## 향후 milestone

| 묶음 | 해당 phase | 독립 완료 조건 |
|---|---|---|
| 저장·연구 경계 | 2~3 | 연구의 일반 trading import 제거, owner별 저장 경계, 단계별 façade 축소 |
| 판단·실행 경계 | 4~5 | RiskGate가 intent 미생성, broker 계약이 live runtime에서 사용, 안전 테스트 유지 |
| 조회·발송 경계 | 6·8 | dashboard read가 reporting 소유, engine이 Discord 구현을 직접 모름 |
| 저장 관례·운영·정리 | 7·9~10 | 실제 중복만 정리, 불필요한 façade 삭제, architecture 가드 강화 |

각 묶음은 해당 시점의 코드와 caller inventory를 다시 검증해 세부 계획을 작성한다. 목표 구조 문서의 후보 파일명을 완료 사실로 취급하지 않는다.
