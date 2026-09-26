# Fundamentals canonical 컬럼 — 이름과 의미

아래 표는 `db/postgres/v1/30_fundamentals.sql`의 현재 저장 계약을 요약한다. 없는 파생 테이블이나
과거 이름을 이 문서에 추가하지 않는다.

## provenance

### `fundamentals.filings`

| column | 의미 |
|---|---|
| `accession_no` | SEC 공시 accession, primary key |
| `cik` | 공시 등록인 |
| `form_type` | 10-K, 10-Q(정정본 포함), 8-K |
| `filing_date` | 제출일(ET 날짜) |
| `report_date` | SEC `reportDate` — 정기공시는 보고 기간 말일 |
| `available_at` | 우리 수집기가 공시를 처음 손에 넣은 시각(운영 PIT 경계) |
| `source` | 원천 provider |

값을 정하는 곳은 기업 재무 공시 경로 하나다. 주식수·8-K·세그먼트 경로는 FK 부모가 없을 때만
행을 만든다(`test_architecture.FilingsOwnershipTest`).

### `fundamentals.filing_processing`

| column | 의미 |
|---|---|
| `accession_no` | `filings` FK |
| `content_type` | `company`, `segments` |
| `status` | parsed / empty / unsupported / superseded |
| `facts_count` | 읽은 허용 XBRL fact 수 |
| `rows_count` | 저장한 행 수 |
| `updated_at` | 처리 결과를 마지막으로 기록한 시각 |

## 재무 원장

### `fundamentals.financials`

grain은 `(cik, period_end)`이고 `(cik, fiscal_year, fiscal_period)`도 유일하다. 분기(Q1~Q4)만
저장하고 연간은 네 분기의 합이다. 정정 공시는 보고한 컬럼만 덮는다. `accession_no`는 값을 마지막으로
반영한 공시, `ingested_at`은 마지막으로 쓴 시각이다.

한 컬럼은 한 회계 개념이다. 헷갈리기 쉬운 것:

| column | 뜻 |
|---|---|
| `net_income` | 모회사 귀속 순이익(NetIncomeLoss). 없으면 연결 순이익 - 비지배지분 순이익 |
| `common_equity` | 보통주 자본 = 모회사 주주자본 - 우선주. 비지배지분·메자닌 제외 |
| `short_term_debt` · `current_portion_of_long_term_debt` · `long_term_debt` | 서로 겹치지 않는 차입금. 총차입은 이 셋과 운용리스 부채의 합(`leverage_metrics.total_debt`) |
| `total_debt_including_current` | 회사가 보고한 총차입(리스 제외). 구성요소 합의 검증에만 쓴다 |
| `eps_basic_gaap` · `eps_diluted_gaap` | 보고값. 없는 분기는 순이익÷가중평균 주식수(뺄셈으로 만들지 않는다) |
| `is_liabilities_derived` | 총부채를 자산-(보통주 자본+우선주+비지배지분+메자닌)으로 계산했는가 |

컬럼마다 허용 XBRL 태그는 `domain/taxonomy/gaap_concepts.py`의 `COLUMN_POLICIES`가 정한다.
총계 태그만 허용하고, 없으면 비운다.

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
| `earnings_results` | cik · fiscal year/period · accession | `filings.filing_date`, `filings.available_at` |
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
