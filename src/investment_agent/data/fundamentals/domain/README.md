# Fundamentals domain — 저장소와 무관한 계산 규칙

`investment_agent.data.fundamentals.domain`은 외부 공급자나 저장 방식이 바뀌어도 유지되어야 할 회계·재무
결정 규칙의 단일 기준이다. SEC 실제값, 차원값, 시장 예상값, 실적 발표값은 같은
회계기간 어휘를 공유하지만 서로 다른 관측 유형으로 유지한다.

상위 계층과 전체 데이터 흐름은 [../ARCHITECTURE.md](../ARCHITECTURE.md), 영속 컬럼은
[../COLUMNS.md](../COLUMNS.md)와 [../SEGMENT_COLUMNS.md](../SEGMENT_COLUMNS.md)를 본다.

## 1. 이 계층의 계약

domain 함수는 이미 가져온 dict·bytes·날짜를 받아 같은 입력에 같은 금융 의미의 결과를
돌려준다. 다음 책임은 domain에 둔다.

- SEC concept를 프로젝트의 제한된 지표 어휘로 분류한다.
- 원 공시 기간을 FY·단일 분기 관측으로 정규화한다.
- 중복 후보의 우선순위와 충돌 거부 규칙을 결정한다.
- XBRL dimension을 사업·제품/서비스·지역 축으로 분류한다.
- 세그먼트 합계를 기업 전체값과 대조해 지표별 품질을 판정한다.
- 상대 예상 horizon을 회사의 절대 회계기간으로 연결한다.
- 8-K 보도자료 본문에서 제한된 실적 정보를 추출한다.

다음 책임은 domain에 두지 않는다.

- SEC·Yahoo URL 호출, timeout, retry, 요청 간 sleep
- Supabase table/RPC/Storage query와 RLS
- 환경변수·CLI·GitHub Actions 해석
- ticker 대상 선정, 병렬 worker 조립, Discord 발송
- DB 보존 기간 삭제와 reporting read model 조회

## 2. 허용 의존성과 금지 의존성

이 계층을 “표준 라이브러리만 쓰는 계층”이라고 설명하지 않는다. 실제 허용 의존성은
다음과 같다.

| 의존성 | 허용 이유 |
| --- | --- |
| Python 표준 라이브러리 | 날짜, hash, 정규식, dataclass, 컬렉션 |
| `lxml.etree` | 호출자가 전달한 XBRL instance bytes의 인메모리 XML 파싱 |
| `investment_agent.data.fundamentals.filings.FilingRef` | fundamentals 공시 값 계약 |
| `investment_agent.platform.logging` | 구조화 로깅. 외부 호출이나 저장을 수행하지 않는다. |
| `data/gaap_mappings.json` | 패키지에 vendoring한 edgartools 기반 concept 사전 |

금지되는 의존성은 `investment_agent.data.fundamentals.application`, `infrastructure`, `jobs`,
`investment_agent.platform.db`, `supabase`, `yfinance`와 네트워크 클라이언트다. 환경변수도 읽지
않는다. 이 규칙은 `tests/test_fundamentals_architecture.py`가 검사한다.

`models/`, `taxonomy/`, `services/`는 책임별 묶음이지 내부 독립 계층은 아니다. 현재
`taxonomy/segment_concepts.py`가 QName local-name 정규화를 위해
`services/classify_dimensions.py`의 `local_name()`을 재사용한다. 따라서 domain 내부가
항상 `services -> taxonomy -> models`로만 흐른다고 가정하지 않는다. 새 순환 의존을
늘리지는 말고, 두 영역이 함께 써야 하는 규칙이 늘면 명시적인 낮은 수준 모듈로 분리한다.

## 3. 디렉터리와 모듈 책임

```text
domain/
├── models/
│   └── filing.py                    지원 form·statement와 form 정규화
├── taxonomy/
│   ├── financial_columns.py         company core 저장 어휘
│   ├── gaap_concepts.py             vendored 사전 + 명시적 semantic policy
│   ├── segment_axes.py              축 후보와 mapping version
│   ├── segment_concepts.py          세그먼트 concept·이익 정의 분류
│   └── segment_metrics.py           revenue/profit/assets 성격과 허용 조합
├── services/
│   ├── reported_observations.py     후보 선택, YTD/Q4, company wide pivot
│   ├── validate_financial_statements.py  wide 불변조건과 격리 사유
│   ├── parse_xbrl.py                XBRL instance -> dimension facts
│   ├── normalize_segment_facts.py   FSDS dimension -> segment transient facts
│   ├── classify_dimensions.py       대표 축·멤버 정규화와 aggregate 판정
│   ├── build_segment_metrics.py     직접/YTD/Q4 세그먼트 지표 후보
│   ├── assess_segment_quality.py    회사 기준값 대조와 지표별 품질
│   ├── map_fiscal_periods.py        예상치 horizon의 회계기간 고정
│   ├── classify_report_session.py   발표 시각 -> BMO/AMC 세션과 수집 창
│   ├── resolve_flash_period.py      8-K 공시일 -> 회사 회계분기
│   └── parse_earnings_release.py    보도자료의 매출·가이던스 추출
└── policies.py                      여러 서비스가 공유하는 허용 오차
```

`models/filing.py`에는 현재 복잡한 불변 value object가 없다. 지원 form·statement 상수와
정정공시 form을 기본 form으로 바꾸는 `normalize_form()`이 있다. 존재하지 않는 객체
모델을 문서상 계약으로 만들지 않는다.

## 4. 메모리 관측 계약

원시 fact dict는 영구 public schema가 아니라 domain과 application 사이의 내부 계약이다.
모든 경로는 다음 의미를 보존한다.

| 필드군 | 대표 필드 | 규칙 |
| --- | --- | --- |
| 발행인·공시 | `ticker`, `accession_no`/`accession`, `form`, `filed_at` | accession은 정정공시와 재처리의 기준이다. |
| 회계기간 | `fiscal_year`, `fiscal_period`, `period_start`, `period_end`, `qtrs`/`period_kind` | FY와 discrete Q1~Q4를 구분한다. |
| 의미 | `concept`/`concept_qname`, `column_key`, `standard_tag`, `unit` | 원 QName과 선택된 표준 의미를 함께 전달한다. |
| 값 | `value` 또는 wide 지표 | 단위가 같은 값만 차감·비교한다. |
| 차원 | `dimensions`, `axis`, `member`, `dimensions_hash` | company fact에는 없고 segment fact에만 있다. |
| 파생·근거 | `is_derived`, `derivation`, source context | 직접 공시값과 계산값을 구분하고 재현 근거를 보존한다. |

Company는 daily·backfill 모두 `infrastructure.sec.companyfacts`가 이 계약을 만든다.
최신 회계연도 CompanyFacts coverage가 부족하면 `filing_xbrl`이 저장소 내장 XBRL 파서의
비차원 us-gaap fact를 같은 계약으로 바꾸고 해당 accession 전체를 교체한다.
Segment daily는 `parse_xbrl.py`, segment backfill은 `normalize_segment_facts.py`가
같은 downstream 지표 계약으로 수렴한다. 원천이 다르다는 이유로 별도 금융 의미를
만들지 않는다.

## 5. 기업 전체 재무 규칙

### Concept 선택

`gaap_mappings.json`은 폭넓은 후보 사전일 뿐 최종 회계 정책이 아니다.
`gaap_concepts.py`의 명시적 `ColumnPolicy`가 중요 컬럼의 허용 태그, 단위, 우선순위,
충돌 거부 여부를 고정한다.

`select_semantic_candidates()`는 같은 ticker·컬럼·회계기간·duration 후보에서 다음 순서를
적용한다.

1. 최신 `filed_at`과 accession의 공시를 선택한다.
2. 명시적 policy priority가 가장 높은 concept를 선택한다.
3. 동순위의 서로 다른 tag가 남으면 mapping anomaly를 만든다.
4. 해당 컬럼이 충돌 거부 정책이면 값을 버리고, 아니면 결정적인 이름 순서로 하나를 고른다.

대차대조표 컬럼은 duration 항목보다 instant context를 우선한다. 원본 fact는 파생값보다
우선하고, 같은 종류라면 최신 공시를 우선한다.

### 기간 정규화

- Q2·Q3가 YTD 누적이면 직전 누적 또는 discrete 분기를 차감한다.
- 일반 유량의 Q4는 `FY - Q1 - Q2 - Q3`이다.
- 가중평균주식수는 기간 일수가 있으면 일수 가중식을 사용하고, 없을 때만 분기 수
  가중식을 fallback으로 쓴다.
- 가중평균주식수 파생값이 0 이하이면 그 값을 만들지 않는다.
- instant FY 값은 Q4 기간말 값으로 사용할 수 있지만 유량처럼 차감하지 않는다.
- Q4의 Q1~Q3는 단순 fiscal-year label이 아니라 FY 종료 전 12개월의 `period_end`로 맞춘다.

`validate_financial_statements.check_core_wide()`는 wide에 도달한 0 이하 평균주식수를
NULL로 바꾸고 데이터 이슈 사유를 만들며, 자산과 부채+자본의 차이가
`policies.BALANCE_TOLERANCE`를 넘으면 balance mismatch를 기록한다. 품질 경고는 나머지
유효 컬럼의 저장을 막지 않는다.

## 6. 차원 재무 규칙

### 축과 concept

- namespace와 `Axis`/`Member` 접미사를 제거해 비교 가능한 이름으로 만든다.
- 주 축과 선택적 보조 축은 명시적 DB registry, 코드 override, 표준 축, 제한된 이름
  heuristic의 근거를 구분한다.
- 단일축은 depth 1 부모, 제품×지역처럼 정확히 두 개의 분석 축이 있는 교차 행은 depth 2
  자식으로 저장한다. qualifier를 제외해도 세 축 이상이면 저장하지 않는다.
- concept registry의 명시적 승인·차단이 vendored edgartools 사전보다 우선한다.
- 이익은 숫자만 표준화하지 않고 `profit_measure_kind`를 함께 유지한다. 정의가 다른
  이익을 한 시계열로 차감하거나 합산하지 않는다.

### 파생과 품질

- `build_segment_metrics.py`는 직접 공시값, YTD 후보, Q4/YTD 파생 후보를 만든다.
- 실제 discrete 분기가 있으면 derived 분기보다 우선한다.
- `revenue`와 `profit_loss`만 차감 가능한 flow다. `assets`는 instant라 파생하지 않는다.
- `assess_segment_quality.py`는 같은 축 합계를 `financial_versions` 기준값과 대조한다.
- 매출·이익·자산 품질은 독립적으로 `verified`, `partial`, `unsafe`를 판정한다. 한 지표가
  unsafe여도 다른 검증 지표를 보존할 수 있다.
- domain은 품질 사유까지 계산한다. 실제 DB compact projection에서 unsafe 값을 버리는
  것은 company 기준값을 읽는 `SegmentMetricRepository` 구현이 수행한다.

정확한 coverage 범위와 저장 컬럼은 [../SEGMENT_COLUMNS.md](../SEGMENT_COLUMNS.md)를
단일 기준으로 사용한다.

## 7. 예상치와 이벤트 규칙

`map_fiscal_periods.py`는 Yahoo의 `q+0`, `q+1`, `fy+0`, `fy+1` 같은 상대 horizon을
호출자가 `financial_versions`에서 읽어 전달한 회사 회계력에 맞춘다. 결과에는 절대
`target_fiscal_year`, `target_fiscal_period`, `target_period_end`가 있어야 한다.
매핑할 수 없는 행은 추정해서 저장하지 않고 issue로 반환한다.

`parse_earnings_release.py`는 전달받은 HTML에서 제한된 매출 표현과 가이던스 문장을
추출한다. 네트워크 다운로드나 전체 재무제표 해석을 하지 않는다. EPS·매출 surprise
비율은 domain 함수가 아니라 `db/postgres/v1/90_reporting.sql`의 `reporting.earnings_surprise`가 계산한다.
그 뷰는 예상치를 저장 값이 아니라 `earnings_estimates`에서 `snapshot_date <
filed_at`으로 시점 조인해 가져온다. 같은 날 스냅샷은 발표 전후를 구분할 수 없어
보수적으로 제외한다.

## 8. 공개 이름과 사용 방식

`domain.services`는 자주 쓰는 다음 함수를 선별해 재수출한다.

- `match_reported_earnings`
- `normalize_consensus`
- `parse_earnings_release`
- `periodize`, `select_semantic_candidates`, `to_wide_tables`

`domain.taxonomy`는 company/segment 저장 컬럼 집합과 `SEGMENT_METRICS`를 재수출한다.
XBRL 파서, 세부 normalizer, registry 해석처럼 특정 흐름에만 속한 함수는 소유 모듈에서
직접 import한다. 공개 목록에 없는 이름을 위해 별도 모듈을 만들지 않는다.

## 9. 테스트와 변경 체크리스트

Domain 테스트는 네트워크·DB 없이 고정 입력으로 다음을 검증해야 한다.

- form 정규화와 지원 statement
- GAAP 후보 우선순위, 단위, 충돌 거부
- YTD·Q4·가중평균주식수 파생과 비-12월 결산사 매칭
- balance mismatch와 비정상 주식수 격리
- 단일축 선택, nested aggregate 제거, concept registry 우선순위
- 지표별 segment coverage와 unsafe 독립 제거
- 상대 horizon의 회계기간 매핑과 look-ahead 방지
- 8-K 보도자료 파서의 선택적 필드 처리

변경 전후에는 다음을 확인한다.

1. 같은 입력의 결과가 실행 시각·환경변수·외부 상태에 따라 달라지지 않는가?
2. 새 concept가 기존 컬럼과 회계적으로 같은 의미인가, 단지 이름이 비슷한가?
3. flow와 instant를 섞거나 서로 다른 단위·이익 정의를 차감하지 않는가?
4. derived 값보다 직접 공시값이 계속 우선하는가?
5. issue를 조용히 버리지 않고 JSON 로그와 failure detail로 전달하는가? workflow 실패는
   Discord `#운영-요약`의 Actions 사건 카드로 연결되는가?
6. taxonomy·컬럼 사전·DDL·테스트를 함께 갱신했는가?

전체 오프라인 검증은 저장소 루트에서 실행한다.

```bash
python -m unittest discover -s tests -t .
```
