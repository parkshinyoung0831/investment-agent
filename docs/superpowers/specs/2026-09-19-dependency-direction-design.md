# 투자 에이전트 의존성 방향 리팩터링 설계

이 문서는 구현 전 검토용 설계다. 현재 구조의 단일 진실 공급원은 `CLAUDE.md`와 영역별 문서다. 구현이 끝나면 영구 문서는 실제 코드의 현재 모양만 설명하도록 갱신하고, 이 설계 메모는 Git에 추가하지 않는다.

## 목적과 성공 기준

사용자 요청은 파일 이동 자체가 아니라 실제 import와 호출 관계를 `data / intelligence → research → trading → execution` 방향으로 정렬하는 것이다. `reporting`은 읽기 전용 read model, `dashboard`와 `notifications`는 가능한 한 그 모델의 소비자, `operations`는 최외곽 조립·운영 계층, `platform`은 금융 도메인을 모르는 기술 계층으로 유지한다. 실행 결과·저장 형식·DB schema·CLI와 GitHub Actions 호출 계약은 바꾸지 않는다.

성공은 각 변경이 실제 호출자의 구체적 문제를 제거하고, 그 경로의 동작 테스트와 import 검증을 통과하며, architecture test의 `PENDING_DEPENDENCIES`가 줄어드는 것으로 판정한다. 최종적으로 대상 파일의 호출자가 0개일 때만 façade를 지운다. 남은 예외는 코드와 테스트로 명시하고 보고한다. AI 모델·factor·optimizer·risk 수치 자체의 개선은 범위 밖이다.

## 확인된 기준선

- 2026-09-19 원격 `origin/main`과 로컬 HEAD는 모두 `53b232bb1547a57d53dd45fa940c2f135c742edc`였고 작업 트리는 깨끗했다.
- `src/investment_agent`에는 Python 파일 745개가 있다. 현재 큰 영역은 data 219, research 102, notifications 100, trading 80, operations 70, reporting 45, execution 41, dashboard 41개다.
- `tests/investment_agent/test_architecture.py`는 계층별 import를 AST로 검사하고 방향 위반 69쌍을 정확한 축소 기준선으로 추적한다. `research/system_validation`과 `execution.contracts`, `research.adapters.trading`의 예외가 이미 선언돼 있다.
- `trading/supabase_repository.py`는 95개 메서드로 data owner read, research DuckDB 저장, trading 원장, execution 계좌 snapshot 저장을 함께 제공한다. `research/commands/build_features.py`, `trading/decision/analysis.py`, `operations/harness_adapters.py` 등이 실제 호출자다.
- `research/storage/repository.py`에는 feature Parquet, 일반 dataset record, strategy allocation, lineage, promotion 관련 메서드가 같이 있다. 하나의 generic `records()` 저장 엔진도 있어 메서드 수만으로 쪼개면 안 된다.
- `trading/risk/gate.py`의 `DeterministicRiskGate.create_execution_intent()`는 `execution.orders.intents.ExecutionIntent`를 만든다. `operations/commands/create_execution_intent.py`가 승인된 판단·snapshot·promotion을 검증한 다음 이를 호출해 execution 원장에 저장한다.
- `execution/brokers/contracts.py`에는 `BrokerAdapter` Protocol이 있으나 production 구현·호출자는 없다. `execution/orders/live_worker.py`는 Toss 타입과 API를 직접 사용한다. Toss 수량·수수료·매수 가능액·정규장·수동 handoff의 fail-closed 절차가 있어 단순 타입 교체가 아니다.
- `reporting/readers/dashboard.py`가 일부 화면 read model을 제공하지만 `dashboard/db.py`는 아직 4개 화면 모듈에서 호출된다. `SelectOnlyGateway`와 RPC 거부는 현재 읽기 전용 안전 경계다.
- `notifications/engine.py`는 Discord의 `Delivery`·`ForumThread` 등 타입과 `DiscordChannel` 기본 생성에 결합돼 있다. `reporting/notifications/earnings_report*.py`도 notifications의 계산 helper를 import해 reporting 방향에 역행한다.
- data의 `repository.py`/`persistence.py`/`db.py`는 의미가 다르다. 예를 들어 market `repository.py`는 DB 행 계약이고 `persistence.py`는 ticker·security id 변환 및 PIT 조회를 담는다. 이름만 보고 일괄 흡수하지 않는다.
- 기준선 architecture·관례·workflow 테스트 99개는 통과했다. 전체 `unittest`는 2,997개 중 오류 4개·skip 1개이며, 네 오류는 현 환경에 `lightgbm`·`xgboost`가 없어서 발생한다. 이 기존 환경 오류를 코드 회귀로 계산하지 않는다.

## 실제 런타임 경로와 소유권

1. GitHub Actions와 도메인 CLI는 `data/<owner>/commands` → application → provider/owner repository → Supabase 저장을 수행한다. 로컬 하네스는 `operations.commands.investment_harness` → `operations.harness.pipeline` → `operations.harness_adapters.ProductionInvestmentAdapters`로 job을 조립한다.
2. feature job은 `research.commands.build_features` → 현재 `SupabaseRepository`의 여러 data read → `ContextBuilder`·`FeatureLayer` → 현재 `SupabaseRepository.save_rl_feature_snapshots` → `ResearchStore`에 저장한다.
3. 판단 job은 `trading.decision.analysis` → 현재 `SupabaseRepository` evidence read → TradingAgents 판단 → 같은 façade를 통해 trading 원장에 저장한다. System Portfolio와 실제 계좌 follow는 별도 하네스 job이다.
4. 승인 후 주문 경로는 `operations.commands.create_execution_intent`의 scope·promotion·snapshot 확인 → risk decision에서 intent 생성 → execution 원장 저장 → `operations.commands.execute_toss_live` → 승인·control·lockdown 확인 → `TossLiveExecutionWorker`의 reserve-before-submit 및 결과 불명 reconciliation이다.
5. UI·알림은 각자의 entrypoint → reporting 또는 남아 있는 직접 read → 표시·발송으로 흐른다. 알림 원장은 발송 전 원자적 reserve를 수행한다.

소유권은 저장 매체가 아니라 변경 이유로 정한다. data는 원천 사실과 PIT read, research는 재계산 가능한 feature·dataset·학습 산출물, trading은 판단·목표·risk decision, execution은 승인·intent·계좌 snapshot·주문·체결·재조정 원장을 소유한다. `operations`는 다른 영역의 구체 구현을 조립할 수 있으나 도메인 계산을 소유하지 않는다.

## 선택한 접근과 대안

선택: 호출자 단위로 contract test를 먼저 두고 owner API로 옮긴다. 일시적 호환 façade는 이관 기간에만 둔다. 이후 import와 호출자 0건을 검사한 뒤 제거한다. 이 접근은 작은 검증 단위로 실제 저장·안전 동작을 유지한다.

대안인 일괄 파일 이동은 현재 69개 방향 위반과 워크플로 CLI 경로를 동시에 건드려 회귀 위치를 분리하기 어렵다. 반대로 기존 façade를 영구 유지하며 architecture test만 완화하면 문제를 숨길 뿐이다. 두 방식은 채택하지 않는다.

## 단계와 경계 결정

| 단계 | 변경 판단 및 목표 | 통과 조건 |
|---|---|---|
| 1 | 최신 HEAD·전체 파일·runtime·정적 import·기존 가드와 호출자를 확정한다. 그래프는 탐색 보조이며 소스가 판정 근거다. | 대상별 변경 전 호출 관계·테스트·잔여 부채 기록 |
| 2 | God façade에서 data read 조립, research 저장, trading 원장, execution snapshot을 실제 owner로 분리한다. 초기에는 façade로 위임해 동작을 유지한다. | 동일 PIT cutoff·pagination·원장 결과와 호출자 테스트 |
| 3 | research의 trading import를 용도별로 제거한다. 연구가 소유하는 데이터 계약은 research로 옮기고 trading 소비 계약은 필요한 값만 공개한다. production Trading 알고리즘 재현이 필요한 경우만 `research/system_validation`에 둔다. | 일반 research → trading import 0건, 해당 pending 항목 삭제 |
| 4 | `RiskGate`는 `RiskDecision`까지만 만들고, 확인된 decision에서 deterministic intent ID·TTL을 만드는 함수는 execution owner로 옮긴다. 실제 사용자 승인과 System Portfolio는 분리한다. | 승인·scope·promotion·freshness·TTL·ID·fail-closed 테스트 유지 |
| 5 | Toss 전용 preflight와 handoff 의미를 보존하면서 실사용 worker가 broker 계약을 소비하도록 한다. 현 `BrokerAdapter`가 부족하면 실제 필요한 작은 계약으로 조정한다. 다른 broker registry는 만들지 않는다. | 주문 reserve 이전 실패, 결과 불명 시 무재전송, idempotency·reconciliation 테스트 유지 |
| 6 | 남은 dashboard 화면 read를 reporting reader/service로 옮긴다. `SelectOnlyGateway`의 SELECT·RPC 차단을 동등한 경계에 보존하고 호출자 0건 후 `dashboard/db.py` 삭제를 판단한다. | offline 화면·read-only·pagination·상태 표시 테스트 유지 |
| 7 | ResearchStore는 feature, generic dataset, allocation 등 독립된 변경·테스트 경계가 있는 부분만 분리한다. data의 naming은 실제 중복이 입증된 모듈만 정리하고 fundamentals는 기존 SSOT를 존중한다. | 데이터 보존·PIT·DuckDB migration·전략 allocation 테스트 유지 |
| 8 | notification engine의 전송·수정에 필요한 최소 channel contract를 소유시키고 Discord 생성은 바깥 composition으로 옮긴다. reporting이 notifications 표현 helper를 거꾸로 읽는 경로도 정리한다. | reserve-before-send·revision·replay·forum thread·실패 처리 테스트 유지 |
| 9 | 각 owner API로 모든 production·test·CLI·workflow 호출자를 이관한 뒤에만 불필요한 façade, legacy alias, dead code를 제거한다. domain-owned command 이동은 경로 호환과 workflow 배선을 함께 검증할 수 있는 경우에만 한다. | 삭제 대상 import·동적 호출·workflow reference 0건 |
| 10 | 최종 의존성 테스트를 현재 실제 구조에 맞게 강화한다. 검사 대상이 0건이 되는 공허한 가드를 금지하고 위반 주입으로 각 새 규칙의 실패를 확인한다. | targeted import·architecture·전체 가능한 테스트 결과와 남은 예외 공개 |

매 단계의 종료 기록에는 수정 전 호출 관계, 수정 이유, 수정·삭제·이동 파일, import 방향 변화, 실행한 테스트와 결과, 남은 부채를 포함한다. Phase 1의 조사 결과가 제안과 다르면 변경을 취소하거나 더 작은 owner 경계를 선택한다.

## 안전·오류 처리

- 하네스·실행 코드를 변경하기 전에 저장소 지시에 따라 maintenance를 켠다. live flag를 코드로 변경하지 않는다. 유지보수 중 주문을 실행하거나 외부 LLM·broker를 호출하지 않는다.
- 승인·계좌 snapshot·promotion·execution mode·source kind를 하나로 합치지 않는다. `shadow` 판단과 승인된 `paper/live` 실행을 독립적으로 유지한다.
- 주문 POST 전에 reserve하고, timeout/5xx 등 결과 불명에는 재전송하지 않고 reconciliation이 판단하도록 한다. 계좌·킬스위치·일일 한도·시장 시간 검사는 줄이지 않는다.
- 저장소 read 분리는 PostgREST 1,000행 상한을 피하는 `select_all_paged()`와 PIT cutoff를 동일하게 유지한다. schema 변경은 이 리팩터링의 해법으로 쓰지 않는다.
- 알림은 baseline·lease·원장 reserve를 유지한다. Discord 전송 실패가 ETL 결과를 가리지 않도록 한다.

## 검증과 완료 산출물

각 소단위는 실패하는 계약 테스트 → 구현 → targeted 테스트 → import/architecture 검증 순서로 진행한다. 아키텍처 가드는 위반 하나씩 주입해 실제 실패를 확인한다. 최종 `python -m unittest discover -s tests -t .`을 실행하고, 선택적 ML 의존성이 없으면 기준선의 동일한 네 오류를 분리 보고한다. `graphify update .`로 수정 후 그래프를 동기화하되 구조 판정은 실제 import와 테스트를 따른다.

최종 보고에는 `src/investment_agent`의 실제 전체 파일 트리, package dependency 방향, 삭제·유지 구조와 이유, 주요 파일의 이동 전후, 남은 debt, 테스트 결과, 새 AI/ML/factor/optimizer/risk/broker/provider/channel 추가 위치, 내부 구현만 교체 가능한 경계, 실제 dependency와 설계의 일치 검증을 포함한다.

이 설계는 최종 폴더명을 미리 확정하지 않는다. 이름과 파일 분할은 각 단계에서 실제 호출자·테스트·저장 경계로 판정한다.
