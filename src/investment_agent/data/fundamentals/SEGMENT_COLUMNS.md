# Segment metrics

세그먼트 저장 계약은 `fundamentals.segment_metrics`와 공유 provenance 표인
`fundamentals.filings`, `fundamentals.filing_processing`으로 구성된다.

## 저장 grain

```text
(cik, accession_no, fiscal_year, fiscal_period, segment_hash)
```

`segment_hash`는 축과 멤버 identity에서 안정적으로 계산한다. 같은 공시를 다시
처리해도 같은 natural key로 수렴해야 한다.

## 핵심 columns

| column | 의미 |
|---|---|
| `cik` | 등록인 identity |
| `accession_no` | `fundamentals.filings` FK |
| `fiscal_year`, `fiscal_period` | 공시 회계기간 |
| `axis_type` | business / geographic / product 등 |
| `segment_key` | 정규화된 member identity |
| `segment_label` | 표시용 이름 |
| `metric_name` | revenue, operating income 등 |
| `metric_value` | 원문 단위의 값 |
| `unit` | USD 등 단위 |
| `quality_status` | verified / partial / rejected |
| `mapping_version` | 정규화 규칙 버전 |
| `ingested_at` | 저장 시각 |

## 처리 상태

세그먼트 처리 상태는 `filing_processing`에서 `content_type='segments'`로 기록한다.
공시 원문과 기업 전체 재무가 사용하는 `filings`를 공유하므로, 세그먼트 writer가
부모 provenance를 중복 생성하거나 임의 삭제하지 않는다.

처리 순서는 다음과 같다.

1. `filings`에 accession provenance를 upsert한다.
2. `filing_processing`의 segment 상태를 확인한다.
3. XBRL facts를 정규화하고 quality gate를 적용한다.
4. `segment_metrics`를 natural key로 upsert한다.
5. 재처리 시 기존 accession의 stale metric을 자식부터 삭제하고 새 결과를 쓴다.

## 읽기와 품질

- 대량 reader는 `select_all_paged()`와 `(cik, accession_no, fiscal_year,
  fiscal_period, segment_hash)` order를 사용한다.
- dashboard와 notification은 `verified` 또는 허용된 `partial`만 숫자로 표시한다.
- `rejected`와 provider unavailable은 숫자 합계에 포함하지 않고 상태로 노출한다.
- ticker 표시는 securities reader를 통해 수행한다.

## 보존

segment retention은 성공한 sync/backfill/reprocess 뒤 명시적으로 실행한다. 자식인
`segment_metrics`를 먼저 삭제하고, 같은 accession의
`filing_processing(content_type='segments')`만 다음에 삭제한다. 공유 `filings` 행은
이 작업에서 삭제하지 않는다.
