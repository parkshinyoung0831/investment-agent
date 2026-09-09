# Fundamentals canonical 컬럼 — 이름과 의미

아래 표는 `db/postgres/v1/30_fundamentals.sql`의 현재 저장 계약을 요약한다. 없는 파생 테이블이나
과거 이름을 이 문서에 추가하지 않는다.

## provenance

### `fundamentals.filings`

| column | 의미 |
|---|---|
| `accession_no` | SEC 공시 accession, primary key |
| `cik` | 공시 등록인 |
| `filing_date` | 제출일 |
| `report_date` | 보고 기간 종료일 |
| `form_type` | 10-K, 10-Q, 8-K 등 |
| `available_at` | 시스템이 투자에 사용할 수 있게 된 시각 |
| `source` | 원천 provider |

### `fundamentals.filing_processing`

| column | 의미 |
|---|---|
| `accession_no` | `filings` FK |
| `content_type` | `company`, `segments` 등 처리 대상 |
| `mapping_version` | 정규화 규칙 버전 |
| `status` | pending / parsed / empty / unsupported / failed / superseded |
| `processed_at` | terminal 처리 시각 |
| `row_count` | 저장된 결과 행 수 |

## 재무 원장

### `fundamentals.financials`

grain은 `(cik, period_end, accession_no)`다. 손익·재무상태·현금흐름·EPS 및 업종별
계정을 wide column으로 저장하고, 다음 provenance를 반드시 함께 보존한다.

`cik`, `period_end`, `fiscal_year`, `fiscal_period`, `accession_no`, `form_type`,
`mapping_version`, `filed_at`, `ingested_at`.

`filed_at`은 공시 사실의 시각이고 `ingested_at`은 저장 완료 시각이다. historical
reader는 이 둘을 혼동하지 않는다.

## 세그먼트와 주식수

### `fundamentals.segment_metrics`

grain은 `(cik, accession_no, fiscal_year, fiscal_period, segment_hash)`다.
`axis_type`, `segment_key`, `segment_label`, `metric_name`, `metric_value`,
`unit`, `source`, `quality_status`, `ingested_at`을 저장한다. 숫자를 사용할 때는
quality gate를 통과한 행만 선택한다.

### `fundamentals.share_class_snapshots`

grain은 `(cik, share_class_key, as_of_date, accession_no)`다. 클래스별 `ticker`,
`security_id`, `shares_outstanding`, `form_type`, `filed_at`, `ingested_at`을
보존하며, 여러 클래스가 있을 때 valuation을 임의로 합치지 않는다.

## earnings / expectations

| table | 핵심 natural key | 주요 시점 |
|---|---|---|
| `earnings_results` | security · fiscal year/period · accession | `filed_at`, `available_at` |
| `earnings_estimates` | security · snapshot · horizon · source | `snapshot_date`, `collected_at` |
| `earnings_schedule_versions` | security · target period · snapshot · source | `snapshot_date`, `collected_at` |
| `analyst_consensus_snapshots` | security · snapshot date · source | `snapshot_date`, `collected_at` |

예상치와 일정은 관측 snapshot을 append/upsert하며, 현재 값과 과거 관측을 같은 행에
덮어쓰지 않는다. 실적 결과는 `filings` provenance와 연결한다.

## reporting view

현재 공개 reporting view는 다음과 같다.

- `reporting.company_financials_latest`
- `reporting.earnings_schedule`
- `reporting.earnings_surprise`

TTM·종합 지표·역사 valuation은 원장과 market 데이터를 application/reporting에서
계산한다. 별도 파생 저장소나 갱신 RPC는 canonical contract가 아니다.
