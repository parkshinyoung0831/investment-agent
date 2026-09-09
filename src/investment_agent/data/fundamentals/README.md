# Fundamentals — 공시·재무·세그먼트·실적 이벤트

fundamentals 도메인은 SEC 공시를 기준으로 기업 재무·세그먼트·실적 이벤트와
시장 예상치의 수집, 정규화, 시점 정합 조회를 소유한다. 정식 실행 경로는
`investment_agent.data.fundamentals`이며 DB 기준은 `db/postgres/v1/30_fundamentals.sql`과
`db/postgres/v1/90_reporting.sql`이다.

## 소유 구조

```text
fundamentals/
├── domain/                         순수 정규화·기간·품질 규칙
├── application/                    persistence builder, source/repository protocol,
│                                    collect -> transform -> write orchestration (평탄 구조)
├── infrastructure/
│   ├── sec/                        SEC source adapter
│   ├── yahoo_finance/               estimate/earnings source adapter
│   └── supabase/                    canonical v1 reader/writer
├── commands/                       Actions와 수동 실행 진입점
├── companyfacts.py                  SEC companyfacts 변환 경계
└── repository.py                    application-facing storage adapter
```

Supabase query builder는 `infrastructure/supabase/`와 공용
`investment_agent.platform.db`에만 둔다. 다른 도메인은 fundamentals 내부 구현을
직접 import하지 않고 public application port 또는 reporting read model을 사용한다.

## canonical 저장 모델

| 목적 | canonical 객체 | identity / grain |
|---|---|---|
| 공시 provenance | `fundamentals.filings` | `accession_no` |
| 처리 상태 | `fundamentals.filing_processing` | accession · content type · mapping version |
| 기업 전체 재무 | `fundamentals.financials` | CIK · period end · accession |
| 클래스별 발행주식수 | `fundamentals.share_class_snapshots` | CIK · class · as-of date · accession |
| 세그먼트 지표 | `fundamentals.segment_metrics` | CIK · accession · fiscal period · segment hash |
| 실적 결과 | `fundamentals.earnings_results` | security · fiscal period · accession |
| 예상치 | `fundamentals.earnings_estimates` | security · snapshot · horizon · source |
| 발표 일정 | `fundamentals.earnings_schedule_versions` | security · fiscal period · snapshot · source |
| 애널리스트 스냅샷 | `fundamentals.analyst_consensus_snapshots` | security · snapshot date · source |

### 스냅샷 보존

예상치·발표 일정·애널리스트 커버리지는 매일 한 행씩 쌓인다. **발표 전에는 그 누적
자체가 값이지만(예정일이 밀린 것, 컨센서스가 움직인 것), 발표가 끝나면 계속 읽히는
것은 하나뿐이다** — `reporting.earnings_surprise`가 집는 "발표일 직전 마지막
스냅샷"이다.

그래서 지우는 기준은 나이가 아니라 발표 여부다. `fundamentals.prune_expectation_snapshots()`가
발표가 끝난 기간만, 그것도 최근 180일 밖의 것만 그 한 건씩 남기고 정리한다
(`refresh_expectations`가 적재 성공 회차에만 호출한다). 나이로만 자르면 아직 발표
안 한 분기의 드리프트가 먼저 사라지고, 반대로 오래된 분기의 매일치가 그대로 남는다.

기업 재무는 ticker가 아니라 CIK와 accession을 저장 identity로 사용한다. ticker와 CIK
승계는 `universe`에서 읽어 fan-out하고, 표시용 reporting view가 이를 투영한다.
동일 기간의 정정 공시는 기존 값을 덮어쓰지 않고 별도 `financial_versions` 행으로
보존한다.

## 읽기 규칙

- 최신 화면은 `reporting.*` view 또는 해당 도메인의 paged reader를 사용한다.
- historical replay와 trading evidence는 `filed_at`/`available_at`와
  `financial_versions.ingested_at`를 cutoff에 적용한다.
- 대량 조회는 `select_all_paged()`와 안정적인 primary-key order를 사용한다.
- 계산 가능한 TTM·margin·surprise·valuation은 원장 행을 application/reporting에서
  계산하며 별도 materialized-view refresh 계약을 두지 않는다.
- 공시·처리 상태·재무 행의 부모 순서를 지킨다. `filings`가 먼저 존재해야
  `filing_processing`, `financial_versions`, `segment_metrics`를 기록할 수 있다.

## 실행 진입점

- `commands.sync_filings`: 최근 SEC filings와 companyfacts 동기화
- `commands.backfill_history`: 명시적 기간 백필
- `commands.refresh_earnings_events`: 8-K 실적 이벤트 갱신
- `commands.refresh_expectations`: 예상치와 analyst snapshot 갱신
- `commands.common_shares`: 클래스별 발행주식수 갱신
- `commands.verify_integrity`: canonical 원장 정합성 점검
- `operations.commands.watch_earnings`: 발표 세션 감시

모든 command는 provider 오류를 데이터 적재 결과와 분리해 기록하며, 외부 연결 없는
검증에서는 source adapter를 mock한 unit test만 실행한다.
