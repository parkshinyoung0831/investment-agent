# 문서 지도 — 처음 보는 사람을 위한 시스템 안내

> 이 문서는 공개 저장소의 현재 구조를 설명하는 입문 문서입니다. 유지보수자용 작업 지시와
> 날짜가 붙은 검토 기록은 아래의 별도 문서로 분리되어 있습니다.

평소에는 이 문서와 루트 `README.md`만 읽으면 된다. `docs`는 프로그램이 실행하는 코드가 아니라
사람과 코딩 에이전트가 참고하는 설명서다. 주제마다 파일을 쪼개면 같은 설명이 여러 곳에
복사되고 한 곳만 갱신되므로, 아래 중심 문서에 모은다. 날짜가 붙은 감사·개편 기록은 이 문서군 안에는
남기지 않는다 — "무엇이 어떻게 바뀌었는가"는 git이 갖고 있고, 문서는 **지금 무엇인가**만
말한다. 다만 특정 시점의 조사 결과 자체가 산출물인 기록(예: v1 재구성의 외부 리뷰와
구→신 매핑 CSV)은 날짜가 붙은 채로 둘 수 있다 — 그 시점의 스냅샷이며, 상시 문서처럼
항상 최신 상태를 유지할 의무는 없다.

## 프로젝트를 한 줄로 설명하면

```text
외부 데이터
→ Supabase 저장
├→ Discord 알림
├→ 읽기 전용 대시보드
└→ AI Investor가 투자안 생성
   → optimizer가 목표 비중 계산
   → RiskGate가 절대 제한 검사
   → 승인된 경우에만 execution이 broker 주문
```

현재 실제 운용의 중심은 **데이터 적재와 Discord 알림**이다. AI·포트폴리오·주문 코드가
존재한다고 자동매매가 현재 활성화된 것은 아니다. Live는 기본 비활성이다.

## 쉬운 비유

| 구성 | 쉬운 의미 | 실제 위치 |
|---|---|---|
| Supabase | 데이터 창고 | 원격 Postgres |
| Data pipeline | 창고에 자료를 넣는 수집팀 | `src/investment_agent/data/` 도메인 |
| Notifications | 창고를 읽고 Discord로 알려주는 직원 | `src/investment_agent/notifications` |
| Dashboard | 창고와 운영 상태를 보는 화면 | `src/investment_agent/dashboard` |
| Trading | 자료를 보고 투자안을 만드는 두뇌 | `src/investment_agent/trading` |
| Execution | 승인 후 주문을 보내는 손 | `src/investment_agent/execution` |
| Harness | 노트북에서 작업 순서와 시간을 관리하는 운영 도메인 실행 매니저 | `src/investment_agent/operations/harness` |
| GitHub Actions | GitHub 서버에서 실행되는 자동 시간표 | `.github/workflows` |
| Docs | 사람이 읽는 설명서 | `docs`와 package README |

## 데이터 적재는 어디에 있는가

| 폴더 | 담당 데이터 |
|---|---|
| `src/investment_agent/data/universe` | 미국 종목, S&P 구성 이력과 CIK |
| `src/investment_agent/data/market` | 일봉 가격과 corporate action |
| `src/investment_agent/research/features` | RSI, MACD 등 기술지표 |
| `src/investment_agent/data/fundamentals` | SEC 공시, 재무제표, 실적, 세그먼트, 기대치 |
| `src/investment_agent/data/institutional` | 13F 매니저와 보유 종목 |
| `src/investment_agent/data/macro` | 금리, 환율, 변동성과 경기지표 |
| `src/investment_agent/data/macro/releases` | macro 경제지표 일정, 예상, 실제와 개정 |
| `src/investment_agent/research/strategies` | AI가 아닌 고정 규칙 전략의 월별 배분 |

각 폴더의 source/client가 외부 데이터를 가져오고 ETL/application이 정리한 뒤 db/infrastructure
코드가 원천 데이터는 Supabase, Research 파생 산출물은 로컬 DuckDB에 저장한다. `.github/workflows/*.yml`이 GitHub 서버에서 이 명령을 예약 실행한다.

상세한 PIT, Supabase와 뉴스 cache 설명은 [데이터 문서](DATA.md)에 있다.
무엇이 Supabase에 있고 무엇이 로컬 SQLite·DuckDB에 있는지는 [저장 지도](STORAGE_MAP.md)가
한 장으로 갖는다 — 저장소를 헷갈리면 없는 곳을 찾아가게 된다.

## Discord 알림은 어디에 있는가

`src/investment_agent/reporting/notifications`가 read model을 제공하고,
`src/investment_agent/notifications`가 발송 대상·표현·전송을 담당한다.

```text
src/investment_agent/reporting/notifications/<read-model>.py
→ src/investment_agent/notifications/<알림종류>/candidates.py
→ card.py·embeds.py·render.py
→ notification_outbox 원장 등록·선점
→ src/investment_agent/notifications/channels/discord.py
→ delivery 결과 기록
```

`src/investment_agent/data/universe/watchlists`는 관심종목, `src/investment_agent/notifications/discord_admin`은 채널·역할 구성 도구다. 실제 알림
발송의 중심은 `src/investment_agent/notifications`다.

## 대시보드는 어디에 있는가

대시보드는 `src/investment_agent/dashboard`의 Streamlit 앱이다.

| 위치 | 역할 |
|---|---|
| `src/investment_agent/dashboard/app.py` | 앱 시작과 상단 메뉴 |
| `src/investment_agent/dashboard/app_pages` | 매크로·실적·13F·퀀트·AI 승인·포트폴리오·시스템 화면 |
| `src/investment_agent/dashboard/db.py` | Supabase 읽기 전용 SELECT |
| `src/investment_agent/dashboard/calculations/` | 화면용 계산 |
| `src/investment_agent/reporting/models.py` | 화면·읽기 결과 데이터 구조 |
| `src/investment_agent/dashboard/ui.py`, `theme.py` | 공통 UI와 색상 |
| `src/investment_agent/data/news/provider.py` | 뉴스 provider 호출과 원문 없는 메타데이터 정규화 |
| `src/investment_agent/data/news/contracts.py` | data 계층 뉴스 결과 계약 |
| `src/investment_agent/platform/cache.py` | 선택적 Streamlit 캐시 경계 |
| `src/investment_agent/platform/external_usage.py` | 외부 provider 호출량 원장 |
| `src/investment_agent/dashboard/ops.py` | 하네스 상태의 읽기 전용 표시 투영 |

Windows에서는 `scripts/dashboard.bat`을 실행한다. 대시보드는 관제 화면이며 DB mutation, Discord
발송, 승인 변경과 주문 실행을 하지 않는다.

## 투자를 판단하는 곳은 어디인가

AI 기반 판단의 중심은 `src/investment_agent/trading`다.

```text
universe.py + candidate_ranker.py       분석할 종목 선택
→ context.py                            Supabase PIT 근거 묶음 생성
→ agents/tradingagents_adapter.py       AI 분석과 토론
→ portfolio/signal_book.py              공통 수익·확신·위험 신호
→ portfolio/optimizer.py                목표 비중 계산
→ risk/gate.py                절대 위험 제한 검사
→ trading/repository.py / execution/db.py 판단·제안·risk·주문 결과 저장
```

현재 하네스가 호출하는 주 분석 파일은 `trading/decision/portfolio_shadow.py`다. 이 경로는 투자안을 DB에
저장하지만 주문은 보내지 않는다.

`trading/decision/shadow_daily.py`와 `role_runner.py`는 로컬 multi-role Shadow와 계약 검증을
담당하는 보조 경로다. `feature_layer.py`, `ml`, `rl`, `backtest`, `qlib_adapter.py`는
연구·검증 계층이며 파일이 있다는 이유만으로 실전 채택된 것은 아니다.

상세한 AI, ML/RL, optimizer, RiskGate와 backtest는 [투자 시스템 문서](INVESTMENT_SYSTEM.md)에 있다.

## 주문을 담당하는 곳은 어디인가

`src/investment_agent/execution`만 broker credential과 주문 mutation 경계를 소유한다.

```text
RiskDecision
→ ExecutionIntent
→ Discord 승인 또는 제한된 permit
→ broker adapter
→ 주문·체결 원장
→ reconciliation
```

승인, 중복 주문 방지, 결과불명 주문, Toss adapter, broker reconciliation과 durable kill
switch가 이 폴더에 있다. AI Investor는 broker key에 접근하지 않는다.

자세한 Shadow/Paper/Live 단계는 [실행과 안전 문서](EXECUTION_AND_SAFETY.md)에 있다.

## 하네스는 무엇인가

`src/investment_agent/operations/harness`는 투자 판단 알고리즘이 아니라 로컬 자동 실행기다. 노트북에서 AI 분석,
승인 listener, 계좌 risk snapshot과 reconciliation을 정해진 시간과 순서로 호출한다.

| 계층 | 역할 |
|---|---|
| AI Investor | 판단을 계산 |
| Execution | 주문을 실행 |
| Harness | 언제 무엇을 실행할지 관리 |

하네스 내부 코드는 `src/investment_agent/operations/harness`, 실제 AI/execution 연결은 `src/investment_agent/operations/harness_adapters.py`,
사용자용 Windows 버튼은 `scripts/harness`에 있다. GitHub Actions와 달리 노트북에서 실행된다.

설치, GitHub Actions, 하네스와 장애 해결은 [운영 문서](OPERATIONS.md)에 있다.

## 전체 책임 경계

| 계층 | 소유하는 것 | 소유하지 않는 것 |
|---|---|---|
| Data | 수집, PIT/provenance와 품질 | 모델 신호와 주문 |
| Evidence/Feature | cutoff 조회, 결측과 version/hash | 미래 label 노출과 broker key |
| ML/RL/LLM | expected return, probability, confidence와 reasoning | 최종 비중과 hard risk |
| Optimizer | 명시적 목적함수와 목표 비중 | 승인과 주문 수량 |
| RiskGate | 절대 portfolio 제한과 승인/거절 | alpha 생성 |
| Backtest | 과거 체결, 비용, 장부와 metric | live broker 호출 |
| Execution | credential, 승인, 주문과 reconciliation | 투자 thesis와 LLM prompt |
| Ops/Harness | schedule, lock, heartbeat와 재시작 | 투자 판단 알고리즘 |

## 공개 독자가 읽을 상시 문서

| 문서 | 답하는 질문 |
|---|---|
| `README.md` | 폴더가 무엇이고 전체 흐름이 어떻게 연결되는가? |
| `DATA.md` | 데이터, Supabase, PIT, 품질과 뉴스 cache는 어떻게 동작하는가? |
| `ENV.md` | 어떤 환경변수가 어디에 필요한가? |
| `INVESTMENT_SYSTEM.md` | AI/ML/RL, backtest, optimizer와 RiskGate는 무엇을 하는가? |
| `AUTONOMOUS_SYSTEM.md` | 자율 판단 계층의 패키지 경계와 계약 흐름은 어떤 모양인가? |
| `EXECUTION_AND_SAFETY.md` | 승인, broker, Paper/Live와 안전장치는 무엇인가? |
| `OPERATIONS.md` | 설치, Actions, 하네스, 상태 확인과 장애 해결은 어떻게 하는가? |
| `V1_STATUS.md` | v1 구현과 오프라인 검증의 현재 상태는 무엇인가? 진행 중인 후속 리팩터링 로드맵은 [superpowers/specs](superpowers/specs/)를 본다. |

**위 문서들은 현재 canonical v1 시스템**을 설명한다. 구현·검증 수치와 외부 실행 보류
상태는 `V1_STATUS.md`가 관리하고, 나머지 문서는 각 도메인의 현재 계약을 설명한다.
기여 절차는 [루트 CONTRIBUTING.md](../CONTRIBUTING.md), 공개 전 확인사항은
[OPEN_SOURCE_READINESS.md](OPEN_SOURCE_READINESS.md)를 읽는다.

## 유지보수자·기록 자료

저장 계층 개편 제안은 [저장 최소화 검토와 Markdown 개정안](superpowers/specs/2026-09-06-storage-minimization-review.md)에 있다.
현재 DDL·코드와 대조한 목표 구조, PIT 한계, 문서별 교체 문안과 단계별 전환 기준을 다루며,
아직 적용되지 않은 설계를 현재 시스템 설명과 구분한다.

다음 작업 로드맵과 구조 검토 기록은 날짜가 붙은 스펙 문서로
`docs/superpowers/specs/`에 둔다. 완료되어 코드에 반영된 내용은 이 문서군에 남기지
않고 지운다 — "무엇을 했는가"는 git이, "지금 무엇인가"는 이 문서와 `V1_STATUS.md`가 갖는다.

## 문서와 코드가 다르면

1. 최근 상태와 row count는 상태 명령과 DB 원장을 우선한다.
2. 계약과 안전 규칙은 코드, tests와 `src/investment_agent/trading/CONSTITUTION.md`를 우선한다.
3. 개발 규칙은 `CLAUDE.md`, 환경변수 목록은 `docs/ENV.md`와 `.env.example`을 우선한다.
4. 틀린 문장은 관련 중심 문서 한 곳만 고친다. 같은 설명을 여러 package README에 복사하지 않는다.

package README는 해당 폴더의 함수·테이블을 수정할 개발자를 위한 세부 참고서다. 일반 사용자가
모두 읽을 필요는 없다.
