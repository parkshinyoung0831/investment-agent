# 의존성 방향 리팩터링 진행 원장

> 사용자가 요청한 새 세션 인계 문서다. 이것은 현재 아키텍처 SSOT가 아니다. 새 세션은 `AGENTS.md` → `CLAUDE.md` → `docs/superpowers/specs/2026-09-19-dependency-direction-design.md` → `docs/superpowers/architecture-target.md` → 이 파일 → 현재 계획 순서로 읽는다. 기록보다 Git·코드·테스트의 실제 상태가 우선한다.

## 식별과 현재 상태

- 기준 원격 `main`: `53b232bb1547a57d53dd45fa940c2f135c742edc` (2026-09-19 확인).
- 작업 브랜치: `codex/dependency-direction-refactor`.
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

1. `git status --short --branch`, `git log -1 --oneline`, `git ls-remote origin refs/heads/main`으로 브랜치·미커밋 변경·원격 변화 확인. 원격 `main`이 달라졌으면 무조건 자동 rebase하지 말고 차이를 검토한다.
2. 위 문서와 현재 계획을 읽고 마지막 완료 task/phase의 실제 커밋·테스트 출력을 확인한다. 이 파일의 기록만 믿고 이미 완료된 작업을 반복하지 않는다.
3. 각 phase를 시작하기 전에 호출자·대상·삭제 조건을 다시 확인한다. 하네스/실행 코드에는 maintenance 선행.
4. 단계별로 실패 테스트 → 최소 구현 → 대상 테스트 → import/architecture 테스트 → 가능한 전체 테스트를 수행하고 결과를 이 파일에 갱신한다.
5. 각 완료 기록에 `수정 전 호출 관계 / 이유 / 수정 파일 / 이동·삭제 파일 / import 방향 / 테스트 결과 / 남은 부채 / 다음 단계`를 빠짐없이 적는다. 계획의 별도 실행 ledger가 생기면 해당 경로와 task 번호를 함께 적는다.
6. `PENDING_DEPENDENCIES`의 정확한 남은 항목을 확인한다. 새 항목을 기준선에 추가하지 않는다.

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

## 향후 milestone

| 묶음 | 해당 phase | 독립 완료 조건 |
|---|---|---|
| 저장·연구 경계 | 2~3 | 연구의 일반 trading import 제거, owner별 저장 경계, 단계별 façade 축소 |
| 판단·실행 경계 | 4~5 | RiskGate가 intent 미생성, broker 계약이 live runtime에서 사용, 안전 테스트 유지 |
| 조회·발송 경계 | 6·8 | dashboard read가 reporting 소유, engine이 Discord 구현을 직접 모름 |
| 저장 관례·운영·정리 | 7·9~10 | 실제 중복만 정리, 불필요한 façade 삭제, architecture 가드 강화 |

각 묶음은 해당 시점의 코드와 caller inventory를 다시 검증해 세부 계획을 작성한다. 목표 구조 문서의 후보 파일명을 완료 사실로 취급하지 않는다.
