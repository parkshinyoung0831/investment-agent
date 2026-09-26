# Fundamentals 아키텍처 — 계층 경계와 소유 규칙

이 문서는 현재 v1 구현의 경계만 정의한다. 스키마의 단일 기준은
`db/postgres/v1/30_fundamentals.sql`이고 reporting read model은 `db/postgres/v1/90_reporting.sql`에 있다.

## 의존성 방향

```text
source adapters (SEC / Yahoo)
        │
        ▼
domain normalization + application builders
        │
        ▼
application use cases
        │
        ▼
infrastructure.supabase (canonical readers/writers)
        │
        ├── reporting views
        ├── notifications producers
        └── dashboard / trading evidence readers
```

`domain` 안의 계산 규칙 자체는 [domain/README.md](domain/README.md)가 갖는다.
`domain`은 Supabase·HTTP·환경변수를 import하지 않는다. `application`은 port에만
의존하고 provider 구현을 알지 않는다. `infrastructure`만 외부 API와 Supabase를
구체적으로 다룬다. command는 use case를 조립하는 얇은 실행 경계다.

## 저장 책임

| 책임 | owner |
|---|---|
| SEC filing provenance와 처리 상태 | `infrastructure.supabase.company_financials` |
| CIK 기반 재무 version | `infrastructure.supabase.company_financials` |
| 세그먼트 metric과 retention | `infrastructure.supabase.segment_metrics` |
| share-class snapshot | `infrastructure.supabase.share_class_snapshots` |
| earnings result | `infrastructure.supabase.earnings_events` |
| estimates / analyst snapshot | `infrastructure.supabase.expectations` |
| integrity checks | `infrastructure.supabase.integrity` |
| ticker·CIK·watchlist lookup | `data.universe` public reader |

모든 writer는 canonical parent를 먼저 upsert하고, natural key를 명시한 idempotent
upsert를 사용한다. 공유 `filings`는 segment writer가 임의로 삭제하지 않는다.
retention은 자식 metric과 해당 content type의 processing 상태를 순서대로 처리한다.

## 시점 정합성

`financials`는 (cik, period_end)마다 한 행이고 `accession_no`는 값을 마지막으로 반영한
공시다. PIT reader는 그 기간을 처음 공개한 정기공시(같은 CIK·`report_date`의 가장 이른
10-Q/10-K)로 자른다.

```text
first_disclosure.filing_date <= cutoff date          (filed_before: 제출일 공개 규칙)
first_disclosure.available_at <= as_of_at            (as_of: 우리가 받은 시각)
```

정정 값은 원본 공시일로 소급된다. 정정은 기간의 0.5% 미만이고, 매매 판단이 당시 본 값은
판단 evidence가 보관한다.

`security_fundamentals_filed_before`는 공시일 기준 비교용이고,
`security_fundamentals_as_of`는 실제 당시 사용 가능했던 데이터만 반환한다.
두 reader 모두 ticker를 universe security에서 CIK로 해석한 뒤 원장을 읽는다.

## 계산과 reporting

원장에 없는 TTM·margin·surprise·valuation은 계산 결과를 별도 writer로 저장하지
않는다. `reporting.company_financials_latest`, `reporting.earnings_schedule`,
`reporting.earnings_surprise`와 application 계산기가
필요한 시점에 원장으로부터 결과를 만든다. 따라서 별도 파생 결과 갱신 job은
architecture contract에 포함되지 않는다.

## 실패와 검증

- filing별 partial success는 이미 저장된 canonical 행을 보존한다.
- 처리 실패는 `filing_processing`의 terminal 상태와 실행 metrics에 남긴다.
- provider 오류와 DB 오류는 command 결과의 failures에 분리한다.
- `tests/investment_agent/data/fundamentals/`가 domain·application·infrastructure
  계약을 검증한다.
- 실제 DB reset, schema probe, 외부 수집, Discord 발송은 이 문서의 offline 검증 범위가
  아니다.
