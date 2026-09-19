# 의존성 방향 리팩터링 — 진행 원장

> 사용자가 요청한 새 세션 인계 문서다. 이것은 현재 아키텍처 SSOT가 아니다. 새 세션은 `AGENTS.md` → `CLAUDE.md` → `docs/superpowers/specs/2026-09-19-dependency-direction-design.md` → `docs/superpowers/architecture-target.md` → 이 파일 → 현재 계획 순서로 읽는다. 기록보다 Git·코드·테스트의 실제 상태가 우선한다.

## 식별과 현재 상태

- 기준 원격 `main`: `53b232bb1547a57d53dd45fa940c2f135c742edc` (2026-09-19 확인).
- 통합 작업 브랜치: `main`. 모든 phase는 이 브랜치의 연속 커밋과 이 진행 원장 하나로 추적한다. 임시 검증 브랜치를 만들더라도 완료 내용을 `main`에 통합한 뒤 이 원장을 갱신한다.
- 통합 기반 HEAD: `d30e2e5e7ce320641349ceb2d3d5a5c6ddbff6dc`에서 문서 브랜치를 `main`에 fast-forward했고 임시 브랜치를 삭제했다. 이후 커밋은 이 지점부터 이어진다.
- 현재 단계: 설계 문서 승인 완료. 첫 구현 계획 작성 완료·사용자 검토 대기. 제품 코드 변경 없음.
- 현재 계획: `docs/superpowers/plans/2026-09-19-repository-boundaries.md` (Task 1~4 미착수).
- 완료 단계: Phase 1의 최초 구조·runtime·import·기준 테스트 조사. Phase 2~10 구현은 시작 전.
- maintenance 상태: 확인·설정하지 않았다. 하네스 또는 execution 코드를 수정하기 전에 `harness_switch --maintenance on`을 수행하고 상태를 확인한다. live flag는 변경하지 않는다.

## 검증 기준선

| 검사 | 결과 | 의미 |
|---|---|---|
| `git ls-remote origin refs/heads/main` | 로컬 HEAD와 동일 SHA | 최신 `main` 기준 확인 |
| `python -m unittest tests.investment_agent.test_architecture tests.test_repo_conventions tests.test_workflow_wiring -q` | 99개 통과 | 구조·관례·workflow 기준선 |
| `python -m unittest discover -s tests -t .` | 2,997개, 오류 4개, skip 1개 | `lightgbm`·`xgboost` 미설치로 인한 기존 환경 오류 4개 |
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

## 향후 milestone

| 묶음 | 해당 phase | 독립 완료 조건 |
|---|---|---|
| 저장·연구 경계 | 2~3 | 연구의 일반 trading import 제거, owner별 저장 경계, 단계별 façade 축소 |
| 판단·실행 경계 | 4~5 | RiskGate가 intent 미생성, broker 계약이 live runtime에서 사용, 안전 테스트 유지 |
| 조회·발송 경계 | 6·8 | dashboard read가 reporting 소유, engine이 Discord 구현을 직접 모름 |
| 저장 관례·운영·정리 | 7·9~10 | 실제 중복만 정리, 불필요한 façade 삭제, architecture 가드 강화 |

각 묶음은 해당 시점의 코드와 caller inventory를 다시 검증해 세부 계획을 작성한다. 목표 구조 문서의 후보 파일명을 완료 사실로 취급하지 않는다.
