# 문서 지도 — 처음 보는 사람을 위한 시스템 안내

평소에는 이 문서와 루트 `README.md`만 읽으면 된다. `docs`는 실행되는 코드가 아니라 사람과
코딩 에이전트가 참고하는 설명서다. 주제마다 파일을 쪼개면 같은 설명이 여러 곳에 복사되고
한 곳만 갱신되므로 중심 문서에 모은다. 문서는 **지금 무엇인가**만 말한다 — 무엇이 어떻게
바뀌었는지는 git이 갖는다.

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

실행 코드 추적, 외부 연구 비교, 고도화 결정·검증·다음 작업은 기존
[코드 품질 감사의 투자 시스템 고도화 절](superpowers/audits/2026-09-20-code-quality-overhaul.md#9-투자-시스템-고도화--실행-경로연구결정인계)에 통합한다.
현재 알고리즘 설명은 [INVESTMENT_SYSTEM](INVESTMENT_SYSTEM.md)이 담당한다.

점검 기록은 [감사 폴더](superpowers/audits/)에 날짜 순으로 쌓이고 **각 보고서가 이전 것을 링크한다** —
가장 최근 파일부터 거슬러 읽으면 된다. 여기에 최신 파일 이름을 적지 않는 이유는, 적으면 다음 점검 때
갱신되지 않고 낡기 때문이다.

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
→ src/investment_agent/notifications/engine.py (Postgres notifications 원장 예약)
→ src/investment_agent/notifications/channels/discord.py
→ 발송 결과 기록(notices·deliveries)
```

`src/investment_agent/data/universe/watchlists`는 관심종목, `src/investment_agent/notifications/discord_admin`은 채널·역할 구성 도구다. 실제 알림
발송의 중심은 `src/investment_agent/notifications`다.

## 대시보드는 어디에 있는가

대시보드는 `src/investment_agent/dashboard`의 Streamlit 앱이다.

| 위치 | 역할 |
|---|---|
| `src/investment_agent/dashboard/app.py` | 앱 시작과 상단 메뉴 |
| `src/investment_agent/dashboard/app_pages` | 매크로·실적·13F·퀀트·AI 승인·포트폴리오·시스템 화면 |
| `src/investment_agent/reporting/readers/select_only.py` | Supabase 읽기 전용 SELECT gateway |
| `src/investment_agent/dashboard/calculations/` | 화면용 계산 |
| `src/investment_agent/dashboard/components/` | 공통 화면 조각과 색상 |
| `src/investment_agent/reporting/models.py` | 화면·읽기 결과 데이터 구조 |
| `src/investment_agent/reporting/readers/news.py` | 뉴스 read model (원문은 intelligence DuckDB) |
| `src/investment_agent/platform/cache.py` | 선택적 Streamlit 캐시 경계 |
| `src/investment_agent/platform/external_usage.py` | 외부 provider 호출량 원장 |
| `src/investment_agent/dashboard/ops.py` | 하네스 상태의 읽기 전용 표시 투영 |

Windows에서는 `scripts/dashboard.bat`을 실행한다. 대시보드는 관제 화면이며 DB mutation, Discord
발송, 승인 변경과 주문 실행을 하지 않는다.

## 투자를 판단하는 곳은 어디인가

AI 기반 판단의 중심은 `src/investment_agent/trading`다.

```text
SYSTEM PORTFOLIO (실계좌·승인을 모른다)
decision/universe.py                           tracked universe로 판단 대상 제한
→ decision/candidates.py + candidate_ranker.py  분석할 종목 선택(System 보유·새 정보 우선)
→ research/evidence/context.py                 PIT 근거 묶음 생성 (Research가 소유)
→ decision/analysis.py                         TradingAgents 논지 → 신호 배치
→ decision/alpha.py                            factor 기대수익 + 논지 검증 → 기대수익·제약
→ system/target.py                             위험예산 → optimizer → RiskGate → 목표비중
→ system/engine.py                             비중 기반 NAV·성과
MY PORTFOLIO
→ my_portfolio.py                              System 목표 − Toss 계좌 = 추종 제안
→ execution/                                   Discord 승인 → Toss 주문 → 대사
```

근거 조립과 feature는 `trading`이 아니라 `research`가 소유하고, Trading은
`src/investment_agent/research/adapters/trading.py` 하나로만 가져온다. 계층 사이에
허용되는 화살표 전체는 [시스템 아키텍처](SYSTEM_ARCHITECTURE.md)에 있다.

System Portfolio는 프로그램 판단을 100% 따랐다면의 전략을 추적하고 주문을 내지 않는다. 실계좌 주문은
My Portfolio 추종 제안이 Discord에서 승인된 뒤에만 나간다.
`research/features/`, `research/models/`, `research/rl/`, `research/backtest/`,
`research/qlib_adapter.py`는 연구·검증 계층이며 파일이 있다는 이유만으로 실전 채택된 것은 아니다.

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

## 목적별로 읽을 문서 하나

찾는 것이 아래 질문 중 하나라면 그 문서 **하나만** 열면 된다. 같은 사실을 여러 문서에
복사하지 않으므로, 어느 문서가 그 사실의 주인인지가 곧 어디를 읽을지다.

| 알고 싶은 것 | 문서 |
|---|---|
| 전체가 어떻게 생겼고 어떤 의존이 허용되는가 | [시스템 아키텍처](SYSTEM_ARCHITECTURE.md) |
| 어떤 사실이 네 저장소 중 어디에 사는가 | [저장 지도](STORAGE_MAP.md) |
| 수집·PIT·품질·provenance는 어떻게 동작하는가 | [데이터](DATA.md) |
| 판단·ML/RL·optimizer·RiskGate는 무엇을 하는가 | [투자 시스템](INVESTMENT_SYSTEM.md) |
| 자율 판단 계층의 패키지 경계와 계약 흐름 | [자율 판단 계층](AUTONOMOUS_SYSTEM.md) |
| 승인·broker·Paper/Live·안전장치 | [실행과 안전](EXECUTION_AND_SAFETY.md) |
| 설치·Actions·하네스·상태 확인·장애 대응 | [운영](OPERATIONS.md) |
| 어떤 환경변수가 어디에 필요한가 | [환경변수](ENV.md) |
| 알림 카드와 대시보드 UI 규칙 | [디자인 시스템](../DESIGN-system.md) |
| 코드를 고칠 때 지켜야 할 규칙 | [CLAUDE.md](../CLAUDE.md) |
| 지식 그래프를 MCP 서버로 붙이는 법 | [Graphify MCP](GRAPHIFY_MCP.md) |
| 다이어그램을 고치고 다시 빌드하는 법 | [다이어그램](diagrams/README.md) |
| 판단 계층이 넘지 않는 선 | [Trading Constitution](../src/investment_agent/trading/CONSTITUTION.md) |

package를 직접 고칠 때는 그 폴더의 README가 가장 가깝다 — 책임·경계·진입점·불변식을
그 자리에서 말한다.

| 패키지 | README |
|---|---|
| 수집 | [universe](../src/investment_agent/data/universe/README.md) · [market](../src/investment_agent/data/market/README.md) · [fundamentals](../src/investment_agent/data/fundamentals/README.md) · [macro](../src/investment_agent/data/macro/README.md) · [institutional](../src/investment_agent/data/institutional/README.md) |
| 텍스트 | [intelligence](../src/investment_agent/intelligence/README.md) |
| 연구 | [research](../src/investment_agent/research/README.md) · [features](../src/investment_agent/research/features/README.md) · [strategies](../src/investment_agent/research/strategies/README.md) |
| 판단·실행 | [trading](../src/investment_agent/trading/README.md) · [execution](../src/investment_agent/execution/README.md) |
| 읽기·표시 | [reporting](../src/investment_agent/reporting/README.md) · [dashboard](../src/investment_agent/dashboard/README.md) |
| 알림 | [notifications](../src/investment_agent/notifications/README.md) · [discord_admin](../src/investment_agent/notifications/discord_admin/README.md) |
| 운영·공통 | [operations](../src/investment_agent/operations/README.md) · [harness](../src/investment_agent/operations/harness/README.md) · [platform](../src/investment_agent/platform/README.md) |

각 문서는 **지금 무엇인가**만 적는다. 무엇을 왜 바꿨는지는 git이 갖는다.

## 문서와 코드가 다르면

1. 최근 상태와 row count는 상태 명령과 DB 원장을 우선한다.
2. 계약과 안전 규칙은 코드, tests와 `src/investment_agent/trading/CONSTITUTION.md`를 우선한다.
3. 개발 규칙은 `CLAUDE.md`, 환경변수 목록은 `docs/ENV.md`와 `.env.example`을 우선한다.
4. 틀린 문장은 관련 중심 문서 한 곳만 고친다. 같은 설명을 여러 package README에 복사하지 않는다.

package README는 해당 폴더의 함수·테이블을 수정할 개발자를 위한 세부 참고서다. 일반 사용자가
모두 읽을 필요는 없다.
