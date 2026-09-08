# v1 현재 상태

> 이 문서는 공개 가능한 개발 상태 보고서이면서 유지보수 참고 자료입니다. 실거래 준비 완료를
> 의미하지 않으며, 라이브·외부 API·DB 실행 여부는 아래 제한을 따릅니다.

마지막 갱신: **2026-09-07**

이 문서는 현재 구현과 검증 상태만 기록한다. 작업 경위와 일회성 실행 절차는 기록하지
않는다.

기준 문서:

- 구조·작업 규칙: [CLAUDE.md](../CLAUDE.md), [AGENTS.md](../AGENTS.md)
- 진행 중인 리팩터링 로드맵: [superpowers/specs](superpowers/specs/)

## 현재 결론

정식 런타임과 데이터 owner는 `src/investment_agent/`다. 공통 플랫폼은
`src/investment_agent/platform/`, Discord 관리 도메인은
`src/investment_agent/notifications/discord_admin/`이 소유한다.

배포 패키지 이름은 `investment_agent`다. `src/` 자체는 패키지가 아니며, `pyproject.toml`과
`uv.lock`이 의존성 계약을 소유한다. `.env`는 import 시 읽지 않고 CLI entrypoint가
`investment_agent.bootstrap.start_cli()`로 한 번만 읽는다. Actions는 필요한 uv
dependency group만 locked sync한다.

v1 DB는 빈 상태에서 `db/postgres/v1/` 선언만으로 구성할 수 있어야 한다. 정식 실행 경로는 현재
선언과 현재 application contract만 사용하며, compatibility wrapper는 포함하지 않는다.

`src/investment_agent/operations/`는 공유 실행·운영 경계로 유지하고, execution owner는
`src/investment_agent/execution/`으로 이동했다. `LIVE_ENABLED`, `TOSS_LIVE_ENABLED`,
`TRADING_KILL_SWITCH`, `EXECUTION_LOCKDOWN`의 의미와 live worker 동작은 보존한다.

## 소유 구조

```text
src/investment_agent/
├── platform/                 공통 DB·직렬화·시계·로그·재시도·저장소·캐시·사용량 원장
├── data/
│   ├── universe/             종목·S&P 500·watchlist
│   ├── market/               가격·분할·배당
│   ├── fundamentals/         SEC 재무·세그먼트·실적·예상치
│   ├── macro/                거시 지표·발표·revision
│   ├── institutional/        13F manager·filing·position
│   └── news/                 뉴스 provider·정규화 결과 계약
├── research/                 feature·label·dataset·strategy·backtest·RL
├── trading/                  decision·portfolio·evidence·repository
├── reporting/                v1 read model과 reporting view consumer
├── notifications/            outbox·producer·Discord·discord_admin
├── operations/               Actions·heartbeat·운영 CLI·로컬 하네스
├── dashboard/                read-only Streamlit UI·하네스 상태 투영
└── execution/                승인·broker·주문·fill·reconciliation·TCA 안전 경계

```

평가 owner는 `src/investment_agent/research/evaluation/`(DSR·cost·shadow fill)와
`src/investment_agent/trading/performance/`(PnL·attribution)로 분리하고, TCA는
리뷰 §8에 따라 `src/investment_agent/execution/orders/tca.py`가 소유한다. Toss OAuth·조회·주문
client는 `src/investment_agent/execution/brokers/toss/`에 있으며, execution CLI는
`src/investment_agent/operations/commands/`에서만 노출한다.

## 데이터와 SQL

canonical schema는 `db/postgres/v1/`이다.

- `00_extensions.sql`: 공통 extension과 helper
- `10_universe.sql`: universe master(관심 기업 컬럼 포함)·identifier·membership
- `20_market.sql`: prices·splits·dividends
- `30_fundamentals.sql`: filing·wide financial·segments·earnings·consensus
- `40_macro.sql`: series(원천 이름 포함)·measure·observation·release·forecast
- `50_institutional.sql`: filing·position (manager 설명과 추적 대상은 코드 catalog)
- `90_reporting.sql`: reporting view

판단·실행·알림·운영 상태는 `data/local/runtime/runtime.sqlite3`와
`db/sqlite/runtime/v1/` DDL이 소유한다. 별도 PostgreSQL execution schema SQL은 없다.

`trading.model_versions`는 불변 artifact metadata만 보관한다. 현재 모델 단계는 승인된
`model_promotions` 이력에서 `reporting.current_model_stage`가 계산하며, 수동 승격은 artifact
행을 갱신하지 않고 잠금된 append-only audit으로 기록한다.

구독 목적지는 2026-09-07부로 `notifications.subscriptions` 테이블이 아니라 각 워크플로의
`DISCORD_CHANNEL_*` env와 `notifications/subscriptions.py`의 `KIND_ENV` 매핑이 SSOT다.
실사용이 전부 global(`security_id=None`, `is_enabled=true`, `active_from=오늘`)이었기 때문에
DB 왕복 없이 env를 직접 읽어도 동작이 같다.

- `discord_targets(kind, config=...)`: `KIND_ENV[kind]` 환경변수를 읽어 실패 시 즉시 예외
- `validate_subscriptions`: 각 kind의 env가 실제로 설정됐는지만 확인하는 workflow preflight
- 정규 notify workflow: producer 실행 전 validator 호출, 자기 채널 env를 직접 선언
- `configure_subscriptions`(DB 적재용)는 삭제됨 — 더 이상 적재할 DB 표가 없다

`ops_heartbeat`의 channel env와 execution 승인 채널 env는 운영 관측·승인 경계이므로
notification producer 경계와 다르다.

## 현재 검증

- 전체 오프라인 unittest: **2,367개 실행, 0 failures, 0 errors**.
- `python -m compileall -q src tests`: 통과
- `pyflakes src/investment_agent`: **문제 0개**
- `git diff --check`: 통과
- GitHub Actions YAML: **37개** 파싱 통과
- 활성 old path 검색(실제 경로·import 대상): **0개**
- workflow Python 모듈 import: **34개 성공** (앱 31개 + tooling 3개)
- canonical CLI entrypoint `--help`: **80개 성공** (모두 parser-only 경로로 종료)
- 문서의 canonical 애플리케이션 `python -m` 실행 참조: **133건**, 고유 모듈 **54개 전부 import 성공** (설치·테스트·placeholder 제외)
- `src/investment_agent` 공개 export 감사: **문제 0개**
- 활성 코드 주석·docstring Unicode 스크립트 감사: **비한글 스크립트 0건**
- 프로젝트 Markdown 50개 감사(유지보수자 문서·기록 자료 포함): **개인 경로·비밀값·인코딩 오류·깨진 내부 링크 0건**
- graphify code graph (rebuild 산출물): **13,455 nodes / 29,744 edges / 639 communities**
- graphify multigraph 진단: 누락·dangling·중복 edge **0건**, 의도된 execution 자기참조 FK **2건**

주요 정적 계약:

- 정규 notify workflow는 자기 kind에 필요한 `DISCORD_CHANNEL_*`을 env로 직접 선언한다.
- workflow validator kind와 dispatch alias가 일치한다.
- `notifications/subscriptions.py`의 `KIND_ENV`가 모든 notify kind를 채널 하나에 매핑한다.
- execution binding FK와 fail-closed control seed는 canonical v1 SQL에 직접 선언돼 있다.
- 대량 reader는 paged read 경계를 사용한다.
- accession 기반 다중 조회는 URL 길이 제한을 피하도록 결정적 청크와 paged read를 함께 사용한다.
- research의 event·feature·label 파생물은 local `ResearchStore`가 소유하며,
  `trading`·`execution` Supabase 테이블을 연구 산출물 저장소로 사용하지 않는다.
- canonical owner와 폐기한 런타임·테스트 경로의 존재 여부를 레이아웃 회귀 검사로 고정한다.
- reporting 모델과 dashboard cache, notification renderer는 각 owner에 하나만 두며 중복 parity 구현은 유지하지 않는다.
- historical fundamentals 조회는 공시일뿐 아니라 `financial_versions.ingested_at`와
  `filings.available_at`도 cutoff로 적용해 미래 적재 데이터 누출을 막는다.
- `reporting.earnings_surprise`는 발표일과 같은 날의 estimate를 제외하고
  `snapshot_date < filing_date`인 관측치만 발표 전 컨센서스로 결합한다.
- 후보 랭킹의 세그먼트 신호는 현재 CIK의 `filing_date`와
  `filing_processing.updated_at`를 cutoff로 적용한 `fundamentals.segment_metrics`
  PIT snapshot에서 계산하며, 전체 회사 조회나 빈 placeholder 반환을 사용하지 않는다.
- reporting view가 read-time 계산되는 canonical 구조이므로 materialized-view refresh
  호환 hook은 존재하지 않는다.
- Dashboard 가격·전략 재현은 `market.prices_daily` 저장 행만 읽고, 진행 중인 달은
  월말 종가로 만들지 않는다. yfinance 가격 호출과 전략 source 직접 의존성은 없다.
- Dashboard 뉴스는 `reporting.news` 계약만 소비하고, provider 호출·메타데이터 정규화는
  `data.news`가 소유한다. 하네스 상태 읽기는 `dashboard.ops`에, 캐시와 provider 사용량
  원장은 `platform`에 둔다.

## 적용 상태

2026-09-08: 빈 Supabase(`gbpopgppaqvceugjtypt`)에 `db_bootstrap.py apply`로 v1 선언
전체를 한 트랜잭션에 세웠다 — 표 24, view 15, function 5. 데이터는 아직 없다.

**남은 수동 단계 하나**: PostgREST 노출 목록이 아직 `public, graphql_public`이라
Data API가 여섯 스키마를 서빙하지 않는다. Supabase 대시보드에서
`universe, market, fundamentals, macro, institutional, reporting`을 추가해야 한다.
반대로 **목록에 없는 스키마를 먼저 넣으면 Data API 전체가 503**이 되므로 순서를 지킨다
(스키마를 먼저 만들고, 그다음 목록에 넣는다).

## 아직 실행하지 않은 것

다음 작업은 코드와 오프라인 검증만으로 진행한다. 아래 작업은 별도 실행 단계에서만 한다.

- 외부 API 재수집
- Discord 실제 발송·관리 API 동기화
- broker·실거래·live execution 검증

현재 작업 트리는 이미 사용자 변경을 포함하므로 reset·checkout으로 정리하지 않는다.

## 현재 실행 계약의 보강

- 하네스·CLI 기본 위치는 `operations/paths.py`의 저장소 루트와 상태 디렉터리를 공유한다.
- 실제 위험 판정은 `trading/risk/gate.py`의 `DeterministicRiskGate` 하나다.
- 주문 원장은 `security_id`를 저장하고 `ticker`는 승인 당시의 불변 요청 표기로 보존한다.
- reporting view는 `security_invoker = true`로 원천 권한·RLS를 따른다.
- 공통 페이지 조회는 정렬키와 1~1,000행 page_size 계약을 공유한다.
- 전년 재무 비교는 정확한 전년도 fiscal_period를 요구한다.
- 전략 알림은 유한 배치 snapshot만 순회한다. 실패·불명 결과를 발송 완료로 바꾸지 않는다.
- Research Actions 산출물 전달과 로컬 운용 차이는 [OPERATIONS.md](OPERATIONS.md)의 Research 절을 따른다.
- 테이블별 정적 쿼리 계약과 주문 identity·기본 경로·재무 비교·읽기 전용 DuckDB 회귀 검증을 포함한다.

`db/postgres/v1/`이 DB 구조의 기준이다. 원격 업무 스키마 설치나 ETL·Discord·broker 실행까지
검증한 상태는 아니다. 현재 작업 중 정비 보류는 유지하며 Live 스위치는 변경하지 않았다.

## 2026-09-07 storage foundation 전환

- PostgreSQL 선언 경로를 `db/postgres/v1/`로 통일했다.
- Intelligence, Research, Runtime, 로컬 artifact의 기본 경로를 `data/local/<store>/` 아래로
  모으고 기존 개별 환경변수 우선순위를 유지했다.
- Research DuckDB와 Runtime SQLite 선언을 `db/duckdb/research/v1/`,
  `db/sqlite/runtime/v1/`의 책임별 SQL로 분리했다.
- legacy 로컬 DB 세 개를 canonical 경로로 복사하고 schema, 행 수, hash를 검증했다.
  원본은 보존했으며 검증 manifest도 로컬 artifact에 남겼다.
- Supabase 원격 환경에는 아직 어떤 schema 변경도 적용하지 않았다.
- storage 집중 테스트 32개와 수정 회귀 테스트 15개가 통과했다. 전체 오프라인 테스트는
  2,373개 중 10 failures, 0 errors이며 storage foundation과 `src/` 구조 정리에서 새로
  생긴 실패는 없다.
- Runtime maintenance hold는 유지한다. Graphify는 최종 통합 단계에서 사용자가 갱신한다.
