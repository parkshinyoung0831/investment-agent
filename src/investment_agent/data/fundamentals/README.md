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
| 예상치 | `fundamentals.earnings_estimates` | security · fiscal period · source · 수집 성격 · 상태 시작일 |
| 발표 일정 | `fundamentals.earnings_schedule_versions` | security · fiscal period · source · 상태 시작일 |
| 애널리스트 스냅샷 | `fundamentals.analyst_consensus_snapshots` | security · source · 상태 시작일 |

### 예상치·일정은 바뀔 때만 새 행이다

예상치·발표 일정·애널리스트 커버리지는 직전 저장 상태와 다를 때만 새 행을 쓰고, 같으면
그 행의 `last_seen_at`만 옮긴다(`domain/services/state_versions.py`). 인접 비교라서 값이
A→B→A로 돌아온 사건은 세 행으로 남고, "값이 안 바뀜"과 "수집이 멈춤"은 `last_seen_at`으로
가른다. 반복 행이 없으므로 보존 기간으로 지우는 정리도 없다 — 발표 전 예상 이력은 다시 받을
수 없다.

`snapshot_kind`는 자료가 당시 값임을 얼마나 보장하는지 말한다.

| 값 | 뜻 | 발표 서프라이즈에 쓰나 |
|---|---|---|
| `captured_live` | 그날 우리가 직접 수집 | 쓴다 |
| `vendor_pit` | 공급자가 당시 값임을 보장한 과거 자료 | 쓴다 |
| `reconstructed` | 현재 API의 발표 이력에서 되살린 값 | 쓰지 않는다 |
| `latest_history` | 당시 값 보장이 없는 과거 요약 | 쓰지 않는다 |

backfill 명령으로 받았다는 이유로 과거 시점 신뢰도가 생기지 않는다. 표지는 명령이 아니라
원천의 보장으로 정한다.

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
