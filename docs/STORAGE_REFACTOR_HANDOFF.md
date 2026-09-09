# 저장 계층 개편 — 인계 메모

작성 시점: 2026-09-06

## 새 세션 시작 지시문

새 세션에는 아래 문장을 그대로 전달한다.

> 저장 계층 전면 개편을 계속한다. 먼저 `AGENTS.md`, `CLAUDE.md`,
> `docs/STORAGE_REFACTOR_HANDOFF.md`를 읽고 현재 working tree를 유지한 채 이어서
> 작업한다. 기존 변경을 reset하거나 되돌리지 않는다. maintenance mode는 작업이
> 끝나고 전체 오프라인 테스트가 통과할 때까지 유지한다. 남은 테스트를 새 저장 계약에
> 맞게 고치되, 테스트를 통과시키려고 삭제한 Supabase trading/execution/notifications
> 스키마나 과거 버전 저장을 복원하지 않는다.

## 확정된 저장 경계

- Supabase/PostgreSQL은 `universe`, `market`, `fundamentals`, `macro`,
  `institutional`과 ordinary `reporting` view만 소유한다.
- Market 일봉은 `integer security_id`, `double precision OHLC`, `bigint volume`,
  `is_repaired`만 저장한다. 행별 provider와 `ingested_at`은 저장하지 않는다.
- Fundamentals는 공시 provenance를 보존하되 기간별 canonical `financials` 한 행만
  유지한다. 숫자의 정정 전 버전은 복원하지 않는다.
- Macro 시장 관측은 현재값 테이블, 경제 발표만 full vintage 테이블을 사용한다.
- Institutional DB에는 SEC 사실만 저장하고 화면 해석은 코드 설정이 소유한다.
- News/Social 본문은 날짜 partition ZSTD Parquet가 소유하고 DuckDB는 작은 catalog와
  분석 metadata 및 view만 소유한다.
- Research feature와 학습용 대용량 행은 연도 partition ZSTD Parquet가 소유한다.
  DuckDB는 전략 배분과 `feature_sets`/`dataset_runs` metadata만 소유한다.
- 판단·승인·주문·체결·대사·알림 중복 방지·로컬 job 상태는
  `data/local/runtime/runtime.sqlite3`가 소유한다.

## 현재 working tree에서 완료한 내용

### PostgreSQL DDL과 canonical writer

- `security_id`를 `integer`로 줄이고 JSON membership을 기간형
  `universe.index_memberships`로 교체했다.
- `market.prices_daily`에서 `source`와 `ingested_at`을 제거하고 `is_repaired`를
  사용하도록 writer와 Dashboard 가격 reader를 바꿨다.
- `fundamentals.financials` 사용을 canonical `financials`로 바꾸고 filing
  accession 및 filing date provenance를 연결했다. `FY` fiscal period도 허용한다.
- Macro catalog seed를 실제 collector source 목록에서 만들며, 정상 writer 진입점이
  catalog를 먼저 seed하도록 바꿨다.
- 시장 macro 관측과 경제 vintage를 분리하고 release event의 중복 actual 컬럼을
  제거했다.
- Institutional manager/position DDL을 사실 컬럼만 남기도록 줄였다.
- Reporting view의 manager 컬럼 모호성, identifier 대소문자 및 유효기간 경계를
  수정했다.

### 로컬 Runtime

- Trading repository를 SQLite 관계형 판단 원장에 연결했다.
- 비어 있는 구형 execution 표를 교체할 때 SQLite 전역 index 이름이 남는 rename
  문제를 제거했다. 데이터가 있는 구형 원장은 자동 변환하지 않고
  `RuntimeMigrationRequired`로 중단한다.
- 주문 상태 전이를 검증하고 terminal 상태 및 broker order identity를 불변으로
  만들었다.
- Broker raw response는 내용 주소 artifact 파일로 저장하고 SQLite에는 경로와 SHA-256만
  둔다.
- `account_daily_snapshots`를 갱신하고 상세 operational account snapshot은 이틀로
  제한한다.
- Dashboard와 알림 reader의 remote trading/execution/notifications 직접 조회를
  대부분 로컬 런타임 뷰(`reporting/readers/runtime.py`의 `LOCAL_VIEWS`)와 로컬 outbox로
  전환했다.

### Research와 Intelligence

- Intelligence news/social 본문은 날짜 partition Parquet, DuckDB는 metadata/view라는
  경계를 구현했다.
- `ResearchStore`의 technical feature를
  `parquet/features/technical_v1/year=YYYY/data.parquet`로 옮겼다.
- 범용 `research_records`를
  `parquet/datasets/<dataset>/year=YYYY/data.parquet`로 옮겼다.
- Parquet은 ZSTD를 사용하고 같은 디렉터리의 임시 파일을 `os.replace`하여 교체한다.
- 기존 DuckDB `feature_signals_daily`와 `research_records`가 있으면 첫 writable open에서
  Parquet로 옮긴 뒤 구형 표를 삭제한다.
- 전략 비중은 `strategy_runs`와 `strategy_allocations` 관계형 행으로 유지하며 알림
  상태를 Research DB에 쓰지 않는다.

## Storage foundation 전환 결과

- PostgreSQL 선언 루트는 `db/postgres/v1/` 하나로 통일했다.
- 로컬 기본 경로는 `data/local/intelligence/`, `data/local/research/`,
  `data/local/runtime/`, `data/local/artifacts/`로 묶었다. 기존 store별 환경변수는 계속
  새 기본값보다 우선한다.
- Research DuckDB DDL은 `db/duckdb/research/v1/` SQL 파일로 분리했다.
- Runtime SQLite DDL은 account, decision, execution, notification 책임별 파일로 나눴다.
- legacy Intelligence·Research DuckDB와 Runtime SQLite를 canonical 경로에 복사하고
  schema, 행 수, hash를 검증했다. 원본 파일은 삭제하지 않았다.
- 검증 manifest는
  `data/local/artifacts/storage-migration/20260907T063825.548115Z.json`에 있다.
- Supabase 원격 DB에는 DDL, reset, migration을 적용하지 않았다.
- Runtime maintenance hold는 계속 활성 상태다.

## `src/` 패키지 구조 정리 결과

- Data의 한 파일짜리 `models/`, `services/`, `market_state/` 래퍼를 제거하고 각 책임의
  `domain/` 또는 `application/` 바로 아래로 모았다.
- Macro command를 `data/macro/commands/`로 모으고, Macro가 Market repository를 직접
  참조하던 경계를 `infrastructure/sources/market.py` reader로 분리했다.
- Reporting의 `readers/intelligence`, `econ_calendar`, `fundamentals`, `strategy` 단일 파일
  래퍼를 역할 이름이 드러나는 top-level 모듈로 옮겼다.
- Research의 단일 `ml/inference.py` 래퍼는 `research/ml_inference.py`로 이동했다.
- provider `sources/`, broker, notification 종류별 package, Macro release처럼 독립된
  interface와 확장 방향이 있는 경계는 유지했다.
- 모든 source, test, Dashboard, notification import를 새 경로로 갱신했다.

## 현재 검증 결과

- storage foundation 집중 테스트 32개: 통과
- 수정 회귀 테스트 15개: 통과
- `python -m compileall -q src scripts`: 통과
- `git diff --check`: 통과
- 전체 오프라인 테스트: 2,373개 실행, 10 failures, 0 errors

남은 10건은 Market PIT의 이전 `ingested_at` 계약, Reporting guard의 multiline SELECT
판정, 이전 table 수·retention·Macro seed 계약, 공개 정책 문서 부재 등 기존 기준선이다.
storage foundation과 `src/` 구조 정리에서 새로 생긴 failure나 error는 없다. Graphify
갱신은 사용자 요청에 따라 최종 통합 단계로 넘겼다.

## 다음 작업 순서

1. **실제 코드 결함부터 닫기**
   - `dashboard.db`가 `data.institutional.managers`를 직접 import해 presentation dependency
     guard를 깨는 문제를 reporting 전용 presentation adapter로 옮긴다.
   - `LOCAL_VIEWS`의 모든 view를 임시 SQLite fixture로 통합 검증한다.
   - account daily snapshot writer/reader, order event, fill, notification outbox를 실제
     SQLite로 검증한다.
   - `ResearchStore` Parquet 동시 writer, record가 다른 연도 partition으로 이동하는
     경우, legacy migration의 멱등성을 단위 테스트로 고정한다.
2. **테스트 계약을 새 구조로 교체**
   - `tests/investment_agent/test_reporting.py`는 remote view와 local view fixture를 나눠
     검증한다.
   - Dashboard execution/account/target 테스트를 fake Supabase가 아니라 temp
     `runtime.sqlite3`로 바꾼다.
   - execution/trading/notification SQL schema 테스트는
     `db/sqlite/runtime/v1/*.sql`을 검사하게 바꾼다.
   - Universe JSON membership 테스트를 interval membership과 원자 replace RPC 계약으로
     바꾼다.
   - Fundamentals version 복원 테스트를 canonical overwrite + filing provenance의
     의도적 한계 계약으로 바꾼다.
   - Market PIT ingestion 테스트를 trade-date 계약과 change manifest 테스트로 바꾼다.
   - Macro 테스트 fixture를 `series_key`, `market_observations`,
     `economic_observation_versions` 구조로 바꾼다.
   - Institutional manager 해석/SEC raw extra-column 기대를 코드 presentation + compact
     fact 계약으로 바꾼다.
3. **소스 잔재 정리**
   - `rg -n "financial_versions|notifications\.outbox|SCHEMA_TRADING|SCHEMA_EXECUTION|ingested_at"`
     결과를 문맥별로 확인한다. Macro vintage, share/segment ingestion time처럼 유지할
     값과 삭제한 이름을 구분한다.
   - `execution/db.py`의 사용하지 않는 과거 Supabase 상수·import를 제거한다.
   - DuckDB store의 구형 `collection_runs`/본문 테이블 테스트를 새 catalog 계약으로
     바꾼다.
4. **문서와 운영 계약 갱신**
   - `README.md`, `CLAUDE.md`, `docs/DATA.md`, `docs/OPERATIONS.md`, domain README에서
     `financial_versions`, remote execution/trading/notifications, DuckDB 본문 중복 저장
     설명을 모두 새 경계로 바꾼다.
   - Supabase 정상 목표 350–400MB와 공간 부족 시 제거 순서를 문서화한다.
   - 의도적 한계인 “정정 전 fundamental 숫자는 완전 재현하지 않음”을 backtest 계약에
     명시한다.
5. **최종 검증**
   - `python -m unittest discover -s tests -t .`
   - `graphify update .`
   - `git diff --check`
   - 모든 테스트 통과 후에만 maintenance mode 해제를 검토한다.

## 주의할 점

- 다른 세션이 `research/`와 `trading/`을 동시에 정리할 수 있으므로 해당 경로의 변경을
  reset하거나 한 커밋에 섞지 않는다.
- 테스트 통과를 위해 삭제한 원격 schema를 되살리지 않는다.
- `LIVE_ENABLED`와 `TOSS_LIVE_ENABLED`는 코드가 자동 변경하면 안 된다.
- Full integration ETL은 외부 네트워크와 Chromium이 필요하다. 우선 오프라인 단위
  테스트로 검증한다.
- 기준선에서도 공개 정책 문서 부재 등 일부 실패가 있었지만, 최종 작업에서는 전체
  결과를 다시 확인하고 이번 변경에서 늘어난 실패를 모두 제거한다.
