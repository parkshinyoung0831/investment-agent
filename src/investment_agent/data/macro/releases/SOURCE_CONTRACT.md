# ECON 데이터 출처 계약 — 고정 30개 지표

제공처 확인일: 2026-08-27. 구조 갱신일: 2026-08-31.
이 문서는 `series_config.json`의 `source_contract`를 사람이 검토하기 쉽게 펼친 것이다.
경제발표 지표군은 정확히 30개이며, 값을 합법적이고 정확하게 제공할 수 없는 지표군에는
임의 대체값을 넣지 않고 수집 상태와 제약을 명시한다.

공통 원칙:

- `observations`에는 아래 실제값 코드의 원시 관측값만 저장하고, 투자용 measure는
  `normalize.py`의 변환식과 `db/postgres/v1/40_macro.sql`의 measure catalog를 기준으로 계산한다.
- Survey는 라이선스와 실제 제공 여부가 확인된 제공처만 `forecast_kind=survey`로 저장한다.
  현재 FMP economic-calendar endpoint는 이 프로젝트 키에서 HTTP 402/403을 반환하므로
  **30개 Survey 모두 `unsupported`**다.
- FRED/ALFRED 요청에는 초당 2회 이하 제한, 30/60초 timeout, 유한값·중복 검증을 적용한다.
  FRED 발표 달력은 날짜만 제공할 수 있으므로 출처 계약의 발표시각과 watcher의 제한된
  polling을 함께 사용한다.
- 일정의 `date_only`는 현지 정오를 UTC로 바꾼 저장 기준점일 뿐 발표시각이 아니다. 감시 구간은 36시간이다.
  원자료 ALFRED 빈티지는 날짜 표식을 보존하며 `time_precision=date_only`로 구별한다.
- 비교월과 전년동월은 정확한 달력 기준으로 읽는다. 원자료가 없으면 다른 달을 대신 사용하지 않는다.
- 과거 예상값·빈티지에도 실제 수집시각을 기록한다. 소스 기준의 과거 날짜를 수집시각으로 복사하지 않는다.
- ALFRED `output_type=4`는 최초 발표값, `output_type=3`는 개정값 감사에 사용한다.
  ECOS/EIA에는 공개 빈티지가 없으므로 과거 원시 이력은 `DEGRADED`이며 최초 발표시각을 꾸며내지 않는다.

| 지표군 | 실제값 제공처·코드 | 일정 제공처·현지 발표시각 | 주기·원시 단위 → 투자 measure | 빈티지·과거 적재 | 대체 경로·라이선스·상태 |
|---|---|---|---|---|---|
| US CPI | FRED `CPIAUCSL` | FRED release 10, 08:30 ET `exact` | 월간 지수 → 수준값, 전월비, 전년동월비 | ALFRED 최초 발표·개정 | 대체 경로 없음, FRED 출처표시 · 정상(OK) |
| US Core CPI | FRED `CPILFESL` | FRED release 10, 08:30 ET `exact` | 월간 지수 → 전월비, 전년동월비 | ALFRED 최초 발표·개정 | 대체 경로 없음 · 정상(OK) |
| US PPI | FRED `PPIFIS` | FRED release 46, 08:30 ET `exact` | 월간 지수 → 전월비, 전년동월비 | ALFRED 최초 발표·개정 | 대체 경로 없음 · 정상(OK) |
| US Core PPI | FRED `PPIFES` | FRED release 46, 08:30 ET `exact` | 월간 지수 → 전월비, 전년동월비 | ALFRED 최초 발표·개정 | 대체 경로 없음 · 정상(OK) |
| US PCE | FRED `PCEPI` | FRED release 54, 08:30 ET `exact` | 월간 지수 → 전월비, 전년동월비 | ALFRED 최초 발표·개정 | 대체 경로 없음 · 정상(OK) |
| US Core PCE | FRED `PCEPILFE` | FRED release 54, 08:30 ET `exact` | 월간 지수 → 전월비, 전년동월비 | ALFRED 최초 발표·개정 | 대체 경로 없음 · 정상(OK) |
| KR CPI | ECOS `901Y009/0` | 통계청 일정 규칙, 08:00 KST | 월간 지수 → 전월비, 전년동월비 | 최신값·과거값 가능, 빈티지 없음 | ECOS만 사용 · 제한(DEGRADED) |
| KR Core CPI | ECOS `901Y010/20` | 통계청 일정 규칙, 08:00 KST | 월간 지수 → 전월비, 전년동월비 | 최신값·과거값 가능, 빈티지 없음 | ECOS만 사용 · 제한(DEGRADED) |
| US NFP | FRED `PAYEMS` | FRED release 50, 08:30 ET `exact` | 월간 천 명 → 월간 증감 | ALFRED 최초 발표·개정 | 대체 경로 없음 · 정상(OK) |
| US Unemployment | FRED `UNRATE` | FRED release 50, 08:30 ET `exact` | 월간 % → 수준값 | ALFRED 최초 발표·개정 | 대체 경로 없음 · 정상(OK) |
| US AHE | FRED `CES0500000003` | FRED release 50, 08:30 ET `exact` | 월간 USD → 전월비, 전년동월비 | ALFRED 최초 발표·개정 | 대체 경로 없음 · 정상(OK) |
| US JOLTS Openings | FRED `JTSJOL` | FRED release 192, 10:00 ET `exact` | 월간 천 개 일자리 → 수준값 | ALFRED 최초 발표·개정 | 대체 경로 없음 · 정상(OK) |
| US Initial Claims | FRED `ICSA` ×0.001 | FRED release 180, 08:30 ET `exact` | 주간 천 명 → 수준값 | ALFRED 최초 발표·개정 | 대체 경로 없음 · 정상(OK) |
| US Continuing Claims | FRED `CCSA` ×0.001 | FRED release 180, 08:30 ET `exact` | 주간 천 명 → 수준값 | ALFRED 최초 발표·개정 | 대체 경로 없음 · 정상(OK) |
| US GDP | FRED `A191RL1Q225SBEA` | FRED release 53, 08:30 ET `exact` | 분기 연율 % → 전분기비 연율 | ALFRED, GDPNow archive | Atlanta Fed GDPNow nowcast · 정상(OK) |
| KR GDP | ECOS `200Y102/10111` | BOK 일정 규칙, KST `date_only` | 분기 % → 공식 전분기비 | 최신값·과거값 가능, 빈티지 없음 | ECOS만 사용 · 제한(DEGRADED) |
| US Retail Sales | FRED `RSAFS` | FRED release 9, 08:30 ET `exact` | 월간 백만 USD → 전월비, 전년동월비 | ALFRED 최초 발표·개정 | 대체 경로 없음 · 정상(OK) |
| US Industrial Production | FRED `INDPRO` | FRED release 13, 09:15 ET `exact` | 월간 지수 → 전월비, 전년동월비 | ALFRED 최초 발표·개정 | 대체 경로 없음 · 정상(OK) |
| ISM Manufacturing | 없음 | 없음(일반적으로 10:00 ET) | 월간 PMI → 수준값 | 없음 | ISM 이용조건상 허가 없는 자동 복제·보관·데이터 스트림 금지 · **미지원(UNSUPPORTED)** |
| ISM Services | 없음 | 없음(일반적으로 10:00 ET) | 월간 PMI → 수준값 | 없음 | 동일한 ISM 이용조건 제약 · **미지원(UNSUPPORTED)** |
| Michigan Sentiment | FRED `UMCSENT` | FRED release 91, ET `date_only` | 월간 지수 → 수준값 | 제공되는 범위에서 ALFRED 사용 | 미시간대 소유 데이터, 내부 출처표시만 허용, FRED 지연 · 제한(DEGRADED) |
| US FOMC / Fed Funds | FRED `DFEDTARU`(제공처 날짜 −1일 → 결정 이벤트) | Federal Reserve 공식 FOMC 달력, 14:00 ET 규칙, 추가 감시 36시간 | 비정기 % → 상단금리 수준값 | 현재 이력만 가능, 정규화된 최초 이벤트 빈티지 없음 | 비결정 보도자료가 섞이는 FRED release 101은 사용하지 않으며 제공처 날짜는 고정 offset으로 역산 가능 · 제한(DEGRADED) |
| KR Base Rate | ECOS `722Y001/0101000` | BOK 공식 달력, **09:50 KST `exact`** | 비정기 % → 수준값 | 최신값·과거값 가능, 빈티지 없음 | 수동 관리하는 공식 달력만 사용 · 제한(DEGRADED) |
| US 30Y Mortgage | FRED `MORTGAGE30US` | FRED release 190, 12:00 ET `exact` | 주간 % → 수준값 | ALFRED 최초 발표·개정 | 대체 경로 없음 · 정상(OK) |
| US New Home Sales | FRED `HSN1F` | FRED release 97, 10:00 ET `exact` | 월간 천 호 → 수준값 | ALFRED 최초 발표·개정 | 대체 경로 없음 · 정상(OK) |
| US Existing Home Sales | FRED `EXHOSLUSM495S` | **미지원**: FRED release 291에 사용 가능한 날짜가 없고 승인된 공식 달력 adapter도 없음 | 월간 천 호 원시값만 사용 | 현재 이력 가능, ALFRED 사용 불가 | 합법적 일정 출처 승인 전까지 발표·빈티지를 생성하지 않음 · 제한(DEGRADED) |
| US M2 | FRED `M2SL` | FRED release 21, ET `date_only` | 월간 십억 USD → 수준값, 전년동월비 | ALFRED 최초 발표·개정 | 공식 출처가 없는 정확한 시각을 단정하지 않음 · 정상(OK) |
| Fed Net Liquidity | FRED `WALCL-WTREGEN-RRPONTSYD` | FRED release 20, 16:30 ET 규칙 | 주간 십억 USD → 수준값, 4주 변화량 | 구성요소의 현재 이력만 가능 | 구성요소별 ALFRED 빈티지 재구성 미구현 · 제한(DEGRADED) |
| KR Export | ECOS `301Y013/110000` ×0.001 | 공식 일정 규칙, 09:00 KST | 월간 십억 USD → 수준값, 전년동월비 | 최신값·과거값 가능, 빈티지 없음 | ECOS만 사용 · 제한(DEGRADED) |
| EIA Crude Oil Inventories | EIA `WCESTUS1` | 공식 수요일 규칙, 10:30 ET | 주간 천 배럴 → 수준값, 주간 변화량 | 최신값·과거값 가능, 빈티지 없음 | EIA Open Data, 휴일 이동 감시 구간 적용 · 제한(DEGRADED) |

## Survey와 실시간·PIT 제공 범위

30개 지표군의 `survey_provider`는 모두 `unsupported`다. 실제 FMP 사용 권한이
확인되지 않았고 호출 결과가 HTTP 402/403이므로, 과거 consensus를 추정하거나
`own_model`을 Survey로 표시하지 않는다. 아래 표는 이 사실과 현재 실시간·PIT 범위를
지표군별로 고정한다.

| 지표군 | Survey 제공처 | 실시간·PIT 제공 범위 |
|---|---|---|
| US CPI | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| US Core CPI | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| US PPI | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| US Core PPI | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| US PCE | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| US Core PCE | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| KR CPI | 미지원(FMP 402/403) | ECOS 최신값·과거값, 빈티지·PIT 없음 |
| KR Core CPI | 미지원(FMP 402/403) | ECOS 최신값·과거값, 빈티지·PIT 없음 |
| US NFP | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| US Unemployment | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| US AHE | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| US JOLTS Openings | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| US Initial Claims | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| US Continuing Claims | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| US GDP | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT, 제공 시 Atlanta GDPNow nowcast |
| KR GDP | 미지원(FMP 402/403) | ECOS 최신값·과거값, 빈티지·PIT 없음 |
| US Retail Sales | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| US Industrial Production | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| ISM Manufacturing | 미지원 | 자동 실시간·과거 수집 없음, 라이선스 제약 |
| ISM Services | 미지원 | 자동 실시간·과거 수집 없음, 라이선스 제약 |
| Michigan Sentiment | 미지원(FMP 402/403) | FRED 지연 최신값, 가능한 범위의 ALFRED, 소유권 라이선스로 제한 |
| US FOMC / Fed Funds | 미지원(FMP 402/403) | FRED 목표금리 최신값과 공식 달력, 이벤트 빈티지·PIT 없음 |
| KR Base Rate | 미지원(FMP 402/403) | ECOS 최신값·과거값과 BOK 달력, 빈티지·PIT 없음 |
| US 30Y Mortgage | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| US New Home Sales | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| US Existing Home Sales | 미지원(FMP 402/403) | FRED 최신값·과거값만 가능, 일정·빈티지 없음 |
| US M2 | 미지원(FMP 402/403) | FRED 최신값, ALFRED 최초 발표·개정 PIT |
| Fed Net Liquidity | 미지원(FMP 402/403) | FRED 구성요소 최신값, 구성요소 빈티지 재구성 불가 |
| KR Export | 미지원(FMP 402/403) | ECOS 최신값·과거값, 빈티지·PIT 없음 |
| EIA Crude Oil Inventories | 미지원(FMP 402/403) | EIA 최신값·과거값, 빈티지·PIT 없음 |

## 제공처 참고 문서

- FRED/ALFRED API: <https://fred.stlouisfed.org/docs/api/fred/series_observations.html>
- FRED 발표 달력: <https://fred.stlouisfed.org/docs/api/fred/release_dates.html>
- ECOS Open API: <https://ecos.bok.or.kr/api/>
- EIA Open Data: <https://www.eia.gov/opendata/>
- Atlanta Fed GDPNow: <https://www.atlantafed.org/cqer/research/gdpnow>
