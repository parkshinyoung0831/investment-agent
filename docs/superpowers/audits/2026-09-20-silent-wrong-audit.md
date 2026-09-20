# 조용히 틀리는 것 감사 — 수집·저장·알림

에러도 종료 코드도 없이 **성공한 척 틀린 결과**를 내는 곳을 단계별로 찾은 감사 보고서다.
수집(외부 원천 → 파싱), 저장(DB 적재·보존), 알림(계산·판정·발송) 세 단계로 나눴고, 단계를
가로지르는 문제는 마지막에 따로 모았다.

이 문서는 특정 시점(2026-09-20)의 점검 결과다. 고치고 나면 낡는다 — 고친 항목은 지우고, 남길
가치가 있는 규칙만 해당 영역 문서·테스트로 옮긴다.

## 조치 상태

| 항목 | 상태 | 고친 곳 |
|---|---|---|
| N-1 캘린더 주 선택 | 수정됨 | `platform/clock.py`의 `kst_today()`를 캘린더 세 곳이 사용, 일요일 23:10 UTC → W39 테스트 |
| N-2 카드·대시보드 EPS | 수정됨 | 보고 `eps_diluted_gaap`만 사용, 재계산 제거. `metrics.eps_diluted`로 사본 통합 |
| C-1 주식수 스케일 | 검증기 추가, **기존 행 재처리 대기** | `validate_financial_statements`가 보고 EPS·순이익에서 역산한 주식수와 100배 넘게 어긋나면 비우고 anomaly 기록 |
| C-2 귀속 순이익 오매핑 | 매핑 수정, **기존 행 재처리 대기** | `net_income_to_common_shareholders`에 허용 태그 화이트리스트(`gaap_concepts`) |
| N-3 `is_estimated` 미사용 | 수정됨 | 카드 등급 `announced`("회사 공지") 추가 |
| 나머지 | 미착수 | X-4 킬스위치, X-1 대상 0건, X-2 verify_data 자동화, C-3~C-8, S-1, N-4~N-8, X-5 |

C-1을 운영 데이터 18,915행에 대 본 결과 122행이 잡혔다. 단위 오류(천·백만 배, 108행)는 주식수만 비우고,
액면분할 전후 값을 섞은 Q4 파생(AMZN 2022-Q4, NFLX 2025-Q4 등 14행)은 어느 쪽이 틀렸는지 알 수 없어
주식수와 EPS를 함께 비운다. 같은 종목 이력의 중앙값으로 가려 보면 122행 중 19행은 주식수가 멀쩡하고
EPS 쪽이 틀린 행(HAL 등, 관심종목 밖)이라 정상 주식수를 잃는다 — anomaly의 `detail`에 원래 값이 남는다.
관심종목에서 잡힌 행은 MCD·COP·KO(단위 오류)와 AMZN·NFLX(기준 혼합)뿐이다.

## 1. 읽는 법

### 확인 수준

| 표시 | 뜻 |
|---|---|
| **재현** | 같은 입력으로 잘못된 출력을 직접 만들어 냈다 |
| **데이터** | 운영 DB를 읽기 전용으로 조회해 값으로 확인했다 |
| **코드** | 코드를 읽어 확인했다. 실행으로는 재현하지 않았다 |
| **의심** | 정황은 강하지만 원천(SEC 원문 등)과 대조하지 못했다 |

### 심각도

| 표시 | 기준 |
|---|---|
| 높음 | 사용자에게 가는 숫자·알림이 틀리거나 통째로 빠진다. 또는 실주문 안전에 닿는다 |
| 중간 | 값이 비거나 어긋나지만 한정된 종목·화면에 그친다 |
| 낮음 | 드물거나, 이미 다른 장치가 드러내 준다 |

### 방법과 한계

- 소스 718개 파일 109,386줄을 AST로 훑어 후보를 뽑았다. 예외 삼킴 282곳, 빈 입력 조기 반환
  509곳, 예외 후 기본값 반환 110곳이 나왔고, 광범위·I/O 예외 100곳 중 영향이 큰 약 30곳을
  실제로 읽었다. **모든 줄을 읽은 것이 아니다.**
- DB 값은 읽기 전용 세션(`readonly=True`, 쓰기 시도는 `ReadOnlySqlTransaction`으로 거부됨)으로
  직접 조회했다.
- SEC 원문·FRED·Yahoo 원천과의 대조는 하지 못했다. 그래서 값 오류 중 **원인이 원천인지 파서인지
  가르지 못한 것은 의심**으로 적었다.
- 점검 중에 다른 커밋이 들어와 파일이 옮겨졌다. 아래 경로는 확인 시점의 현재 트리 기준이다.

## 2. 한눈에 보기

| ID | 단계 | 심각도 | 무엇이 조용히 틀리나 | 수준 |
|---|---|---|---|---|
| N-1 | 알림 | 높음 | 주간 캘린더가 UTC 날짜로 주를 골라 정시 실행이면 **끝난 주**를 선택한다 | 재현 |
| N-2 | 알림 | 높음 | 카드 EPS를 보고 EPS 대신 순이익÷주식수로 계산해 MCD가 3,321,614.40으로 나온다 | 데이터 |
| C-1 | 수집 | 높음 | 희석주식수 스케일 오류(MCD 10분기 연속, WAT 최근 2분기 1,000배) | 데이터 |
| C-2 | 수집 | 높음 | `net_income_to_common_shareholders`가 UNH 등 10여 곳에서 엉뚱한 작은 값 | 의심 |
| X-1 | 교차 | 높음 | "대상 0건이면 INFO 후 성공 종료"가 43곳, 모니터링은 "돌았는가"만 본다 | 코드 |
| X-4 | 교차 | 높음(잠복) | `harness_switch --kill-switch on`이 떠 있는 하네스에 반영되지 않는다 | 재현 |
| C-3 | 수집 | 중간 | 비금융 402곳 중 41곳(10%)의 현금이 NULL → EV·순부채가 빈칸 | 데이터 |
| C-4 | 수집 | 중간 | 부채 이중 계산 의심(45행 정확히 동일) | 의심 |
| C-5 | 수집 | 중간 | `company_name_ko`가 6,081곳 중 0곳 | 데이터 |
| C-6 | 수집 | 중간 | 13F 운용사 1곳만 2026-03-31에서 멈춤 | 의심 |
| C-7 | 수집 | 중간 | Michigan 소비자심리 마지막 재관측 9/14, 관측은 7월 | 의심 |
| N-3 | 알림 | 중간 | `is_estimated`를 안 읽어 항상 "날짜는 확정이 아닙니다" | 코드 |
| N-4 | 알림 | 중간 | 속보 `fact_at`이 `available_at` 우선 → 재적재 시 기준선 우회 | 데이터 |
| S-1 | 저장 | 중간 | `economic_observations` 56%가 같은 값의 일별 재복사 | 데이터 |
| S-2 | 저장 | 낮음 | 관심종목 시작일이 로컬(KST) 날짜라 전날 미국 접수 공시가 빠진다 | 코드 |
| N-5 | 알림 | 낮음 | `total_debt()`가 결측을 0.0으로 접는다 | 코드 |
| N-6 | 알림 | 낮음 | 속보·정밀 카드는 한 번 나가면 예상치·세그먼트가 채워져도 갱신 안 됨 | 코드 |
| N-7 | 알림 | 낮음 | 포럼 태그 조회 실패가 로그 없이 빈 튜플 | 코드 |
| N-8 | 알림 | 낮음 | Discord 한도 초과 시 자르지 않고 영구 포기(`abandoned`) | 코드 |
| C-8 | 수집 | 낮음 | ISM PMI 두 시계열이 정의만 있고 수집되지 않는다 | 데이터 |
| X-2 | 교차 | 중간 | 값 검증기 41개가 전부 통과하는데 위 값 결함은 하나도 못 잡는다 | 데이터 |
| X-3 | 교차 | 중간 | 카드 테스트 픽스처가 리더보다 풍부해 결함을 가린다 | 코드 |
| X-5 | 교차 | 중간 | 시간대 없는 `date.today()`가 21곳 | 코드 |

### 관심종목 50곳 영향표

관심종목 50곳 중 **14곳**이 최신 공시에서 값 문제를 하나 이상 가진다. 아래는 문제가 있는 종목만
적었고 나머지 36곳은 이 검사에서 걸리지 않았다(N-2의 EPS 비교는 별도 기준이다).

| 종목 | 최신 공시 | 걸린 문제 | 관련 |
|---|---|---|---|
| MCD | 2026 Q2 | 주식수 스케일 | C-1, N-2 |
| UNH | 2026 Q2 | 귀속 순이익 불일치 | C-2, N-2 |
| BRK-B | 2026 Q2 | 주식수·현금·EPS 모두 없음 | N-2, C-3 |
| V | 2026 Q3 | 주식수·EPS 없음 | N-2 |
| XOM | 2026 Q2 | 희석주식수 없음 | N-2 |
| AVGO | 2026 Q3 | 부채 이중 계산 의심 | C-4 |
| NVDA | 2027 Q2 | 부채 이중 계산 의심 | C-4 |
| CVX·GE·MDLZ·PG·SBUX | 2026 Q2~Q4 | 현금 없음(비금융) | C-3 |
| BAC·JPM | 2026 Q2 | 현금 없음(금융사, 예상된 결측) | C-3 |

한국어 이름(C-5)은 관심종목 50곳 전부 비어 있다.

## 3. 수집 단계

외부 원천(SEC EDGAR·Yahoo·FRED·ECOS)에서 받아 파싱하는 곳.

### C-1. 희석주식수 스케일 오류 — 높음, 데이터

`fundamentals.financials.shares_fully_diluted_average`가 **자릿수가 틀린 채** 저장돼 있다.
전 이력에서 1e5 미만 또는 3e10 초과인 행을 세면:

| 종목 | 행 수 | 기간 | 값 | 해석 |
|---|---|---|---|---|
| MCD | 10 | 2024-03 ~ 2026-06 | 711.1 ~ 726 | 백만 단위 그대로(약 7억 주여야 함) |
| WAT | 2 | 2026-04-04, 2026-07-04 | 82,139,000,000 / 98,204,000,000 | 약 1,000배 큼 |
| AAPL | 1 | 2020-09-26 | 56,898,773,000 | 1,000배 큼 |
| NVDA | 1 | 2025-01-26 | 47,105,000,000 | 1,000배 큼 |
| KO | 4 | 2018-03 ~ 2019-03 | 4,290 ~ 4,306 | 백만 단위 |
| PCAR·VTRS·PSKY·CHD·AMCR·COHR·AXP·SW·BKR | 1~2 | 과거 | 100 ~ 13,001 | 백만·천 단위 혼입 |

`validate_financial_statements.py:31-43`은 주식수가 **양수인지만** 본다(`nonpositive_average_shares`).
자릿수는 안 보므로 위 값이 그대로 통과한다. **MCD는 오류가 지금도 진행 중**이고(마지막 2026-06-30),
관심종목이다. `share_class_snapshots.shares_outstanding`은 추적 종목 504곳 중 1곳만 1e6 미만이라
별도 경로(시총·밸류)는 대체로 안전해 보인다.

### C-2. `net_income_to_common_shareholders` 오매핑 — 높음, 의심

최신 공시에서 `net_income_to_common_shareholders`(없으면 `net_income`)로 재계산한 EPS가 보고 EPS와
30% 넘게 어긋나는 종목이 21곳이다. 이 중 BX·FCX·WYNN은 귀속 순이익이 비어 비지배지분을 포함한
`net_income`으로 대체돼 정당하게 어긋나므로 뺀다. `net_income`으로 계산하면 어긋나던
IBKR·APO·TKO·LYV·EQT 등은 귀속 순이익으로 계산하자 정합해졌다. 남은 종목은 **귀속 순이익이 사실상 0에 가깝다**.

| 종목 | 귀속 순이익(백만) | 보고 EPS | 희석주식수(백만) | 기대 순이익 |
|---|---|---|---|---|
| UNH | 63 | 6.04 | 906 | 약 5,470 |
| ELV | 8 | 6.71 | 217.9 | 약 1,460 |
| CEG | -21 | 1.42 | 360 | 약 511 |
| AON | -2 | 2.58 | 213.9 | 약 552 |
| EXPE·GEHC·GEV·HSIC·SBAC·SYY·J·MCK·SPGI·EW | -16 ~ 117 | 0.42 ~ 7.16 | | 수십~수천 |

`net_income`(비귀속 포함) 컬럼은 이 종목들에서 정상이라, `net_income_to_common_shareholders`가
**다른 개념(비지배지분 귀속분 등)에 매핑**된 것으로 의심한다. KLAC(순이익 +1,363M인데 EPS -22.61)과
LITE(순이익 -7,162M, EPS×주식수는 약 -3,444M)는 부호·규모가 따로 어긋난다. 원문 대조 전이라 의심이다.

### C-3. 비금융 종목의 현금 결측 — 중간, 데이터

비금융 402곳 중 **41곳(10%)** 의 최신 공시에서 `cash_and_cash_equivalents`가 NULL이다:
CVX·GE·MMM·MDLZ·DHR·GILD·EMR·CSX·CPRT·PG·SBUX 등. 금융사(BAC·JPM·AXP)의 결측은 예상된 것이다.

동작은 안전한 쪽이다. 현금이 `None`이면 `_net_debt()`가 `None`을 돌려주고(`earnings_report.py:477-482`)
EV 기반 밸류에이션이 **틀리게가 아니라 빈칸**으로 나온다. 다만 빈칸이라는 사실을 카드가 알리지 않는다.

같은 조회로 나온 다른 충전율(추적 500곳의 최신 공시): 매출 98%, 순이익 99%, 자산·부채·자본 100%,
희석주식수 97%, 영업현금흐름 99%, 설비투자 87%, 매출총이익 **37%**, `total_debt_including_current` **15%**.
비금융 매출 결측은 2곳(APA, FDXF).

### C-4. 부채 이중 계산 의심 — 중간, 의심

`total_debt()`(`reporting/services/financial_row.py:18-34`)는 `total_debt_including_current`가 없으면
단기차입 + 유동성 장기부채 + 장기부채 + 리스를 합한다. 그런데 `short_term_debt`의 XBRL 태그 목록
(`gaap_concepts.py`)에 `DebtCurrent`, `LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities`처럼
**유동성 장기부채를 이미 포함하는 태그**가 들어 있다.

최근 공시(2026-03 이후) 979행 중 직접 합계가 있는 행은 148개뿐이라 831행이 합산 경로를 탄다.
그중 단기차입과 유동성 장기부채가 **둘 다 채워진 행이 325개**이고, 이 중 **45개(14%)는 두 값이 정확히 같다**
(AVGO 2.25B 두 번, 다른 예: CIK 1633978, 882095, 1510295). 서로 다른 개념이 우연히 같은 값일 가능성은
낮지만 SEC 원문 대조는 못 했다.

### C-5. `company_name_ko` 0% — 중간, 데이터

`universe.entities`의 한국어 이름이 **6,081곳 중 0곳**(관심종목 50곳 중 0곳)이다. 채우는 코드는
`apply_toss_names`(`data/universe/persistence.py`)뿐이고 `collection.py:171-180`에 따라 **토스 IP 허용
목록에 등록된 로컬 환경에서만** 실행된다. 재구축 이후 그 작업이 돌지 않은 것으로 보인다. 카드는
`names.name_ko or names.name`으로 폴백하므로 SEC 법인명(예: `COSTCO WHOLESALE CORP /NEW`)이 그대로 나간다.

### C-6. 13F 운용사 1곳이 분기를 건너뜀 — 중간, 의심

7개 운용사 중 6곳의 최신 보고기간은 2026-06-30(접수 8/13~8/14)인데 `0001336528` 한 곳만
2026-03-31(접수 5/15)이다. 제출 기한(8/14)이 5주 지났다. 미제출인지 미수집인지는 EDGAR 대조가 필요하다.
`guru.quarter` 요약이 이 공백을 표시하는지는 확인하지 못했다. 저장한 포지션 합계는 신고 합계와
전부 일치했다(2% 초과 불일치 0건).

### C-7. Michigan 소비자심리 정체 — 중간, 의심

`US_MICHIGAN_SENTIMENT`의 마지막 관측은 2026-07-01이고 마지막 재관측은 **9/14**다. 같은 시점에
`US_M2`는 9/20, `KR_EXPORT`는 9/20까지 재관측됐다. 발표 일정(`release_events`)은 2026-12까지 있다.
8월 확정치와 9월 잠정치가 이미 나왔어야 하는 시점이지만 FRED 원천을 직접 보지 못해 의심으로 둔다.
`US_M2`·`KR_EXPORT`도 마지막 관측이 7월이지만 발표 지연 범위로 보여 결함으로 세지 않았다.

### C-8. ISM PMI 시계열이 정의만 있음 — 낮음, 데이터

`US_ISM_MANUFACTURING`·`US_ISM_SERVICES`는 `macro.series`에 있지만 `provider_series_code`가 비어 있고
관측치 0건, 발표 일정 0건이다(`release_catalog.py:41-42`에 정의만). 수집되지 않는 시계열이 목록에 남아
있는 것 자체가 조용한 결측이다. 핵심 카드 배치(`CORE_LAYOUT`)에는 쓰이지 않는 것으로 보인다.

## 4. 저장 단계

### S-1. `economic_observations`의 일별 재복사 — 중간, 데이터

59,703행 중 **33,212행(56%)** 이 관측일·값이 같고 `vintage_at`만 다른 재복사다. 예컨대 `KR_EXPORT`의
2026-07-01 값 100.45가 9/13부터 9/20까지 **매일 한 행씩** 있다. 평일 신규 적재는 하루 약 290행이다.
`financial_versions`·`earnings_schedule_versions`는 "상태가 바뀔 때만 새 행"인데 이 표만 다르다.
값은 틀리지 않지만 용량과 조회 비용이 조용히 늘고, "이 값이 언제 처음 바뀌었나"를 읽으려면 매번 접어야 한다.

### S-2. 관심종목 시작일이 로컬 날짜 — 낮음, 코드

`watchlists/db.py:78,89,132,134`의 기본 `watch_from`이 `date.today()`다. CLI는 KST 로컬에서 도니, 한국
오전에 종목을 추가하면 시작일이 **전날 미국 접수 공시보다 하루 뒤**가 돼 그 공시가 걸러진다.

### S-3. 수집·저장 코드 자체는 견고하다

정렬 없는 페이지 조회 0건, `ignore_duplicates` 0건, 모든 `delete`가 `count="exact"`를 쓴다. 분할 감지 시
이력 재수집이 기업행위 기록보다 먼저 끝나므로 중간 실패에도 다음 실행이 재수집을 반복한다.
결함은 코드 패턴이 아니라 **값**에 있다.

## 5. 알림 단계

### N-1. 주간 캘린더가 UTC 날짜로 주를 고른다 — 높음, 재현

`earnings_calendar`의 `candidates.py:20,79`, `run.py:78`, `reporting/notifications/earnings_calendar.py:78`이
`date.today()`를 시간대 없이 쓴다. Actions 러너는 UTC이고, 워크플로는 **일요일 23:10 UTC(월요일 08:10 KST)**
에 예약돼 있다. 정시에 시작하면 아직 일요일이라 `week_window`가 **끝나가는 주**를 고른다.

같은 코드에 날짜만 바꿔 재현했다:

| 입력 | 선택된 주 | 후보 |
|---|---|---|
| 2026-09-20(일) — 일요일 23:33 UTC | 2026-W38 | 0건 |
| 2026-09-21(월) — 월요일 01:01 UTC | 2026-W39 | COST 1건 |

최근 5회 실제 시작 시각(UTC): 8/16 23:32(일), 8/23 23:33(일), 8/31 01:20(월), 9/7 00:58(월),
9/14 01:01(월). **5회 중 2회가 일요일에 시작**했다. 다행히 최근 3회는 GitHub의 지연 덕에 월요일에
돌았지만 지연은 보장되지 않는다. 8/31과 9/7 실행은 실패로 끝났고 원인은 확인하지 못했다.
원장은 9/13 이후만 있어 8/16·8/23 실행이 어떤 주를 골랐는지는 확인할 수 없다.

후보가 0건이면 발송 단계를 건너뛰고 성공으로 끝나므로 **그 주 카드가 빠져도 어디에도 드러나지 않는다.**
`week_window`의 독스트링은 "cron이 밀려도 같은 주를 가리켜야 한다"고 하지만 일찍 도는 방향은 다루지 않는다.

### N-2. 카드 EPS가 보고 EPS를 무시한다 — 높음, 데이터

`notifications/earnings_report/charts.py:48-54`와 `reporting/services/earnings/metrics.py:76-85`의
`_eps_diluted()`는 `net_income_to_common_shareholders ÷ shares_fully_diluted_average`로 EPS를 직접
계산한다. 독스트링은 "원천 EPS 컬럼을 보관하지 않으므로"라고 하지만 `financials`에는
`eps_diluted_gaap`가 실제로 있다. 입력 두 컬럼이 C-1·C-2에서 오염돼 있다.

같은 수식으로 관심종목 50곳을 계산해 보고 EPS와 비교했다:

| 종목 | 카드 EPS(코드 수식) | 보고 EPS | 원인 |
|---|---|---|---|
| MCD | **3,321,614.40** | 3.32 | 주식수 스케일(C-1) |
| UNH | **0.07** | 6.04 | 귀속 순이익 오매핑(C-2) |
| BRK-B | 빈칸 | 없음 | 보고 EPS·희석주식수 모두 NULL |
| V | 빈칸 | 없음 | 보고 EPS·희석주식수 모두 NULL |
| XOM | 빈칸 | 3.48 | 희석주식수 NULL |

이 EPS는 전년 대비 증감과 등급 판정(`derive()`)에도 쓰인다. 이번에 보낸 ORCL·AVGO·CSCO 카드는
10% 이상 어긋나지 않았다. **MCD·UNH의 다음 10-Q 카드가 잘못 나갈 수 있다.**

### N-3. `is_estimated`(회사 확정 여부)를 카드가 안 읽는다 — 중간, 코드

수집(`consensus.py:185-195`)·저장·조회(`repository.py:172`)까지 하는데 `schedule.py`에는 사용처가
없다. 세션 감시(`select_session_targets.py:155`)만 쓴다. DB에서 COST·NKE는 `is_estimated = false`
(회사 확정 공지)인데 카드는 항상 "날짜는 확정이 아닙니다"라고 말한다. `schedule.py` 독스트링의
"출처가 확정 여부를 알려주지 않는다"는 스키마 주석과 맞지 않는다. Yahoo 플래그의 신뢰도는 검증하지 못했다.

### N-4. 속보 `fact_at`이 수집 시각을 우선한다 — 중간, 데이터

`earnings_flash/run.py:38`은 `fact_time(flash.get("available_at") or flash["filed_at"])`이고 정밀
카드는 접수일(`filed_at`)이다. 원장에서 속보 3건의 `fact_at`이 2026-09-13 16:54~17:20으로
접수일(9/2~9/10)이 아니라 **재적재 시각**이었다. 기준선(9/13 16:23)을 통과해 억제되지 않았다.
기준선은 "백필·초기 적재가 옛 소식을 쏟아내지 않게" 하는 장치인데, 속보는 재적재만 하면 우회된다
(7일 lookback과 `watch_from`이 상한이다).

### N-5. `total_debt()`가 결측을 0.0으로 접는다 — 낮음, 코드

구성요소가 전부 NULL이면 `sum(v or 0.0 ...)`이 `0.0`을 돌려준다. `_net_debt()`의 `debt is None`
검사(`earnings_report.py:479-481`)는 `total_debt()`가 `None`을 주지 않으므로 절대 참이 되지 않는다.
"부채 없음"과 "부채 데이터 없음"이 구분되지 않아 순부채가 과소(=EV 과소)가 될 수 있다.
최근 979행 중 65행(6.6%)이 이 경로다. 무부채 기업일 수도 있어 어느 쪽인지 가르지 못한다.

### N-6. 한 번 나간 카드는 갱신되지 않는다 — 낮음, 코드

`earnings.flash`·`earnings.report`는 `on_revision="ignore"`(`topics.py`)다. 이번 세션 속보 3건은 매출
예상치·애널리스트 수·매출 서프라이즈가 비어 나갔다(발표 전 실시간 컨센서스가 없어 재구성 예상치를 쓰기
때문). 9/13 이후 수집분이 쌓이면 채워지지만, 그 뒤에도 이미 나간 카드는 고쳐지지 않는다.

### N-7. 포럼 태그 조회 실패 무로그 — 낮음, 코드

`earnings_calendar/run.py:64`의 `_schedule_tags`가 예외를 잡고 로그 없이 `()`를 돌려준다. 태그 없이
발송돼도 어디에도 남지 않는다. 같은 계열인 `strategy/service.py:41`은 경고를 남긴다.

### N-8. Discord 한도 초과 시 영구 포기 — 낮음, 코드

`validate_message`가 한도(내용 2,000자, embed 6,000자 등)를 넘으면 **자르지 않고** 거부하고, 엔진은 이를
재시도 불가로 `abandoned` 처리한다. 종료 코드 1로 드러나므로 조용하지는 않지만 그 알림은 다시 안 나간다.
macro·institutional·investment 빌더는 미리 자르고, 속보·정밀 카드·econ 빌더는 자르지 않는 것으로 보인다.
속보의 자유 텍스트(`guidance_summary`)는 `format_guidance_headline`이 한 줄로 줄여 위험이 낮다고 봤다(미검증).

## 6. 교차 문제

### X-1. "대상 0건"이면 조용히 성공한다 — 높음, 코드

`if not X:`로 시작해 INFO 로그 한 줄(또는 무로그)만 남기고 반환하는 곳이 알림·수집 진입점에서
**43곳**이다. 이번 관심종목 0개가 그 사례였다. 실적 알림 세 곳(flash·report·calendar 후보), 관심종목
fast path(`tickers=0 candidate_ciks=0`), 발표 세션 감시(`selected=0`)가 전부 INFO로만 끝났고
워크플로는 20초 만에 초록색이었다. 그 밖의 예:

- `data/fundamentals/application/sync_recent_filings.py:329`, `refresh_expectations.py:58,172`
- `data/market/application/price_collection.py:121`(추적 종목이 0이면 빈 결과. 다만 원천이 빈 응답을 주면
  예외를 던진다)
- `notifications/earnings_report/candidates.py:145,174,178`, `notifications/macro/core.py:177-181`
  (`"...silent skip (stale)"` — 카드 없이 성공 종료)

`operations/monitoring`은 "예정된 것이 돌았는가"만 본다. "일을 했는가"는 보지 않는다.
관심종목 0개는 `verify_data`의 `watchlist_has_members` 검사가 잡았을 검사인데 실행이 수동이었다(X-2).

### X-2. 값 검증기의 사각지대 — 중간, 데이터

`scripts/verify_data.py`의 불변식 41개가 **전부 통과**하는데(관심종목 추가 전에는
`watchlist_has_members`만 실패했을 것이다) 이 문서의 값 결함은 하나도 못 잡는다. 못 보는 것:

- 표시 컬럼의 충전율(현금 10%, 한국어 이름 100% 결측)
- 자릿수(주식수 스케일)
- 파생 컬럼 간 정합(귀속 순이익 × 주식수 ≈ EPS)
- 항등식 통과율이 아니라 "독립 검증이 안 되는 행" 비율(부채 파생 140/500)

또 `SUPABASE_DB_URL`이 필요하고 "로컬 전용이며 CI에 주입하지 않는다"고 적혀 있어 **어떤 워크플로도
자동으로 부르지 않는다.** 관심종목이 비었을 때 빨개졌어야 할 검사가 아무도 안 돌리는 도구 안에 있었다.

### X-3. 카드 테스트 픽스처가 결함을 가린다 — 중간, 코드

`test_calendar_metrics.py`의 `_snap()`이 `eps_avg`·`eps_analysts`·`revenue_avg`를 픽스처에 넣어 줘서, 실제
리더가 그 컬럼을 고르지 않는 결함이 통과했다. 카드가 읽는 필드는 **실제 리더를 운영 데이터에 돌려서**
"항상 비는 필드"를 확인하는 편이 정확하다. 이 감사에서 그 방식으로 `names.name_ko`,
`flash.revenue_estimate`, `row.total_debt_including_current`가 항상 비는 것을 찾았다.

### X-4. 킬스위치가 떠 있는 하네스에 반영되지 않는다 — 높음(잠복), 재현

- `harness_switch --kill-switch on`(`switch.py:415`)은 `.env` **파일만** 고친다.
- 하네스는 `KillSwitches(os.environ)`(시작 시점 스냅샷, `runtime.py:135`)을 읽고, 자식 프로세스는
  `dict(os.environ)`을 물려받는다(`commands.py`). `load_config`는 `load_dotenv(override=False)`라
  이미 환경에 있는 값이 `.env`의 새 값을 이긴다.
- 임시 `.env`로 재현했다: `off`로 읽은 뒤 파일을 `on`으로 고치고 다시 `load_config`를 부르니 여전히
  `off`였다. 주문 게이트(`control.py:115`)는 `kill_switch_on=False`로 판단한다.
- 제어판 `get_harness_status()`는 값을 **`.env` 파일에서** 읽어(`switch.py:172-174`) "ON"으로 보인다.
- `set_kill_switch`의 메시지는 쓰기에 실패해도 "설정되었습니다"이고(`switch.py:420-424`), 대화형 메뉴는
  `success`를 확인하지 않는다(`harness_switch.py:128-135`).
- 즉시 듣는 것은 `EXECUTION_LOCKDOWN` sentinel 파일(`emergency_stop`)뿐이다.

**현재는 잠복이다.** 점검 시점에 킬스위치 `on`, `TOSS_LIVE_ENABLED=false`, `EXECUTION_LOCKDOWN`·
`MAINTENANCE_HOLD` 파일이 있고 하네스는 떠 있지 않았다. 실주문을 켜기 전에 고쳐야 한다.

### X-5. 시간대 없는 `date.today()` 21곳 — 중간, 코드

전부 알림·데이터·리포팅에 있다(트레이딩·운영은 시간대를 명시한다). 시세 수집은 미국 동부 시간으로
계산해 올바르다(`market_daily.py:73`). 영향이 큰 곳은 N-1과 S-2이고, 나머지는 하루 어긋남 수준이다:

- `earnings_report/candidates.py:44,123`, `earnings_flash/candidates.py:22` — lookback 경계 ±1일
- `macro/core.py:138,181`, `macro/embeds.py:137`, `econ_calendar/embeds.py:65`,
  `reporting/notifications/macro.py:102` — 카드 날짜 라벨·조회 창
- `data/market/persistence.py:311,334,364,371`, `reporting/services/earnings/valuation_history.py:159`

## 7. 확인했고 문제 없는 것

오탐을 다시 파지 않도록 남긴다.

- **시세**: 추적 503종목 모두 마지막 봉이 9/18, 최근 90일 결측 0, 분할일에도 종가가 이어진다
  (조정된 값을 저장). 신규 분할 시 이력 재수집이 기업행위 기록보다 먼저다.
- **정렬 없는 페이지 조회 0건**, `ignore_duplicates` 0건, `delete`는 `count="exact"`.
- **회계 항등식**: 우선주를 더하지 않는 검증기 정의로 360곳 중 불일치 0건. 이 감사 초기에 3건이 보인 것은
  우선주를 이중으로 더한 **점검의 오탐**이었다.
- **공시 커버리지**: 추적 500곳 모두 최근 정기 공시가 있고(가장 오래된 5/29), 처리 상태에
  `processing`·`failed`가 없고, 최근 공시 1,022건 모두 재무 행이 있다.
- **컨센서스·일정**: 추적 502/503곳에 실시간 컨센서스가 있고 14일 넘게 안 보인 곳이 0, 일정 재확인이
  최신(9/19), 예정일이 10일 넘게 지난 채 방치된 곳 0.
- **13F**: 신고 합계와 저장 포지션이 전부 일치.
- **알림 전송**: `unknown`·`abandoned`는 `report_problems`가 종료 코드 1로 올린다. 사전 점검과 실제
  발송은 같은 함수를 쓴다.
- **fail-closed**: 유지·잠금 sentinel은 깨져도 "보류 중"으로 읽는다. 주문 게이트의 킬스위치는 값이
  없으면 켜진 것으로 읽는다.
- **`macro_etl.yml`의 `set +e`**: 부분 실패(종료 코드 2)를 초록으로 두는 대신 수집기가 구조화된
  Discord 경고를 따로 보낸다(웹훅이 설정돼 있다는 전제, 미확인).
- **뉴스 수집**: 종목별 실패를 경고로 남기고 쿼터 소진을 `capped`로 기록한다(소진 시 뒤쪽 종목이
  계속 밀리는지는 미확인).

## 8. 확인하지 못한 영역

- 트레이딩·실행·연구(LLM 경로 포함)의 예외 삼킴 약 70곳, 대시보드 로더 38곳
- 워크플로 36개의 cron·게이트(배선 테스트가 일부 강제)
- 매크로 발표 일정(`release_calendar.py`)·econ 알림의 값, `earnings_report` 카드의 나머지 필드
- `90_reporting.sql` 뷰의 논리
- C-1·C-2·C-4의 SEC 원문 대조, C-6·C-7의 원천 상태

## 9. 권장 조치

우선순위 순.

1. **N-1** 캘린더의 "오늘"을 KST(또는 ET)로 계산한다. 세 곳(`candidates.py`, `run.py`, 리더 기본값)을
   한 함수로 모으고, "일요일 23:33 UTC → W39" 테스트를 둔다.
2. **N-2 + C-1 + C-2** 카드 EPS는 `eps_diluted_gaap`를 우선하고 없을 때만 계산한다. 주식수 검증에
   자릿수 범위(예: 1e5 ~ 3e10)를 넣고 벗어나면 NULL로 격리한다. 오염된 행(MCD·WAT·UNH 등)은
   재처리한다.
3. **X-4** 킬스위치를 sentinel 파일 방식으로 옮기거나 매 tick `.env`를 다시 읽게 한다. 제어판은
   프로세스가 실제로 읽는 값을 보여 주고, 쓰기 실패 시 메시지를 바꾼다. 실주문을 켜기 전에 끝낸다.
4. **X-1** 대상 0건은 WARNING으로 올리고, 잡별 최소 대상 수(예: 관심종목 ≥ 1)를 넘지 못하면 실패로
   끝낸다. 모니터링에 "일을 했는가"(적재 행 수·발송 수) 신호를 더한다.
5. **X-2** `verify_data`를 스케줄에 올리고(로컬 하네스 job), 충전율·자릿수·EPS 정합 검사를 추가한다.
6. **C-3·C-5** 현금 태그 매핑 보강, 토스 한국어 이름 작업을 재구축 뒤 절차에 넣는다.
7. **C-4·N-5** `short_term_debt`에서 유동성 장기부채를 포함하는 태그를 분리하고, `total_debt()`는 결측
   시 `None`을 돌려준다.
8. **N-3** 카드가 `is_estimated`를 읽어 등급에 반영한다.
9. **S-1** `economic_observations`를 상태 변경분만 저장하도록 바꾸고 기존 중복을 접는다.
10. 나머지(N-4, N-6~N-8, S-2, C-6~C-8, X-3, X-5)는 위를 끝낸 뒤 묶어서 처리한다.

## 10. 부록: 재현

읽기 전용 세션(`conn.set_session(readonly=True)`)에서 실행한다.

### 관심종목 EPS 비교 (N-2)

```sql
WITH wl AS (
  SELECT s.cik, min(s.ticker) AS ticker
  FROM universe.securities s JOIN universe.entities e ON e.cik = s.cik
  WHERE e.is_watchlisted AND s.is_active_listing AND s.is_tracked GROUP BY 1
), l AS (
  SELECT DISTINCT ON (f.cik) f.*, wl.ticker
  FROM fundamentals.financials f JOIN wl USING (cik)
  ORDER BY f.cik, f.period_end DESC, f.filing_date DESC
)
SELECT ticker, fiscal_year, fiscal_period,
       round((coalesce(net_income_to_common_shareholders, net_income)
              / nullif(shares_fully_diluted_average, 0))::numeric, 2) AS card_eps,
       eps_diluted_gaap AS reported_eps
FROM l;
```

### 주식수 스케일 (C-1)

```sql
SELECT t.ticker, count(*) AS bad_rows, min(f.period_end), max(f.period_end)
FROM fundamentals.financials f
JOIN (SELECT cik, min(ticker) AS ticker FROM universe.securities
      WHERE is_tracked AND is_active_listing AND cik IS NOT NULL GROUP BY 1) t USING (cik)
WHERE f.shares_fully_diluted_average < 1e5 OR f.shares_fully_diluted_average > 3e10
GROUP BY 1 ORDER BY 2 DESC;
```

### 일별 재복사 (S-1)

```sql
SELECT count(*) AS total_rows,
       count(DISTINCT (series_key, observation_date, value)) AS distinct_values
FROM macro.economic_observations;
```

### 캘린더 주 선택 (N-1)

```python
from datetime import date
from investment_agent.notifications.earnings_calendar import candidates as cc

store = cc._default_store()
for today in (date(2026, 9, 20), date(2026, 9, 21)):   # 일요일 / 월요일
    rows, reference_date, week = cc.collect(store, today)
    print(today, week, [row["ticker"] for row in rows])
```

### 킬스위치 (X-4)

임시 `.env`에 `TRADING_KILL_SWITCH=off`를 쓰고 `load_config(dotenv_path=...)`로 읽은 뒤, 같은 파일을
`on`으로 고쳐 다시 `load_config`를 부르면 값이 `off`로 남는다. 저장소의 `.env`는 건드리지 않는다.
