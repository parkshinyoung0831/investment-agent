# 저장 계층·스키마 축소 설계 — 2026-09-07 기록

> 상태: 구현 승인됨 (2026-09-07 개정: 코드 디렉터리 평탄화 추가). 이 문서는 저장소
> 파일과 오프라인 검증의 구현 계약이다. 실제 Supabase reset·DDL 적용과 로컬 원장
> 데이터 폐기는 이 작업에 포함하지 않는다. 코드 디렉터리 평탄화(2.1절)는 설계만
> 확정하며, 실제 파일 이동·import 수정은 별도 단계에서 진행한다.

## 1. 목표

`src/investment_agent/`의 디렉터리 구조는 유지하면서 저장 책임을 다음 다섯 곳으로
명확히 나눈다.

| 저장소 | 책임 |
|---|---|
| Supabase/PostgreSQL | 장기 보존할 canonical 금융 사실 |
| Parquet | 뉴스·소셜 원문과 Research 대용량 행 |
| DuckDB | Intelligence·Research의 작은 catalog와 분석 metadata |
| Runtime SQLite | 프로그램 상태, 판단·승인·주문·체결·대사·알림 중복 방지 |
| TOML config | 추적 대상과 provider·알림·매매 정책 설정 |

판단 기준은 다음과 같다.

1. 외부에서 발생한 장기 금융 사실은 Supabase 후보다.
2. 대용량 원본은 Parquet에 둔다.
3. 연구 과정에서 만든 대용량 데이터는 Research Parquet에 둔다.
4. 프로그램의 현재 상태와 실제 실행 원장은 Runtime SQLite에 둔다.
5. 화면을 위한 계산은 Reporting view 또는 Python read model에서 만든다.
6. 운영자가 정한 값은 config에 둔다.
7. 로그와 디버깅 자료는 log 또는 artifact에 둔다.

작은 상태 테이블을 줄이는 것보다 반복 snapshot, raw payload, 파생 행, 중복 index를
먼저 줄인다. PK와 UNIQUE가 만드는 index를 고려해 추가 index는 실제 조회 계약에 필요한
것만 선언한다.

## 2. 최종 디렉터리

```text
config/
  app.toml
  data/
    universe.toml
    tracked.toml
    market.toml
    fundamentals.toml
    macro.toml
    institutional.toml
  trading/
    decision.toml
    portfolio.toml
    risk.toml
    execution.toml
  notifications/
    discord.toml

db/
  postgres/v1/
    00_extensions.sql
    10_universe.sql
    20_market.sql
    30_fundamentals.sql
    40_macro.sql
    50_institutional.sql
    90_reporting.sql
  duckdb/
    intelligence/v1/
      00_init.sql
      10_content.sql
      20_mentions.sql
      30_signals.sql
      90_views.sql
    research/v1/
      00_init.sql
      10_datasets.sql
      20_experiments.sql
      30_models.sql
      40_backtests.sql
      90_views.sql
  sqlite/runtime/v1/
    00_init.sql
    10_account.sql
    20_decisions.sql
    30_execution.sql
    40_notifications.sql

data/local/
  intelligence/
    intelligence.duckdb
    parquet/news/date=YYYY-MM-DD/*.parquet
    parquet/social/date=YYYY-MM-DD/*.parquet
  research/
    research.duckdb
    parquet/datasets/
    parquet/features/
    parquet/labels/
    parquet/backtests/
  runtime/
    runtime.sqlite3
  artifacts/
    models/
    evidence/
    broker/
    reports/
```

`db/postgres/v1/`이 Supabase 선언의 유일한 기준이다. `db/v1/` 호환 사본은 두지 않는다.
모든 스크립트·테스트·문서 참조를 한 변경 묶음에서 새 경로로 바꾼다.

빈 config 파일을 미리 만들지 않는다. 각 파일은 실제 소비자를 새 config loader로
전환하는 단계에서 유효한 기본값과 함께 추가한다. 비밀값은 계속 `.env`와 GitHub
Secrets에 두며 TOML에 쓰지 않는다.

### 2.1 코드 디렉터리 평탄화

`src/investment_agent/` 아래 각 도메인의 최상위 책임 폴더(`domain/`, `application/`,
`infrastructure/`, `commands/` 등)는 그대로 둔다. 다만 그 안에서 파일 하나로 표현될
수 있는 역할을 다시 하위 폴더로 쪼갠 곳은 한 단계 합친다.

- 대상 판단 기준은 "하위 폴더 안에 파일이 소수(대략 5개 이하)이고 각 파일이 이미
  이름으로 역할을 설명하는가"이다. 이 조건을 만족하면 하위 폴더를 없애고 파일을
  상위 폴더로 올린다. 파일 수가 많거나 하위 폴더 자체가 별도 개념 경계(예:
  `infrastructure/sources/`처럼 provider별로 계속 늘어나는 폴더)라면 유지한다.
- 예시: `data/fundamentals/application/{builders,ports,use_cases}/*.py`는
  `data/fundamentals/application/*.py`로 합친다. 파일명은 유지한다
  (`builders/earnings_estimates.py` → `application/earnings_estimates.py`).
- 이 원칙은 fundamentals에 국한하지 않고 저장소 전체에 적용한다. 실제 대상 목록은
  구현 단계에서 위 기준으로 각 패키지를 훑어 정한다(브레인스토밍이나 별도 승인
  없이, 기준을 기계적으로 적용).
- 도메인 최상위 폴더 이름과 개수, 도메인 간 경계(`data/`, `research/`, `trading/`,
  `execution/`, `notifications/`, `platform/` 등)는 바꾸지 않는다. 평탄화는 각
  도메인 내부의 불필요한 깊이만 없앤다.
- 파일을 옮길 때는 같은 변경 묶음 안에서 해당 패키지의 모든 import와 테스트 경로를
  함께 고친다. `git mv`로 이력을 보존한다.

> **2026-09-07 구조 감사 완료.** 이 규칙으로 얕은 `trading/evidence/dossier/`는
> `trading/evidence/`로 합쳤다. 반면 `trading/decision/desks/`는 market,
> fundamental, macro, event라는 독립 analyst 역할의 경계이므로 유지한다.
> `data/intelligence`, `data/news`, `data/social`도 각각 로컬 Intelligence 저장소,
> 뉴스 수집, 소셜 수집을 소유하는 data 도메인이며, top-level 이름만 맞추려고 세
> 패키지를 합치면 repository·수집 명령·provider 계약을 한 모듈에 섞게 된다. 따라서
> 최종 트리의 `intelligence`는 이 세 collection 경계를 포괄하는 논리 영역으로
> 해석하고, 실제 Python 도메인 경계는 유지한다. provider별 `sources/`와 macro의
> `domain/releases/`, `infrastructure/releases/`도 확장 가능한 provider 또는 별도
> release 시간 계약을 나타내므로 평탄화 대상이 아니다.

## 3. PostgreSQL 계약

### 3.1 Universe

> 2026-09-07 개정: 아래 세 항목(`entity_successions` 삭제, `watchlist_members`
> 삭제, `index_memberships.source_hash` 제거)은 실제 소비자 조사 결과 취소한다.
> `is_tracked`와 `watchlist_members`는 서로 다른 질문에 답한다 —
> `is_tracked`는 "데이터를 수집하는가", `watchlist_members`는 "실적 알림을
> 언제부터 보내는가"다. `watch_from`은
> `notifications/earnings_flash/candidates.py`와
> `notifications/earnings_report/candidates.py`가 실제 컷오프로 쓰고 있어,
> 없애면 새로 tracked된 종목의 과거 실적 이벤트가 한꺼번에 알림으로
> 나간다(README가 명시적으로 경고하는 실패 모드). `sources[]`도 "매도해도
> 수동 등록은 유지"하는 안전장치라 boolean 하나로 표현할 수 없다.
> `entity_successions`는 비어 있지만
> `data/fundamentals/infrastructure/supabase/company_financials.py`가 실제로
> 읽어 CIK 승계 재무 연속성을 잇는다. `index_memberships.source_hash`는
> `refresh_universe.py`가 같은 스냅샷 재적용 시 중복 쓰기를 막는 데 쓴다.
> 이 셋을 없애려면 각각 별도 조사·이관 계획이 필요하고, storage 경로 이전과
> 같은 변경 묶음에서 기계적으로 지울 대상이 아니다. Universe는 v1 스키마를
> 그대로 유지한다(`entities`, `entity_successions`, `securities`,
> `security_identifiers`, `index_memberships`, `watchlist_members` 여섯 개).

기본 index는 PK/UNIQUE와 `securities(cik)`,
`index_memberships(index_code, valid_from, valid_to)`다. 상태·갱신시각용 index는 만들지
않는다.

### 3.2 Market

`prices_daily`, `split_events`, `dividend_events` 세 테이블을 유지한다.

- `prices_daily`는 `security_id`, `trade_date`, OHLC, `volume`, `is_repaired`만 저장한다.
- 조정가·수익률·RSI·MACD·이동평균 등 파생값은 저장하지 않는다.
- PK `(security_id, trade_date)`와 횡단면 조회용 `(trade_date, security_id)`만 기본
  index로 둔다.
- split/dividend 날짜 index는 제거한다. 대표 조회가 느리다는 측정이 생기면 추가한다.
- 변경 전파는 `data/local/market_change_manifest.json`의 후속 경로를
  `data/local/artifacts/` 계약에 맞춰 옮기고 manifest 누락 시 보수적으로 재계산한다.

### 3.3 Fundamentals

최종 테이블은 다음 여덟 개다.

```text
filings
financials
shares_outstanding
segment_metrics
earnings_results
earnings_estimates
earnings_calendar
analyst_consensus
```

- `financials`는 `(cik, period_end, fiscal_period)`당 canonical 한 행이다. 정정공시가
  들어오면 공식 공시 순서와 품질 규칙으로 현재 행을 교체한다.
- 정정 전 숫자의 완전한 PIT 재현은 지원하지 않는다. 정정값을 최초 공시 시점으로
  소급하지 않고, 당시 값을 보존하지 않았다면 historical reader는 결측을 반환한다.
- `filing_processing`은 제거한다. 재처리에 필요한 최소 `mapping_version`과
  `processed_at`은 `filings`에 둔다. count·상세 상태·오류는 runtime job state와
  artifact가 소유한다.
- `share_class_snapshots`는 확정된 `security_id`, `as_of_date`,
  `shares_outstanding`, `accession_no`만 갖는 `shares_outstanding`으로 바꾼다. 미확정
  class mapping은 canonical DB에 넣지 않고 artifact/error report에 둔다.
- `segment_metrics`는 canonical 사업 의미만 저장한다. 기간·CIK·segment 종류와 이름,
  핵심 수치, accession을 보존하고 parser axis/member/debug 필드는 artifact로 옮긴다.
  같은 기간의 segment 집합은 transaction으로 전체 교체한다.
- `earnings_estimates`, `earnings_calendar`, `analyst_consensus`는 current row를 upsert한다.
  변천 이력은 필요할 때 Research Parquet에 보존한다.
- `earnings_results`는 실제 발표 사건의 canonical 결과를 유지한다.

기본 index는 각 PK와 `filings(cik, filing_date DESC)`다. PK 선두와 중복되는 기간 index,
status/source/updated_at index는 만들지 않는다.

### 3.4 Macro

최종 테이블은 `series`, `market_observations`, `economic_observations`,
`release_calendar`, `forecasts` 다섯 개다.

- `sources`와 `measures`를 제거하고 해석 metadata를 `series`에 합친다.
- level/YoY/MoM처럼 의미가 다른 값은 각각 명시적인 `series_code`를 가진다.
- `market_observations`는 `(series_id, observation_date)` 현재 관측이다.
- `economic_observations`는 provider가 실제로 제공하는 공개 revision만 보존한다.
- release 일정과 forecast는 Cloud에서 current row만 유지하고 과거 snapshot은 Research
  Parquet로 보낸다.
- forecast 종류, 단위, timezone, 공개 시각 정밀도처럼 계산 의미에 필요한 값은
  `series` 또는 fact에 남긴다.

> **2026-09-07 부분 완료, 나머지는 보류.** 실사용 조사 결과 이 절의 축소안 중
> `economic_observation_versions` → `economic_observations` **이름만 바꾸는 것**만
> 다른 설계와 충돌 없이 안전했다. 나머지는 보류한다:
> - `release_events`/`release_schedule_versions` → `release_calendar`(current row만
>   유지) 안은 `releases/db.py`의 `_summary_rows`/`due_releases()`가 `collected_at
>   <= as_of`로 **과거 스냅샷 전체**를 필터링해 "그 시점에 알려진 일정"을 재구성하는
>   것과 직접 충돌한다. 이 as-of 재구성이 발표창 watcher(`due_releases`, 로컬 하네스
>   1분 주기)를 구동한다 — Postgres 밖으로 이력을 빼려면 그 재구성 로직을 먼저
>   Parquet 기반으로 다시 설계해야 하는데, 이는 이번 세션 범위를 넘는다.
> - `forecast_snapshots` → `forecasts`(current row만) 안은 명시적 NULL 철회를 포함한
>   forecast 전환을 보존하는 현재 PIT 계약과 정면으로 충돌한다. 이력을 제거하면
>   as-of 재구성이 불가능해지므로 이 세션에서 구현하지 않았다.
> - `sources`/`measures` → `series` 통합은 그 자체로는 다른 문서와 충돌하지 않지만,
>   `measures`는 30개 series에 46개 measure(레벨/MoM/YoY 등)로 걸쳐 있고
>   `dashboard/app_pages/econ_calendar.py`, `trading/supabase_repository.py`의
>   evidence 조립, `reporting/queries.py`의 `macro_measures` 뷰까지 소비한다 —
>   institutional의 `managers`보다 훨씬 넓게 퍼져 있어 별도 작업으로 다룬다.
> 결론: macro는 표 개수가 그대로 8개다(`sources`, `series`, `measures`,
> `market_observations`, `economic_observations`, `release_events`,
> `release_schedule_versions`, `forecast_snapshots` — `economic_observations`만
> 이름이 바뀌었다). 나머지 축소는 두 설계 문서의 충돌을 먼저 해소한 뒤 별도로
> 재검토한다.

### 3.5 Institutional

최종 테이블은 `filings`, `positions` 두 개다.

- 추적 manager와 화면 설명은 `config/data/institutional.toml`이 소유한다.
- `filings.manager_cik`는 config에서 검증하지만 별도 manager FK는 두지 않는다.
- 13F 정정·NEW HOLDINGS 사건과 source row identity는 보존한다.
- positions의 기본 추가 index는 `(identifier, identifier_type)`다.
- Reporting이 config와 DB facts를 조립해 이름·분류·설명을 반환한다.

### 3.6 Notifications와 Reporting

> 2026-09-07 완료: PostgreSQL `notifications` schema와 `80_notifications.sql`을
> 삭제했다. 실사용을 확인해보니 `security_id`·`is_enabled`·`active_from` 모두
> 항상 같은 값(global/true/오늘)만 썼으므로, 별도 config 파일을 새로 만드는
> 대신 `notifications/subscriptions.py`의 `KIND_ENV` 상수(kind → 환경변수 이름)로
> 대체했다. 각 알림 워크플로가 자기 kind에 필요한 `DISCORD_CHANNEL_*` 시크릿을
> 직접 env에 선언하고, `discord_targets(kind, config=...)`가 그 값을 읽는다.
> `config/notifications/discord.toml`은 만들지 않는다 — 이미 GitHub Secrets가
> 그 역할을 하고 있어 파일을 하나 더 두면 두 SSOT가 생긴다.

- 전송 선점·재시도·message identity는 Runtime SQLite가 소유한다(변경 없음).
- `90_reporting.sql`에는 다섯 금융 schema만 읽는 ordinary view를 둔다.
- DuckDB·SQLite와 config의 결합은 Python Reporting reader가 담당한다.
- Materialized view는 기본으로 사용하지 않는다.
- Dashboard는 공개 Reporting read model만 소비한다.

## 4. DuckDB·Parquet 계약

### 4.1 Intelligence

뉴스와 소셜 본문은 ZSTD Parquet에 한 번만 저장한다. DuckDB에는 `content_index`,
`mentions`, `content_signals`와 게시 manifest를 검증하는 작은 상태만 둔다.

`content_index`는 content identity, kind, source, hash, URL hash, 공개·최초 관측 시각,
partition 위치를 저장한다. `mentions`는 ticker 대신 `cik`/`security_id`를 canonical
identity로 사용하며 실제 매칭 문자열은 별도로 보존한다. 계산 sentiment는 Research가
소유한다.

writer는 staging 파일 작성, schema/행 수/hash 검증, 원자 rename, generation manifest
교체 순서를 따른다. reader는 검증된 현재 generation만 읽는다. 빈 파일 집합과 schema
불일치를 명시적으로 처리한다.

### 4.2 Research

feature matrix, label, dataset row, backtest 상세 행은 Parquet에 둔다. DuckDB에는
`datasets`, `experiments`, `models`, `backtests`와 필요한 view만 둔다.

metadata는 Parquet 경로·hash·행 수·기간·feature/label version·code commit·stage·평가
요약을 저장한다. 모델 바이너리와 evidence는 `data/local/artifacts/`에 두고 DuckDB에는
경로와 hash만 저장한다.

## 5. Runtime SQLite 계약

DDL 파일은 account, decision, execution, notification 책임으로 나누지만 실제 파일은
`data/local/runtime/runtime.sqlite3` 하나다. 주문 안전상 life-cycle이 다른 intent,
approval, attempt, order, fill, reconciliation은 합치지 않는다.

- `account_daily_snapshots`는 `account_snapshots`로 바꾸고 `snapshot_id`, broker/account,
  `execution_mode`, `captured_at`, cash/value/equity/buying power, artifact 경로/hash를 둔다.
- 판단과 portfolio에서 SQL 집계가 필요 없는 작은 가변 payload는 검증된 JSON을 허용한다.
- 승인 hash, 1회 소비, broker 호출 전 attempt reserve, unknown outcome, 재시작 후 대사
  불변식은 유지한다.
- notification outbox와 delivery state는 SQLite transaction으로 선점한다.
- `foreign_keys=ON`, WAL, busy timeout, `synchronous=FULL`을 유지한다.

## 6. 기존 로컬 파일 이전

현재 다음 legacy 파일이 있다.

```text
data/local/intelligence.duckdb
data/local/news_social.duckdb
data/local/runtime.sqlite3
artifacts/research/research.duckdb
```

활성 파일을 바로 덮어쓰거나 삭제하지 않는다. 새 loader는 다음 규칙을 따른다.

1. 새 경로만 있으면 새 파일을 연다.
2. legacy 경로만 있으면 writer lock을 얻고 backup/hash를 만든 뒤 새 경로로 이전한다.
3. 두 경로가 모두 있으면 자동 병합하지 않고 명시적 migration 오류를 낸다.
4. schema·행 수·핵심 hash 검증이 끝난 뒤에만 새 파일을 활성화한다.
5. legacy 파일 삭제는 이 구현 범위에 포함하지 않는다.

> **2026-09-07 정정.** `data/local/news_social.duckdb`는 위 legacy 목록에 잘못
> 들어갔다. 이 파일은 intelligence store의 이전 버전이 아니라
> `trading/evidence/cache.py`(`DEFAULT_CACHE_PATH`,
> `AI_INVESTOR_NEWS_CACHE_PATH`로 재정의 가능)가 소유하는 **재생성 가능한 90일
> 보존 캐시**다 — 코드 주석이 명시한다: "재생성 가능한 DuckDB cache. historical
> replay는 이 파일을 절대 열지 않는다." `intelligence`/`research`/`runtime` 세
> canonical store와 무관하므로 `storage_paths.legacy_candidates()`에 추가하지
> 않는다 — 추가하면 migration 스크립트가 evidence 캐시를 intelligence 데이터로
> 잘못 취급하게 된다. 실제 legacy 대상은 `data/local/intelligence.duckdb`,
> `data/local/runtime.sqlite3`, `artifacts/research/research.duckdb` 세 개뿐이며
> 이 셋은 이미 `legacy_candidates()`에 있고 한 차례 `scripts/migrate_local_storage.py
> apply`로 canonical 경로에 복사·검증됐다(`data/local/artifacts/storage-migration/
> 20260907T063825.548115Z.json`). 다만 그 스크립트는 아직 runtime/intelligence/
> research 연결 코드에 자동으로 연결돼 있지 않다 — 운영자가 수동으로 실행해야
> 5개 규칙이 적용된다. 연결 코드에 자동 배선하는 일은 실행 owner 코드를 건드리는
> 작업이라 별도 변경 묶음에서 maintenance hold를 걸고 진행한다.

Runtime 파일 이전이나 실행 owner 코드를 건드리기 전에는 저장소 규칙대로 maintenance
hold를 건다. `LIVE_ENABLED`, `TOSS_LIVE_ENABLED`, kill switch를 자동 변경하지 않는다.

## 7. 구현 순서

각 단계는 DDL·loader/repository·검증 스크립트·테스트·문서를 함께 바꾸며, 중간 단계도
오프라인 테스트가 실행 가능한 상태를 유지한다.

1. 경로 기반: `db/postgres/v1`, 새 config loader, local path resolver, bootstrap/probe
   스크립트와 경로 계약을 전환한다.
2. Universe + Market: 추적 상태 통합, seed 제거, index 축소, manifest 경로를 전환한다.
3. Intelligence + Research: DDL 파일을 목표 구조로 바꾸고 legacy local file migration을
   구현한다.
4. Runtime: maintenance hold 후 DDL을 재분할하고 account snapshot 및 경로 이전을
   검증한다.
5. Fundamentals: canonical eight-table contract와 current earnings writer/readers를
   전환한다.
6. Macro + Institutional: catalog/config 분리와 compact facts를 전환한다.
7. Notifications + Reporting: PostgreSQL notification schema를 제거하고 config/local
   reader로 완전히 전환한다.
8. 코드 디렉터리 평탄화: 2.1절 기준으로 각 도메인의 얕은 하위 폴더를 합치고 import를
   갱신한다. 저장 계약 전환(1~7단계)이 끝난 뒤, 별도 변경 묶음으로 진행한다.
9. 모든 직접 참조, 문서, prompts, workflows, `.env.example`을 새 계약으로 정리한다.

1~7단계에서는 `src/investment_agent/` 아래 디렉터리를 이동·병합·이름 변경하지 않는다.
새 저장 계약에 필요한 Python 파일 내용과 import만 수정한다. 디렉터리 평탄화는 8단계에서만
한다.

## 8. 검증

- 기존 사용자 변경을 보존한다.
- PostgreSQL DDL은 `pglast` parse와 가능하면 임시 probe로 검증한다. 원격 DB reset은
  실행하지 않는다.
  > 2026-09-07 완료: `scripts/verify_postgres_sql_syntax.py`가 pglast parse를
  > 수행하고 `tests/test_postgres_sql_syntax.py`가 오프라인 회귀에 포함시킨다.
  > 임시 probe는 이미 있던 `scripts/v1_schema_probe.py`가 맡는다(DB 필요).
- DuckDB와 SQLite는 임시 디렉터리에 빈 설치·재실행·legacy 이전·충돌 거부 테스트를
  수행한다.
- Parquet는 ZSTD, partition 경로, schema, 중복 제거, 원자 게시를 검증한다.
- 삭제된 table/schema/path에 대한 직접 참조가 없는지 정적 검사한다.
- 전체 오프라인 회귀는 `python -m unittest discover -s tests -t .`로 실행한다.
- `python -m compileall -q src`, `git diff --check`를 마지막에 실행한다. Graphify 결과 갱신은
  사용자가 최종적으로 수행한다.

현재 기준선은 2,368개 테스트가 모두 통과한 상태다. 완료 판정은 저장 계약 관련 이전
기대가 현재 계약을 검증하도록 교체되고 전체 오프라인 회귀가 통과하는 것이다.

## 9. 범위 밖 작업

- 실제 Supabase schema drop/reset/apply
- legacy 로컬 DB와 artifact의 삭제
- 도메인 최상위 폴더 이름·경계 변경 (2.1절이 다루는 하위 폴더 평탄화는 범위 안이다)
- UI 재설계
- live/paper 매매 활성화
