# 투자 에이전트 — 목표 구조

> 사용자 요청에 따라 보존하는 목표 설계다. **현재 파일 트리나 이미 달성된 의존성 규칙이 아니다.** 실제 현재 구조의 SSOT는 `CLAUDE.md`와 코드·테스트다. 구현은 `specs/2026-09-19-dependency-direction-design.md`의 판정 조건을 따른다.

## 실제 결과와 후보 지도의 차이 (리팩터링 종료 시점)

아래 "후보 지도"는 출발점이었고 다음 결정으로 달라졌다. 현재 구조의 기준은 코드와 `CLAUDE.md`다.

- 증거 계약·조립기·통계와 PIT 읽기 조립은 `trading/evidence`가 아니라 `research/evidence/`(`contracts.py`·`context.py`·`statistics.py`·`reader.py`)가 소유한다. Trading은 `research/adapters/trading.py`로만 가져온다.
- `dashboard/db.py`는 없다. 저장소 접근은 `reporting/readers/{select_only,earnings,ai}.py`이고 RPC 경로는 코드에 없다.
- broker 중립 계약(`execution/brokers/contracts.py`)은 만들지 않고 삭제했다. 시스템은 Toss 단일 broker다.
- `ResearchStore`는 한 저장소로 유지했다. `SupabaseRepository`는 `PitReader`와 `CandidateSelection`(`trading/decision/candidates.py`)을 합성한 Trading 원장 게이트웨이다.
- Trading 원장을 다루는 CLI 진입점은 `operations/commands`에 있다. Research가 Trading을 import하는 유일한 예외는 `research/system_validation/ablation.py`다.
- `notifications/channels/`(최소 channel 계약)와 `notifications/context.py`(조립)가 engine과 Discord 구현을 분리한다.

## 불변 목표

```text
data / intelligence → research → trading → execution
                                  ↘ reporting → dashboard / notifications
operations = 최외곽 orchestration·composition·monitoring
platform   = 금융 도메인을 모르는 공통 기술 계층
```

이 화살표는 실제 import와 runtime 호출의 방향이어야 한다. façade나 alias로 위반을 감추지 않는다. `reporting`은 read-only이고, `dashboard`와 `notifications`는 가능한 한 reporting의 read model을 소비한다. 저장소 경계는 데이터 의미와 소유권으로 정하며 Supabase·Research DuckDB·Runtime SQLite·Intelligence DuckDB의 역할을 보존한다.

## 이상적인 전체 구조의 책임 지도

아래는 사용자가 제공한 이전 분석의 구조를 잊지 않기 위한 **후보 지도**다. 파일명과 하위 폴더는 호출자·테스트 확인 후에만 확정한다. 빈 폴더·interface·registry는 만들지 않는다.

```text
src/investment_agent/
├─ config.py, bootstrap.py
├─ platform/
│  └─ db/                 # Postgres·DuckDB·SQLite 등 공통 연결 기술
├─ data/
│  ├─ universe/           # identity, tracked gate, membership, watchlists
│  ├─ market/             # 가격·배당·분할
│  ├─ fundamentals/       # SEC·재무·세그먼트·예상치·실적
│  ├─ macro/              # 시장 지표·경제 발표
│  └─ institutional/      # 13F
│     # 각 owner: domain → application → infrastructure/sources,
│     #           repository/persistence/db는 실제 계약을 기준으로 선택
├─ intelligence/          # 뉴스·소셜 수집과 원문 저장
├─ research/
│  ├─ features/, factors/, datasets/, models/, training/
│  ├─ evaluation/, backtest/, rl/, strategies/, valuation/, promotion/
│  ├─ storage/            # feature·dataset·allocation 등 실제 독립 경계
│  ├─ adapters/trading.py # production이 소비하는 좁은 공개 계약
│  └─ system_validation/  # production Trading 알고리즘의 연구 검증만 예외
├─ trading/
│  ├─ decision/           # AI·LLM·factor/ML signal·ALPHA 판단
│  ├─ evidence/           # 여러 data owner의 PIT 사실 조립
│  ├─ portfolio/          # target·optimizer·signal book
│  ├─ risk/               # deterministic RiskDecision, intent 미생성
│  ├─ system/             # Shadow/System Portfolio 목표·회계
│  ├─ performance/        # 성과 분석
│  └─ storage/            # trading 판단·목표의 원장 계약
├─ execution/
│  ├─ approval/           # 사람 승인과 permit
│  ├─ orders/             # intent·reserve·worker·주문 lifecycle
│  ├─ brokers/            # 실제 broker별 adapter (현재 Toss)
│  ├─ reconciliation/    # 결과 불명·체결·계좌 정합성
│  └─ safety/            # control·kill switch·lockdown
├─ reporting/
│  ├─ readers/           # 저장소별 SELECT 전용 접근
│  ├─ services/          # 주제별 read model 조립
│  └─ notifications/     # 알림용 read model
├─ notifications/
│  ├─ engine.py, ledger.py, topics.py
│  ├─ channels/          # 최소 channel 계약과 Discord 구현
│  ├─ renderers/         # 재사용 가능한 표현 원시값
│  └─ <kind>/            # 기존 카드·embed 패키지별 render/templates 유지
├─ dashboard/
│  ├─ app_pages/, components/, calculations/, assets/
│  └─ app.py             # 화면 표현; 직접 DB 접근은 최종 후보에서 제거
└─ operations/
   ├─ harness/, monitoring/
   ├─ commands/          # cross-domain CLI와 운영 명령
   └─ composition/       # 실제 concrete 구현 조립
```

`fundamentals`의 현재 복합 계층은 회계기간과 스키마를 공유하므로 보존 후보가 강하다. 알림별 `render.py`·`templates/`도 의도된 구조다. workflows의 명시적 cron, 4개 저장소, `stage`/`execution_mode`/`source_kind` 3축은 재배치 대상이 아니다.

## 주요 이관 후보와 채택 조건

| 기존 | 목표 후보 | 코드로 확인할 조건 |
|---|---|---|
| `trading/supabase_repository.py` | trading evidence read·trading persistence·research storage·execution snapshot으로 분리 후 삭제 | 모든 production/test 호출자와 저장 owner 확인, façade 호출 0건 |
| `trading/risk/gate.py`의 intent 생성 | execution의 deterministic intent 생성 | 승인·TTL·ID·scope·snapshot 불변 테스트 |
| `execution/orders/live_worker.py`의 Toss 직접 타입 | 실사용 broker 계약 + Toss adapter | Toss preflight·manual handoff·reserve·unknown outcome 의미 보존 |
| `dashboard/db.py` | `reporting/readers`와 service | 남은 4개 화면 호출자 0건 및 SELECT-only 안전 유지 |
| `research/storage/repository.py`의 다중 책임 | 독립 테스트·저장 경계별 분리 | generic dataset 엔진 중복·schema drift를 만들지 않음 |
| `data/*/persistence.py`, `macro/releases/db.py` | 필요한 경우 canonical repository/application으로 정리 | 이름이 아니라 중복·변경 이유·외부 호출 계약으로 판단 |
| `notifications/engine.py`의 Discord 타입 | 최소 channel contract | revision·reserve·forum thread·전송 실패 동작 동일 |
| `operations/commands/*`의 단일 도메인 CLI | owner CLI 후보 | Actions·하네스·문서 호출 경로를 함께 이관 가능 |

`execution/db.py`, `operations/harness_adapters.py`, `trading/local_store.py` 등은 이름만으로 삭제·이동하지 않는다. 운영·저장 경계를 확인해 의미가 실제로 바뀌는 경우에만 진행한다.

## 새 기능이 들어갈 자리

| 추가 | 첫 변경 위치 | 상위 구조 변경 여부 |
|---|---|---|
| OpenAI-compatible 모델·다른 LLM API | `trading/decision/llm/`과 모델 선택 계약 | 현재 범위에서는 불필요 |
| ML·RL 학습 모델 | `research/models/`, `research/rl/`, `research/training/` | 직접 주문 action을 만들지 않는 한 불필요 |
| feature·factor·전략 | `research/features/`, `research/factors/`, `research/strategies/` | 불필요 |
| production ALPHA·optimizer·risk·regime | `trading/decision/`, `trading/portfolio/`, `trading/risk/` | 불필요 |
| 데이터 provider | 해당 `data/<owner>/infrastructure/sources/` | canonical domain 계약이 유지되면 불필요 |
| broker | `execution/brokers/<provider>/`와 operations 조립 | 공통 worker 계약이 유지되면 불필요 |
| notification channel | `notifications/channels/`와 조립 | engine 계약이 유지되면 불필요 |
| dashboard page | reporting reader/service + `dashboard/app_pages/` | 불필요 |

옵션·선물·FX·크립토, 다중 머신 분산 실행, RL의 직접 portfolio action, 초단타 streaming은 현재 계약 밖의 도메인·운영 변화다. 그런 요구가 실제로 생기면 상위 구조를 재검토한다. 지금 이를 위한 폴더나 framework는 만들지 않는다.

## 절대 보존할 안전 조건

- Shadow/System Portfolio는 사용자 승인 계좌와 독립적이다.
- 실주문은 사람이 켜는 live flag, 승인, fresh snapshot, kill switch, deterministic risk, reserve-before-submit, reconciliation을 통과해야 한다.
- 결과 불명 주문을 재전송하지 않는다. hard risk limit와 최종 portfolio weight를 LLM에 위임하지 않는다.
- PostgREST 대량 읽기는 `select_all_paged()`를 사용한다. DB schema와 투자 알고리즘은 아키텍처 리팩터링의 부수 변경으로 손대지 않는다.
