# 코드 품질 전면 점검 — 정확성·성능·구조·하드코딩

2026-09-20 시점의 점검 결과다. [직전 감사](2026-09-20-silent-wrong-audit.md)(N·C·S·X 항목)가 못 본
영역 — trading/execution/research의 예외 삼킴, 대시보드 loader, 워크플로 36개, macro 발표 일정 —
에서 출발했고, 직전 감사가 이미 다룬 항목은 다시 세지 않았다. 고치고 나면 낡는 문서다:
고친 항목은 "수정됨"으로 표시했고, 남길 가치가 있는 규칙만 해당 영역 문서·테스트로 옮긴다.

## 0. 방법과 한계

| 표시 | 뜻 |
|---|---|
| **확정** | 코드 경로를 끝까지 읽었고, 재현했거나 운영 데이터·SEC 원천 수치로 확인했다 |
| **의심** | 정황은 강하지만 위 수준의 확인을 못 했다 |

- 후보는 AST로 전수 수집했다(소스 720개 파일. `except`가 값·`continue`로 끝나는 곳 417, 그중 광범위 예외 162,
  로그 없는 광범위 예외 74). **후보는 후보일 뿐이다** — 실제로 읽어 보니 `_source_failure(failures, …)`처럼
  실패를 모아 상위에서 올리는 정상 패턴이 다수라 이 숫자로 결함 수를 말하지 않는다. 결함으로 센 것은 전부 코드 경로를 따라간 것이다.
- 값 결함은 운영 DB를 **읽기 전용 세션**(`readonly=True`, `statement_timeout 60s`)으로 조회했고, 원천 대조는
  SEC `companyfacts` 공개 API(읽기)로 했다. 쓰기·발송·하네스 조작은 하지 않았다.
- 영역별 분석은 읽기 전용 서브에이전트가 병렬로 했고, **상위 항목은 저자가 다시 재검증**했다(각 항목에 재검증 여부 표시).
  재검증하지 못한 서브에이전트 발견은 원 수준을 그대로 두되 "미재검증"으로 적었다.
- 기준선: 수정 전 `python -m unittest discover -s tests -t .` = **3,146개 통과(skipped 1), 실패 0** (148초).
  따라서 이후 실패는 모두 이번 작업이 만든 것이다.
- 작업 트리에는 이번 작업과 무관한 미커밋 변경(직전 감사의 C-1·C-2·N-2·N-3 수정, docs 정리, 다이어그램)이 이미 있었다.
  이번에 손댄 파일 중 `gaap_concepts.py`·`policies.py`·`validate_financial_statements.py`가 그중 일부이며,
  이번 변경은 각 파일의 독립된 구간에 더했다.

## 1. 요약

| 구분 | 개수 | 비고 |
|---|---|---|
| 발견 항목(확정+의심) | 약 130 | 원본 분석은 `raw/` 폴더에 보존 |
| 높음 | **20** | 정확. 실주문 안전·사용자에게 가는 숫자·알림 누락에 닿는 것 |
| 중간 | 약 38 | 분류 경계에 따라 ±3 |
| 낮음 | 약 70 | 죽은 코드·중복·잠복 |
| **수정됨(코드)** | **22 + 6** | 아래 표(운영 두 번째 분석 OPS-1·3·4·11, HC-17, 죽은 코드 정리 ST-1 포함) |
| 오탐으로 기각 | 1 | RP-01(Altman Z'' 상수) |
| 사용자 결정 대기 | 그 나머지 대부분 | 2.9에 사유별 정리 |

**수정한 것 (코드·테스트·문서만, 운영 DB·발송·하네스는 건드리지 않았다)**

| ID | 한 줄 | 검증 |
|---|---|---|
| FI-1 | 매출이 ASC 606 하위분이 아니라 총계 태그로 | 14개 테스트 |
| FI-2 | Q4 파생이 음수 매출·capex를 만들지 않게 | 테스트 포함 |
| DB-01 | 대시보드 경로 4곳 오류(하네스 상태·RL 정책이 항상 "없음") | 3개, 주입 확인 |
| NT-02 | 적자 컨센서스에서 달성률 방향 뒤집힘 | 6개, 주입 확인 |
| NT-03 | 한 축만 상회해도 "서프라이즈" 판정(부분) | 위와 동일 |
| RP-03 | 결측 부채·D&A를 0으로 접어 순부채·EBITDA를 좋게 | 4개, 주입 2건 |
| DB-02 | 오류 결과를 TTL 동안 캐시 | 1개, 주입 확인 |
| DB-03 | 실행 화면이 주문 이벤트·대사를 안 채움 | 2개 |
| DA-1·DA-3 | 월간·주간 발표를 15분 감시가 못 봄, 발표 전 예상 없음 | 3개 |
| DA-2 | 자체 예상이 원값 수준으로 저장(CPI MOM=335) | 재현 테스트 |
| DA-10 | 휴일 주 유령 이벤트 | 5개 |
| HC-1 | KR 기준금리 일정 만료가 조용히 빈 목록 | 3개 |
| HC-3 | 토스 동기화가 해제 시각을 덮어씀·무변경도 UPDATE | 2개, 주입 확인 |
| HC-4 | 빈 환경변수가 기본값을 못 받음 | 3개 |
| HC-5 | ENV.md에 없는 환경변수 13개 + 재발 방지 가드 | 주입 확인 |
| HC-10 | DB 이름 리터럴 2개 + 가드가 둘째 인자를 못 보던 사각 | 주입 확인 |
| PB-2 | DuckDB 연결마다 DDL 10문장 재적용 | 3개, 측정 |
| PB-7 | Chromium 누수·임시 파일명 | 1개 |
| SC-01 | actions_budget이 분 올림 과금 무시 | 1개 |
| WF-05 | CI가 선택 의존성 때문에 매번 red(skip 처리) | — |
| OPS-1 | heartbeat가 자동매매 채널 ID 3개를 못 받아 매일 거짓 경보 + 72h 무발송 감시가 꺼져 있던 것 | 가드 추가, 수정 전 실패 확인 |
| OPS-3 | 킬스위치 배선 테스트가 5개 이름만 나열 → 도메인 표 + 전수(17개) | 게이트 삭제 3종 주입으로 실패 확인 |
| OPS-4 | 서드파티 import 가드가 `notify --kind`를 못 따라가던 것 | `jinja2` 제거 주입으로 4건 실패 확인 |
| OPS-11 (=OP-01) | NYSE 휴장일에 Good Friday 누락·2027-12-31 오휴장 | 5개 연도 매일 대조 테스트 |
| HC-17 | 의사 종목 `"CASH"` 선언 4곳·리터럴 30곳을 `portfolio_weights.CASH_SYMBOL` 하나로 | 3개 테스트, 주입 2종으로 실패 확인 |
| ST-1 | 참조 0건 코드 1개·미사용 import 8개 제거 | 관련 테스트 통과 |

수정 후 `python -m unittest discover -s tests -t .`는 본문 6절 참조.

## 2. 항목

### 2.1 fundamentals (FI)

#### FI-1 매출이 총계 태그가 아니라 ASC 606 하위분으로 저장된다 — 리츠·보험·은행  [확정] [높음] [정확성] — **수정됨(코드) · 기존 행 재처리 대기**

- **증상**: `fundamentals.financials.revenue`가 총매출의 0.4~30%인 종목이 있다. 매출은 카드의 마진·성장률·P/S의
  분모다. 마진이 100%를 넘고(ESS 총이익 332M ÷ 매출 2.2M = 149배) 성장률이 기간마다 뛴다.
- **근거**
  - SEC `companyfacts` 대조: ESS 2025-Q2 `Revenues` = **469,833,000**, `RevenueFromContractWithCustomerExcludingAssessedTax` = 2,223,000. DB = **2,223,000**.
    MET 2025-Q2 `Revenues` 17,340M, DB 604M(**29배 과소**).
  - 2026-Q2 기준 총계 태그가 있는 종목 22곳 중 **13곳**이 하위분 저장(ESS 2M vs 489M, SBAC 51M vs 715M, CCI 41M vs 1,008M, AMT 211M vs 2,749M,
    EXR 35M vs 874M, INVH 49M vs 748M, MET 724M vs 19,154M, COF 2,762M vs 15,850M, HIG 111M vs 7,263M, KEY·CFG·DOC·IBKR).
  - 운영 DB에서 "매출 < 영업이익 또는 총이익"인 행 = 영업이익 기준 203행, 총이익 기준 59행(대부분 같은 30여 종목, 이력 전체).
  - 무작위 일반 종목 45곳: 42곳은 저장값 = 총계, 3곳(LDOS·DLTR·PAYX)은 `Revenues`가 0.1~3% 더 큼 — 헤드라인 "총매출"이 맞다(PAYX는 고객자금 이자 포함).
    `Revenues`가 606보다 **작은** 경우는 표본 67곳(위 22 + 45)에서 0건.
- **원인**: `select_semantic_candidates`(`reported_observations.py`)는 최신 공시에 있는 후보 중 **우선순위 숫자가 가장 작은 태그**를 값의 크기와
  무관하게 고른다. `revenue` 정책이 606 고객계약 매출을 10, `Revenues`를 20으로 두어 606이 이겼다. 606은 임대·이자·투자 수익을 뺀 부분집합이라
  리츠·보험·은행에서는 총계의 일부뿐이다. 검증기(`check_core_wide`)는 매출 크기를 보지 않아 통과시켰다.
- **수정**
  1. `gaap_concepts.py` `revenue` 정책: 총계 태그(`Revenues` 10, `RevenuesNetOfInterestExpense` 20)를 606(30·40)보다 앞에 둔다.
     총계 태그가 없는 회사는 606을 그대로 쓴다. 특정 종목 분기·클램프 없이 태그 의미(부분집합 ⊂ 총계)로 푼 것이다.
  2. `validate_financial_statements.py`: 총이익·영업이익이 매출을 0.1% 넘게 초과하면 **매출을 비우고** `revenue_below_profit` anomaly를 남긴다
     (총계 태그가 아예 없는 HBAN·UDR·CPT형이 여기 걸린다 — 틀린 값보다 빈칸). 순이익은 일부러 비교하지 않는다(KKR·EMR처럼 정당하게 매출을 넘는다).
     상수는 `policies.py`의 `PROFIT_OVER_REVENUE_TOLERANCE`.
- **검증**: `tests/investment_agent/data/fundamentals/test_revenue_total_concept.py` 14개(수정 전 7개 실패 → 수정 후 전부 통과), fundamentals 전체 424개 통과.
- **하류 영향(확정)**: `reporting.earnings_surprise.revenue_actual`이 이 값을 그대로 속보 카드 입력으로 흘린다 — 2026 Q1 기준 UDR 3.9M, ARE 0.67M달러(실제는 수억 달러). 총계 태그가 아예 없어 검증기로 비워지는 종목(HBAN·UDR·CPT형)은 재처리 뒤 매출이 빈칸이 된다.
  같은 뷰에서 `revenue_estimate`는 최근 400일 2,173행 **전부 NULL**이라 매출 서프라이즈는 애초에 계산되지 않는다(직전 감사의 "속보 예상 매출 빈칸"과 같은 현상 — 재구성 예상치는 EPS만 만든다).
- **남은 것 — 사용자 결정**: `SEMANTIC_POLICY_VERSION`("v1")을 올리지 않았다. 올리면 기존 행이 전부 "낡은 것"이 되어 다음 정기 실행이
  전 종목 재처리와 `reconcile_wide_history` 삭제(운영 DB 쓰기)를 시작한다. 올리지 않으면 이후 적재분만 새 규칙이고 과거 행은
  재처리 전까지 옛 값이다(직전 감사의 C-1·C-2와 같은 "재처리 대기" 상태). 재처리 시점과 방식(`backfill_history`)은 사용자가 정한다.

#### FI-2 Q4 파생이 음수 매출·음수 capex를 만든다 — 스핀오프 재작성과 기간별 태그 불일치  [확정] [높음] [정확성] — **수정됨(코드) · 기존 행 재처리 대기**

- **증상**: 10-K 접수 행(Q4)의 매출이 음수다. ADM 2024-Q4 **-25.7B**, DLTR 2025-Q4 -5.0B, DD 2025-Q4 -2.5B, WDC 2025-Q4 -1.2B, J 2024-Q4 -1.2B, WELL 2023-Q4 -0.13B.
  같은 행에서 capex도 음수다(DD -150M, DLTR -98.8M, DAL·FIS·HAS·SBAC 등 18행). 전 이력 24행.
- **근거**
  - ADM: Q1·Q2는 총계(`Revenues` 21.8B·22.2B), Q3는 606 하위분(5.99B — 같은 분기 `Revenues`는 19.9B), FY는 606 하위분(24.4B — `Revenues` 85.5B).
    Q4 = 24.4 − (21.8+22.2+5.99) = −25.7B. 기간마다 다른 태그가 선택된 결과라 **FI-1과 같은 뿌리**다. FI-1 수정으로 21.6B(=85.5−21.8−22.2−19.9)가 된다.
  - DLTR: FY 606 = 17.57B(패밀리달러 매각으로 재작성)인데 Q1~Q3는 옛 기준(합 22.5B) — **뿌리가 다르다**(FY만 재작성).
- **원인**: `_q4_duration_value`가 `FY − ΣQ1~Q3`를 부호 검사 없이 냈다(평균 주식수 컬럼만 `value > 0` 검사).
- **수정**: `policies.py`에 `NON_NEGATIVE_FLOW_COLUMNS`(매출·매출원가·R&D·SG&A·capex·자사주·배당 지급·차입 조달/상환)를 선언하고, 이 컬럼의 Q4가 음수로
  복원되면 값을 만들지 않는다. 순이익·현금흐름 총계는 음수가 정상이라 넣지 않았다(`test_a_loss_quarter_is_still_derived…`).
- **한계(의심)**: 재작성으로 FY가 줄었지만 분기 합보다는 여전히 큰 경우 Q4는 음수가 아니라 **실제보다 작은 양수**로 조용히 남는다. 기준 혼합을 값만 보고
  가를 수는 없다 — 재작성 여부는 공시 메타데이터(비교기간 재작성 플래그)가 필요하며 이번에는 다루지 않았다.

### 2.2 trading · execution (TE) — 전부 **미수정, 사용자 결정 대기**

실주문 안전 경계라 이번 작업에서 고치지 않았다(정비 보류·킬스위치·LIVE 게이트는 건드리지 않았고 하네스도 실행하지 않았다). 서브에이전트가 읽기 전용으로 분석했고
**상위 다섯은 저자가 코드로 재검증**했다. 재현은 순수 함수·임시 SQLite·가짜 응답이며 실제 하네스·Discord·브로커는 돌리지 않았다.
설계상 안전한 것은 확인했다 — 킬스위치·live 스위치 읽기(없음·오타 → 닫힘), lockdown 손상 파일(존재만으로 차단), 승인/permit TTL(UTC 정규화),
attempt·`client_order_id` 멱등, reserve-before-submit, 결과 불명 무재전송, 뉴욕 세션 판정, 비중 검증. `trading`·`execution`에 naive `date.today()`는 0건이다.

> **TE-1·2·3·4·5·6·9는 후속 고도화에서 수정했다(9절).** 아래 설명은 수정 전 재현 근거다.
> 승인 이음매는 실제 SQLite 통합, 카드 직렬화는 JSON roundtrip으로 검증한다.

#### TE-1 Discord 승인 버튼을 누르면 언제나 실패한다  [확정·재검증] [높음] [정확성]
- **증상**: 서명된 버튼을 눌러도 `Discord approval was duplicate, expired, or concurrent`가 나고 승인은 `pending`에 머문다. paper·live 모두 승인이 기록될 수 없다.
- **근거**: `execution/approval/service.py:194`가 `action = "approved" if … else "rejected"`를 `decide_approval`에 넘기고, `execution/approval/repository.py:55`는 `action not in ("approve","reject")`이면 `None`을 돌려준다.
  `decide_approval` 구현은 저장소 하나뿐이다(`grep`). 테스트의 가짜 저장소(`test_approval.py:104`)는 `values["action"]`을 상태로 그대로 받고, 실제 저장소 테스트(`test_runtime_storage.py:70`)는 `"approve"`만 쓴다 — 둘을 잇는 테스트가 없다.
- **원인**: 서비스("approved")와 저장소("approve")가 서로 다른 어휘를 쓰고, 가짜 저장소가 서비스 쪽에 맞춰져 있다.
- **해결 방향(하드코딩 없이)**: 포트 어휘를 한 곳(`interaction.action`)으로 통일하고, 가짜 저장소가 실제 계약과 같은 어휘를 검증하게 한다. 서비스↔실제 SQLite 저장소 통합 테스트를 둔다. **사용자 결정 필요.**
- **위험**: fail-closed 방향이라 돈은 새지 않는다. 실주문을 켜는 순간 처음 드러난다.

#### TE-2 승인 카드가 Discord로 전송되지 않는다 — `datetime` JSON 직렬화 실패  [확정·재검증] [높음] [정확성]
- **증상**: `build_approval_card`가 "승인 만료" 필드 값으로 `request.expires_at`(datetime)을 그대로 넣는다.
- **근거**: `approval/card.py:112`, `approval/ledger.py:151`(`expires_at`을 datetime으로 정규화), `approval/discord.py:68` `requests.post(json=dict(payload))` → `TypeError: Object of type datetime is not JSON serializable`. 테스트는 payload를 직렬화하지 않는 가짜 세션을 쓴다.
- **원인**: 도메인 객체를 표시 문자열로 바꾸지 않고 payload에 넣었다.
- **해결 방향**: 카드 조립에서 사람이 읽는 문자열로 바꾼다(사용자가 한국에 있으므로 KST 표기 여부를 정해야 한다). payload를 `json.dumps`해 보는 테스트를 둔다. **사용자 결정 필요.**

#### TE-3 주문 POST가 2xx인데 본문이 JSON이 아니면 원장이 `planned`로 굳고 이후 실주문이 영구 차단된다  [확정·미재검증] [중간] [정확성]
- `brokers/toss/orders.py:432-445`의 `_json`이 `TossOrderApiError`를 던지는데 이는 `TossOrderOutcomeUnknown`도 `ExecutionSafetyError`도 아니라 `live_worker.py`의 except 세 개에 안 걸린다.
  주문 행 `planned`·attempt `submitting`·뒤 주문 `reserved`·intent `executing`으로 남고, `unresolved_orders`(`orders/repository.py:270`)는 `planned`를 포함해 다음 실행을 막지만 `reconcilable_orders`(`:275`)는 제외해 재조정도 읽지 않는다.
- 해결 방향: 2xx 이후 파싱 실패는 결과 불명(`TossOrderOutcomeUnknown`)으로 승격하고, 고아 `planned`를 재조정이 보게 할지 정한다. **사용자 결정 필요.** 방향은 fail-closed지만 주문이 브로커에 살아 있는데 원장이 모를 수 있다.

#### TE-4 계획 단계와 실주문 게이트가 다른 규칙을 적용해, 승인이 소비된 뒤 배치가 중간에 잘린다  [확정·미재검증] [중간] [정확성]
- 매도 한 건이 $5,000을 넘으면(예: AAPL 30주 × $200) `planning.py`는 통과하고(주문 한도를 매수에만 건다) `safety/control.py` 게이트가 SELL에도 건별 한도를 걸어 제출 시점에 막힌다. 승인은 이미 소비됐고 intent는 `failed`.
  `planning.py` 머리 docstring은 "매도는 한도 이하의 자식 주문으로 나눈다"고 하지만 그 코드는 없다. 일일 주문 수·금액 잔여 한도도 `create_order`마다 평가돼 앞선 매도가 나간 뒤 뒤쪽 주문이 막힌다.
- 해결 방향: 승인 소비 전에 게이트 규칙으로 배치 전체를 사전 검증하거나 계획이 같은 규칙을 쓰게 한다. **사용자 결정 필요.**

#### TE-5 News Analyst가 `as_of`와 같은 UTC 달력일의 뉴스만 본다  [확정·재검증] [중간] [정확성]
- `decision/agents/runner.py:67`이 `fetch_external_news(ticker, curr_date, curr_date)`로 시작일=종료일을 넘기고, `vendor/yfinance_news.py:85` `_in_news_window`는 `start(00:00Z) <= pub < end+1일`이다.
  월요일 09:00 ET(13:00Z)에 분석하면 일요일 밤·금요일 장마감 뉴스가 통째로 빠진다. Reddit 수집은 "past 7 days"라 창이 서로 다르다. 오류도 로그도 없다.
- 해결 방향: 하한을 판단 시각 기준 N일 전으로 두고 N을 이름 있는 상수로 둔다. 몇 일이 맞는지는 **사용자 결정 필요**(판단 입력이 바뀐다).

#### TE-6 시장 regime이 낡은 SPY로 계산돼도 오류가 없다  [확정·재검증] [중간] [정확성]
- `risk/regime_budget.py:97-128`의 `regime_from_benchmark_prices`는 `trade_date <= as_of.date()`인 봉의 **개수**만 검사한다. 최신 봉이 32일 전이어도 `NORMAL`이고 위험예산이 평상시 한도로 열린다(흔적은 `source_ids=('benchmark_prices:2026-08-19',)`뿐).
  `as_of.date()`는 UTC 날짜다.
- 해결 방향: 최신 봉이 판단 시각의 직전 거래일보다 뒤처지면 `ContractError`로 드러내고 허용 지연 일수는 이름 있는 정책 상수로 둔다. 목표 생성이 실패로 바뀌는 변경이라 **사용자 결정 필요.**

#### TE-7~TE-16 (낮음·미재검증, 서브에이전트 보고 그대로)
| ID | 요약 | 수준 |
|---|---|---|
| TE-7 | `decision/llm/runtime.py:_external_status`가 본문 전체에서 `"unavailable:"`·`"no news found"` 부분 문자열을 찾아 정상 뉴스를 unavailable로 만든다(예: "services unavailable: users report") | 확정, 낮음 |
| TE-8 | `execution/safety/repository.py:runtime_risk_state` — 오늘 장전 스냅샷이 없으면 나이 상한 없이 옛 스냅샷을 baseline으로 씀, `realized_pnl_usd`가 실현손익이 아니라 `min(자산 변화, 토스 일간손익)`(입출금이 손실로 읽힘), 읽기 메서드가 매 호출 스냅샷을 저장하고 전체를 훑음. `min()`이라 조이는 쪽으로만 틀림 | 확정(코드), 낮음 |
| TE-9 | `live_worker.py` 제출 루프가 주문마다 `RuntimeRiskState.captured_at`을 갱신해 30초 신선도 검사가 직전 주문 하나의 소요시간만 봄(실상한은 permit TTL 120초) | 확정, 낮음 |
| TE-10 | `approval/card.py:_ticket_lines`가 주문 목록을 1,024자에서 자름 — 약 25건을 넘으면 일부 주문이 카드에 안 보이는데 합계 금액은 전체 기준 | 확정, 낮음 |
| TE-11 | `trading/my_portfolio.py`의 `plan_follow`가 `RiskDecision(is_approved=True)`를 스스로 만들고 `DeterministicRiskGate`를 거치지 않음(회전율 한도 없음). 폐루프 원칙(사용자 승인)에 해당할 수 있음 | **의심**, 중간, 구조 |
| TE-12 | `reconciliation/worker.py:classify_remote_order`가 `"CANCEL" in status`를 먼저 봄 — `CANCEL_REJECTED`가 있다면 취소로 분류(토스 enum 원문 미확인) | **의심**, 낮음 |
| TE-13 | `decision/candidates.py:_candidate_held_tickers`가 System 원장을 못 읽으면 경고만 남기고 `[]` — 보유 종목 재분석 우선순위가 건너뛰어져도 정기 분석은 성공으로 끝남 | 확정, 낮음 |
| TE-14 | src 안 참조 0건, 테스트만 참조하는 죽은 코드: `reconciliation/service.py:reconcile_orders`, `orders/lifecycle.py:LifecyclePromotionGate`, `orders/market_state.py:MarketState`, `brokers/repository.py:save_quote_snapshot` | 확정, 낮음 |
| TE-15 | `emergency_stop --state-dir`와 실주문 게이트가 읽는 lockdown 위치가 다르면(기본 `artifacts/ops/investment_harness` 고정) 게이트가 못 봄. 쓰기 경로는 끝까지 못 읽음 | **의심**, 낮음 |
| TE-16 | `decision/analysis.py` 실패 기록이 모든 예외를 `model_name="exhausted"`로 저장 — 원인 구분은 `failure_reason` 문자열에만 있음 | 확정, 낮음 |

**읽지 못했거나 얕게 본 곳**: `portfolio/optimizer.py`·`market_risk.py`·`candidate_ranker.py`·`event_impact.py`·`performance/*`·`evidence/*`·`decision/agents/*`(runner 제외)·`model_pool.py`,
`execution/brokers/repository.py`, `orders/toss_manual.py` 뒷부분. 토스 API 명세가 저장소에 없어 `commissionRate` 단위·`cashBuyingPower` 의미·주문 상태 enum은 확인 불가(퍼센트 단위라면 매수가 영구히 preflight에서 막히지만 fail-closed).
`runtime_risk_state`와 `plan_follow`가 운영 로컬 원장에서 실제로 내는 값은 원장 접근을 하지 않아 보지 못했다.

### 2.3 notifications · reporting · dashboard (NT/RP/DB)

서브에이전트 원본 분석의 전체 목록(확정 18·의심 7)에서, 이 절에는 **재검증을 거친 것만** 옮긴다. 나머지는 2.9 "미처리 목록"에 있다.

#### DB-01 대시보드 경로 상수 4곳이 `src/artifacts/…`를 가리킨다  [확정] [높음] [정확성] — **수정됨**
- **증상**: 하네스 상태·RL 정책 화면이 파일이 있어도 항상 "없음". 원인은 `Path(__file__).parents[N]` 깊이를 한 단계 잘못 센 것 4곳(`dashboard/ops.py`, `app.py`, `app_pages/system.py`, `app_pages/ml_rl_lab.py`). 재현: import한 `DEFAULT_HARNESS_STATE`가 `src\artifacts\…`, `exists=False`.
- **수정**: 경로 SSOT를 `platform/storage_paths.py`의 `harness_state_dir()`·`rl_policy_dir()`로 두고, 쓰는 쪽(`operations/paths.py`·`control_center.py`·`research/commands/continuous_retrain.py`)과 읽는 화면이 같은 함수를 쓴다(대시보드는 `operations`를 import할 수 없어 platform에 뒀다).
- **검증**: `tests/investment_agent/dashboard/test_storage_path_agreement.py` 3개. 위반 주입(`parents[3]` 복원) 시 2개 실패 확인. 수정 후 `DEFAULT_HARNESS_STATE`가 실존 파일 `artifacts\ops\investment_harness\state.json`을 가리킴.
- **주의**: 고치고 나면 화면이 처음으로 실제 하네스 상태(failed 등)를 보여 준다.

#### RP-01 Altman Z'' 상수 3.25 누락  — **오탐(기각)**
- 서브에이전트는 "식에서 3.25가 빠졌다"고 했으나, 경계 2.6(양호)/1.1(위험)은 **상수 없는 식**의 것이고 3.25를 더한 신흥시장형의 경계는 5.85/4.35다. 식과 임계가 짝이 맞는다. 값은 그대로 두고, 같은 오해를 막으려 docstring에 근거를 적었다.
- 교훈: 서브에이전트의 "확정"도 도메인 지식이 걸린 것은 재검증한다.

#### NT-02 속보 달성률이 적자 컨센서스에서 방향이 뒤집힌다  [확정] [높음] [정확성] — **수정됨**
- 달성률 = 실제/|예상|×100이라 예상 -1.00·실제 -0.50(손실 축소)이 -50%로 MISS. 운영 `reporting.earnings_surprise`에서 `eps_estimate<0` 37행 중 20행이 "상회인데 음수 달성률"(재현은 서브에이전트 수치, 정의는 코드로 확인).
- **수정**: `notifications/earnings_flash/surprise.py`에 `compute_surprise`를 한 곳으로 모으고 차트는 `100 + 서프라이즈%`로 그린다(양수 예상에서는 기존 값과 동일 — 테스트 `test_positive_estimate_rate_is_unchanged`).

#### NT-03 속보 판정이 한 축만 상회해도 초록  [확정] [중간] [정확성] — **수정됨(부분)**
- EPS -20% 하회 + 매출 +0.01%가 "🟢 어닝 서프라이즈"로 나갔다. `judge()`가 **모든 축이 같은 방향일 때만** beat/miss를 단정하고 엇갈리면 중립(파랑)이다. 임계(`BEAT_THRESHOLD_PCT`·`MISS_THRESHOLD_PCT`)는 이름 붙인 상수로 뺐다.
- **남은 것**: EPS 기준(GAAP vs adjusted) 불일치를 속보가 무시한다(`reporting.earnings_surprise.eps_basis_match`를 flash 컬럼에 추가하고 불일치면 중립 처리). 정밀 카드와 신뢰 규칙을 같게 할지는 제품 결정이라 보류.
- **검증**: `tests/investment_agent/notifications/test_earnings_flash_surprise.py` 6개, 주입(옛 달성률 공식) 시 1개 실패 확인. 알림 270개·reporting 91개 통과.
- **재발송**: 이미 나간 속보는 `on_revision=ignore`라 고쳐지지 않는다. 재발송 여부는 사용자 결정.

#### RP-03 결측을 0으로 접어 순부채·EBITDA·ROIC를 좋게 만든다  [확정] [중간] [정확성] — **수정됨**
- `total_debt`가 구성요소가 전부 NULL이면 0.0을 냈다(순부채=−현금, 부채비율 0). D&A가 NULL이면 EBITDA=영업이익. 운영 `financials` 18,915행 중 부채 전부 NULL 6.3%, D&A NULL 10.6%.
- **수정**: `financial_row.total_debt`는 구성요소가 없으면 `None`, `_ebitda_ttm`은 D&A가 없으면 `None`, 투하자본도 부채 없으면 `None`. 세 곳에 복제돼 있던 `total_debt` 중 `reporting/services/earnings/metrics.py` 사본은 삭제하고 `financial_row`로 통일(research 사본은 계층상 import 불가라 유지).
- **결과**: 일부 카드의 게이지가 빈칸이 된다(틀린 값 대신 빈칸).
- **검증**: `tests/investment_agent/reporting/test_missing_is_not_zero.py` 4개, 주입 2건 각각 실패 확인.

#### DB-02 캐시가 오류 결과를 TTL(최대 30분) 동안 붙잡는다  [확정] [중간] [정확성] — **수정됨**
- 로더가 예외를 던지지 않고 `DataResult.error`를 돌려주므로 `st.cache_data`가 오류를 그대로 캐시했다. 일시적 8초 timeout 하나가 30분 동안 "조회 실패"로 고정됐다.
- **수정**: `platform/cache.py`의 `cache_data`가 `status == "error"` 결과를 받으면 그 인자의 캐시 항목을 지운다(로더별 수정 없이 한 곳).
- **검증**: `tests/investment_agent/test_cache_does_not_hold_errors.py` — 오류 후 재조회, 정상은 캐시 유지. 지우는 줄을 빼는 주입 시 실패 확인.

#### DB-03 실행 화면이 주문 이벤트·대사 실행을 한 번도 채우지 않는다  [확정] [중간] [정확성] — **수정됨**
- `load_execution_data`가 `order_events`·`reconciliations`를 빈 리스트로만 두어, 화면이 "대사 0회/기록 없음"을 항상 주장했다(현재 로컬 원장이 비어 있어 오늘은 안 드러남).
- **수정**: 로컬 원장(`read_runtime_rows`)에서 채우고(대사는 최신순), 읽기 실패는 빈 이력이 아니라 error로 드러낸다.
- **검증**: `tests/investment_agent/reporting/test_execution_loader_fills_runtime_datasets.py` 2개.

### 2.4 하드코딩·구조 (HC) — 서브에이전트 목록 중 코드 수정이 안전한 것

#### HC-1 KR 기준금리 공식 일정이 2026-11-26에서 끝나는데 만료 보고가 주석뿐  [확정] [중간] [정확성] — **수정됨(검증기) · 2027 일정 전사는 사람이**
- 주석은 "갱신 없으면 degraded로 보고"라 했으나 그 코드는 macro 전체에 없었다. `official_calendar_dates("KR_BASE_RATE", 2027…)`가 예외 없이 `[]`.
- **수정**: 조회 시작일이 전사한 마지막 날짜를 넘으면 `ScheduleContractError`를 던져 `failures`(운영 알림)로 올린다. 날짜를 지어내지 않았다.
- **사용자 조치 필요**: 2026-11-27부터 이 family가 실패로 보고된다. BOK 금융통화위원회 2027 일정을 확인해 `_KR_BASE_RATE_DATES`에 더해야 한다.
- **검증**: `tests/investment_agent/data/macro/test_kr_base_rate_calendar_expiry.py` 3개.

#### HC-3 토스 보유 동기화가 해제 시각을 매번 덮어쓰고 변경 없는 행도 쓴다  [확정·재현] [중간, 잠복] [정확성·성능] — **수정됨**
- 재현(가짜 저장소): 이미 해제된 BBB의 `removed_at`이 동기화 때마다 "지금"으로 갱신, 변경 없는 3행도 UPDATE 3회. 운영은 해제 이력 0건이라 잠복 중이었다.
- **수정**: `sources`가 그대로면 쓰지 않고, `removed_at`은 활성→비활성 전환 때만 찍는다(이미 비어 있던 행은 기존 값 유지). 부수 효과로 무변경 50행 UPDATE(PB-4)도 사라졌다.
- **검증**: `test_watchlist_db.py`에 2개 추가, `continue` 제거 주입 시 2개 실패 확인. universe 109개 통과.

#### HC-4 빈 문자열 환경변수가 기본값을 못 받는다  [확정·재현] [낮음~중간] [정확성] — **수정됨**
- `.env.example`이 4개를 `NAME=`(빈 값)으로 싣는데 `int(os.environ.get(name, "7"))`는 `int("")`로 죽고, 날짜(`GURUS_HISTORICAL_START_DATE`)는 빈 문자열이 그대로 통과했다.
- **수정**: `platform/env.py`의 `env_int/env_float/env_str`(빈 값 = 미설정, 잘못된 값은 변수 이름이 든 오류)로 unguarded 11곳 교체(institutional·macro fetch·SEC gap·fundamentals·trading LLM 설정). try/except로 기본값에 떨어지던 5곳은 손대지 않았다.
- **검증**: `tests/investment_agent/platform/test_env_helpers.py` 3개, data 874개 통과.

### 2.5 성능 (PB) — 측정값 포함

#### PB-2 Research·Intelligence DuckDB가 연결마다 DDL 10문장을 다시 적용한다  [확정·실측] [중간] — **수정됨**
- **측정(수정 전)**: 운영 `research.duckdb` 8.4MB 임시 사본에서 `_connect` 242ms(DDL ≈140ms + 이관 점검 ≈20ms), `upsert_allocation` 1건 255ms. 전략 백필(전략 8 × 60개월 = 480회)이 약 2분.
- **수정**: `platform/db/duckdb.py`가 (파일 신원[dev·inode], 선언 내용 해시)를 프로세스 안에 기억해 **프로세스당·파일당 1회**만 DDL과 옛 스키마 이관(`after_ddl`)을 실행한다. 지우고 다시 만든 파일과 바뀐 선언은 다시 적용한다. 트랜잭션 경계·쓰기 직렬화 락은 그대로다.
- **측정(수정 후)**: 빈 DB 기준 연결당 40.7ms → 15.4ms(2.6배). 운영 크기에서는 DDL 비중이 커서 더 크게 줄 것으로 보이나 **운영 크기 재측정은 안 했다**.
- **검증**: `tests/investment_agent/platform/test_duckdb_ddl_applied_once.py` 3개(1회 적용·바뀐 선언·재생성 파일). research 217·intelligence 38·platform 107개 통과.

#### PB-7 / NT-01 카드마다 Chromium 재기동  [확정·실측] [낮음] — **부분 수정**
- 실측: 1장 1.2초(콜드 3.4초), 재사용 시 0.65초 → 장당 약 0.55초. 실적 시즌 수십 장에 10~30초.
- 브라우저를 프로세스당 하나로 재사용하는 것은 `asyncio.run`을 카드마다 다시 부르는 현재 구조에서 이벤트 루프 수명과 얽혀(브라우저는 만들어진 루프에 묶인다) 이득 대비 위험이 커서 **하지 않았다**. 렌더 진입점을 한 루프로 모으는 리팩터링이 선행돼야 한다.
- **수정한 것**: 캡처 예외 시 `browser.close()`가 안 불려 Chromium이 남던 것을 `try/finally`로, 프로세스마다 달라지던 임시 파일명(`hash()`)을 `sha256`으로. 검증 `test_playwright_capture_cleanup.py`.

### 2.6 data — universe · market · macro · institutional (DU/DM/DA/DI)

서브에이전트가 운영 DB(읽기 전용)와 SEC 공개 조회로 분석했다. 아래 넷은 **저자가 코드로 재검증**했고 수정했다. 나머지는 2.9.

#### DA-1 15분 발표 감시가 월간·주간 발표를 거의 못 본다 — 이벤트를 관측 기간(ref_period)으로 거른다  [확정·재검증] [높음] [정확성] — **수정됨(코드)**
- `releases/db.py::_summary_rows`가 창(`start`~`end`, 발표 시각 의미)을 `ref_period`에 적용했다. 월간 지표는 ref가 전월 1일(CPI 9/11 발표 → 2026-08-01), 주간 청구는 발표 5일 전이라 `due_releases`(now-4d~now) 창 밖이다. 운영 데이터: 최근 발표 5건 중 3건이 창 밖, CPI 첫 저장이 발표 후 약 52시간(daily가 잡음), 청구·산업생산도 다음날 06시대.
- **수정**: `_events_scheduled_within`이 최신 일정 버전의 `scheduled_at`으로 거른다(순수 함수). 키로 직접 찾는 `summaries_for`는 창이 필요 없어 `event_keys` 경로로 분리했다.
- **영향**: 고치고 나면 watcher가 실제로 발표 직후 알림을 낸다 — 이전에는 daily 안전망이 늦게 잡던 것들이다. **알림이 늘어나는 변화**라 새 topic baseline이 필요한지는 배포 전에 확인해야 한다.
- **한계**: `_summary_rows` 연결(events→schedules→helper) 자체는 단위 테스트가 없다(순수 helper만). 운영 조회로 확인하지 않았다.
- **검증**: `test_release_window_by_schedule.py` 3개, macro 171개 통과.

#### DA-3 월간 발표는 발표 전 예상 스냅샷이 없다  [확정] [높음] — **DA-1과 같은 뿌리로 수정됨**
- `snapshot_forecasts`가 `releases_within`(같은 창)을 써서 다음 CPI(ref 2026-09-01)의 예상이 0건, 먼 ref(10/1·11/1)에만 매일 쌓였다. DA-1 수정으로 창이 발표 시각이 되어 함께 해소된다. 그 결과 `market_surprise`·`model_error`가 비던 것도 채워진다.
- 과거 발표의 발표 직전 예상은 PIT상 복원할 수 없다(그대로 둠).

#### DA-2 자체 예상(own_model)이 measure 단위가 아니라 원값 수준으로 저장된다  [확정·재검증] [높음] [정확성] — **수정됨(코드) · 오염 행 정리는 사용자 결정**
- 운영 `forecast_snapshots` 최신: `US_CPI.MOM`=335.09(지수 수준, %가 아님), `US_NFP.MONTHLY_CHANGE`=159,075, `US_RETAIL_SALES.MOM`=773,947. `model_error`가 수십만 단위 쓰레기이고 카드(`embeds.py:47`)와 evidence가 그것을 싣는다.
- **원인**: `snapshot_forecasts`가 primary measure면 원값 이력(`primary_history`), 아니면 자기 과거 예상(`measure_history`, 순환)으로 다음 값을 이었다.
- **수정**: `db.measure_actual_history`가 발표 실제값(`_measure_value`)과 **같은 `calculate_family` 규칙**으로 원값에서 measure 값을 계산한 이력을 준다. 쓰이지 않게 된 `primary_history`·`measure_history`는 삭제했다.
- **검증**: `test_db.py`에 "CPI 지수 100→101→101이면 MOM 이력 [1%, 0%]" 재현 테스트. macro 171개 통과.
- **사용자 결정 필요**: 이미 저장된 오염 `own_model` 행(원값 수준)은 그대로 남아 카드·evidence에 계속 실린다. 정리는 운영 DB DML이다(위 원칙상 하지 않았다). 새 행은 정상 단위로 쌓이고 조회는 최신 행 기준이다.

#### DA-10 주간 지표 ref_period를 "발표일 − 고정 일수"로 만들어 휴일 주에 유령 이벤트가 생긴다  [확정] [높음] [정확성] — **수정됨(코드) · 기존 유령 행 정리는 사용자 결정**
- 추수감사절 주에는 청구 발표가 수요일로 당겨지는데 lag는 5일 고정이라 관측일(토)과 하루 어긋난다. 운영에서 US_INITIAL_CLAIMS 이벤트 ref 2025-11-21(관측 없음, 영구 not_available_yet)과 실제 관측 ref 2025-11-22가 동시에 존재. 최근 400일 유령 12건이고 **미래 일정 4건도 이미 어긋나 있다**(청구 2026-11-20 금요일 등).
- **수정**: `series_config.json`의 각 주간 지표 `schedule`에 `observation_weekday`(청구=토, 모기지=목, EIA=금, 순유동성=수)를 두고, `reference_period`가 공칭 위치에서 **가장 가까운 그 요일**로 맞춘다. 평상 주는 결과가 그대로다(테스트). 값은 요일 하나이고 특정 날짜 분기는 없다.
- **검증**: `test_schedule.py`에 휴일 주 4건, 평상 주 불변, "주간 지표 전부가 요일을 선언" 가드 추가.
- **사용자 결정 필요**: 기존 유령 행 정리(DML), 그리고 미래 어긋난 일정이 다음 `sync_schedules`에서 올바른 ref로 다시 만들어진 뒤 옛 행이 "예정"으로 남는 문제(DA-11, 이동·취소 이벤트를 cancelled로 표시하는 경로 부재).

#### 이 절의 나머지 (미수정 — 2.9 참조)
DI-1(Pershing Square 13F 제출자 교체 → 최신 분기 영구 정체, 이전 감사 C-6의 원인 확정, 알림·채널 선언 동반), DI-2, DA-4·5·6·7·8·11, DM-1·2, DU-1·2.

### 2.7 operations · workflows · scripts (OP/WF/SC)

서브에이전트가 `gh run list`(1,000건, 2026-08-21~09-20)와 순수 함수 재현으로 분석했다. **하네스·실주문 경로라 이번에 고치지 않았다**(정비 보류 파일 `artifacts/ops/investment_harness/MAINTENANCE_HOLD`가 이미 있고 하네스는 09-15부터 정지 상태). 원본: [operations 분석 원본](raw/2026-09-20-ops.txt).

| ID | 요약 | 수준 | 상태 |
|---|---|---|---|
| WF-01/01b | GitHub schedule이 nominal cron보다 중앙값 2~5시간 늦다. `econ_calendar_watch`는 설계 월 348회 대비 실측 약 17회 → "발표 직후 속보"가 3~6시간 늦다 | 높음 | 결정 대기 — 시간 민감 경로를 하네스로 옮길지 |
| WF-04 | `earnings_watch`가 창 밖 시각에 돌아 대상 0건으로 "성공" 종료(BMO 100% 창 밖) | 높음 | 결정 대기 — 안전망 의미 변경 |
| OP-01 | NYSE 휴장 표: Good Friday 누락, 12/31 오휴장, 조기폐장 없음 — **실주문 시각 게이트** | 높음 | **휴장일은 수정됨**(2.7-A OPS-11). 조기폐장은 결정 대기 |
| OP-02 | job 정의에 stage가 추가되면 waiting job 때문에 tick이 `KeyError`로 죽어 재시작 반복 | 높음 | **수정됨**(2차) — 옛 stage 집합의 실행 중 job을 `job_replaced`로 새 실행으로 교체. `test_definition_change.py`, 정의 무시 주입 시 실패 확인 |
| SC-03 | `db_bootstrap`/`db_capacity`의 project ref 확인이 ref를 못 읽으면 통과(DROP CASCADE 경로), `v1_reset`은 확인 없음 | 높음(확률 낮음) | 파괴적 DDL 스크립트라 결정 대기 |
| WF-02 | `econ_calendar_ics`가 Storage 공개 버킷 부재로 하루 2회씩 7일+ 연속 실패 | 중간 | **사용자 조치** — 버킷 생성 |
| WF-03 | `fundamentals_integrity` 8일 연속 red(세그먼트 상태 없는 FDXF·HONA·XOM) | 중간 | fundamentals 적재 문제 |
| WF-05 | CI가 push마다 red: `hypothesis` 미선언, `xgboost`는 3.11 미설치 | 중간 | **테스트를 skip 처리해 수정**. 의존성 선언·CI 파이썬 버전은 결정 대기 |
| OP-03 | adaptive 주기가 시작 시 1회 고정 | 중간 | **수정됨**(2차) — `JobDefinition.interval_provider`로 판정 때마다 계산 |
| OP-04 | heartbeat 스레드가 모든 active job heartbeat를 갱신해 stale 무력화 | 중간 | **정정: 결함이 아니라 절충** — 긴 stage(feature_store 52분) 중 tick이 막혀도 오탐 stale이 되지 않게 한 것. 멈춘 핸들러 감지는 별도 장치가 필요한 설계 과제. 스레드 경합(의심)은 미확인 |
| OP-05 | 일별 job이 매일 실행시간만큼 밀림(완료 시각 + interval) | 중간 | 후속 — 하네스 코드 |
| OP-06 | `TRADING_KILL_SWITCH` 해석 규칙이 4곳에서 다름(안전 방향으로만 어긋남) | 중간 | **킬스위치 — 결정 대기** |
| SC-02 | `verify_integration`이 "0건"과 삼켜진 실패를 OK로 셈 | 중간 | 후속 |
| SC-01 | `actions_budget`이 분 올림 과금을 무시(1,790분/90% vs 출력 1,329분/67%), 스케줄 드롭·이력 창(11일) 미반영 | 중간 | **올림은 수정됨**. 나머지 후속 |
| OP-08 | intelligence job이 모든 예외를 skipped로 삼켜 영구 장애가 안 드러남 | 중간 | 후속 |
| OP-07·09~11, WF-06~09, SC-04·05 | 낮음(SC-04는 **수정됨**(2차): `db_capacity` stdout을 utf-8로 재설정; 잔재 job, 정규식 부분 일치, placeholder step 9개, cp949 콘솔에서 em dash로 중단, `verify_data`가 읽기 전용을 강제 안 함 등) | 낮음 | 후속 |

- 저장소가 **PUBLIC**(`gh repo view`)이라 표준 러너 분은 무료·무제한이다. CLAUDE.md의 "2,000분 넘기면 조용히 안 돈다"는 전제가 이 저장소에는 해당하지 않아 `actions_budget` 판단이 왜곡된다 — 문서 정정 여부는 사용자 판단.
- 워크플로의 KST 시각 주석과 "A 뒤 B" 순서 가정은 nominal일 뿐이다. 순서는 `workflow_run`·concurrency만 보장한다. heartbeat의 "돌았어야 함" 판정도 nominal 기준이라 지연이 창을 넘으면 오경보가 난다(실측 최대 11시간).

### 2.7-A operations — 두 번째 분석(OPS-n)에서 확정·수정한 것

위 표와 별개로 돈 두 번째 읽기 전용 분석(워크플로 22/36·heartbeat·harness 제어)의 결과다. 아래 **OPS-1·3·4·11은 저자가 재현·재검증하고 수정했다.**
하네스 코드(OPS-11)를 고치기 전 정비 보류를 확인했다 — 하네스는 정지 상태이고 `MAINTENANCE_HOLD`는 이미 걸려 있었다(이번 작업이 켜고 끈 것은 없다).

#### OPS-1 heartbeat가 자동매매 채널 ID 3개를 주입하지 않아 일일 점검 카드가 매일 "채널 ID 없음" 경보  [확정·재검증] [중간] [정확성] — **수정됨**
- **증상**: 일일 점검 카드의 `투자-리포트`·`매매-기록`·`투자-승인` 세 줄이 항상 "채널 ID 없음"이라 카드가 늘 주황색이다. 반대로 `투자-리포트`의 `quiet_hours=72`(사흘 무발송 감시)는 `configured=False`로 조기 판정돼 **한 번도 평가되지 않는다** — 하네스 발송 실패를 밖에서 잡을 유일한 감시가 꺼져 있었다.
- **근거**: `monitoring/channels.py` `WATCHED`의 env 16개 중 3개(`DISCORD_CHANNEL_AI_REPORTS/AI_TRADES/AI_APPROVALS`)가 `ops_heartbeat.yml`에 없다. 테스트는 WATCHED↔manifest만 비교했다.
- **수정**: `ops_heartbeat.yml` env에 3개를 추가하고, `tests/test_workflow_wiring.py::HeartbeatChannelInjectionTest`가 "WATCHED의 모든 env가 워크플로에 주입되는가"를 전수로 검사한다(수정 전 3개 누락으로 실패 확인).
- **사용자 조치**: `AI_REPORTS`·`AI_TRADES` 시크릿은 `notify_bootstrap.yml`이 이미 써서 등록돼 있다. **`DISCORD_CHANNEL_AI_APPROVALS`는 어떤 워크플로도 쓰지 않아 등록 여부를 확인하지 못했다** — 없으면 그 한 줄은 계속 경보다. 등록하거나 Actions 점검 대상에서 뺀다.

#### OPS-3 킬스위치 배선 테스트가 5개 이름만 손으로 나열 — 게이트가 있는 17개 중 12개, 킬 변수 3종 중 2종은 무방비  [확정·재검증] [중간] [구조] — **수정됨**
- **증상**: `vars.*_KILL` 게이트를 지워도 테스트가 통과했다. `GURUS_KILL`·`ECON_CALENDAR_KILL`을 언급하는 테스트는 0건, `fundamentals_earnings_watch` 등도 나열 밖이었다.
- **수정**: 접두 → 킬 변수 표(`KILL_VARIABLE_BY_PREFIX`)로 워크플로 전수를 검사한다. 표가 아무것도 못 찾으면 실패하고(공허 방지), 킬 변수를 쓰는데 표가 모르는 워크플로도 실패한다. "Python이 킬 변수를 읽지 않는다"는 검사도 세 변수로 넓혔다.
- **위반 주입(하나씩)**: `institutional_13f`의 GURUS 게이트 삭제 → 실패, `econ_calendar_watch`의 ECON 게이트 삭제 → 실패, `fundamentals_earnings_watch`(옛 나열 밖)의 FUNDAMENTALS 게이트 삭제 → 실패. 복원 후 통과, `.github` 무변경 확인.
- **사용자 결정**: `fundamentals_integrity`는 게이트가 없어(예외 표에 사유와 함께 올림) 킬이 켜진 동안에도 "적재가 멈췄다" 경보를 낼 수 있다. 의도인지 정한다.

#### OPS-4 "진입점의 서드파티 import가 dependency group에 있는가" 가드가 `notify --kind`를 못 따라가 알림 워크플로에서 공허하게 통과  [확정·재검증] [중간] [구조] — **수정됨(가드)**
- **증상**: `notify_fundamentals`·`notify_strategy`·`institutional_13f`의 발송 단계는 `notify --kind X`인데 가드가 보는 서드파티 집합이 빈 집합이었다. producer가 새 서드파티를 모듈 레벨로 import해도 테스트는 초록이고 Actions에서만 `ModuleNotFoundError`로 죽는다 — fundamentals_backfill이 죽은 바로 그 사고.
- **수정**: `_entry_modules`가 워크플로의 `--kind X`를 `notify.KINDS`의 producer 모듈로 풀어 진입점에 더한다. 현재 실제 누락은 없다. **위반 주입**: `notifications` group에서 `jinja2` 제거 → 4건 실패, 복원 후 통과.
- **한계**: `--kind`를 셸 변수로 넘기는 `notify_bootstrap`은 정적으로 못 푼다.

#### OPS-11 (= OP-01) 하네스의 NYSE 휴장일 표가 Good Friday를 빠뜨리고 2027-12-31을 휴장으로 처리  [확정·재현] [높음] [정확성] — **수정됨(휴장일)**
- **증상**: `is_us_market_holiday(date(2026,4,3))`=`False`(열림), `date(2027,12,31)`=`True`(휴장). NYSE는 Good Friday에 닫고, 1월 1일이 토요일인 해의 직전 금요일에는 연다. 이 표는 `SessionWindow`·시장 국면·판단 시작 창·`risk_snapshot`·`reconcile`을 정한다. 실주문 worker는 브로커 캘린더로 다시 거르므로 주문 자체는 브로커 기준이다 — 하네스와 브로커가 개장일에 두 개의 답을 갖고 있었다.
- **수정**: 부활절 계산(Meeus/Jones/Butcher)으로 Good Friday를 추가하고 틀린 12/31 규칙을 제거했다. 새 `test_market_schedule_holidays.py`는 2024~2028 **매일**을 NYSE 공식 휴장 목록과 대조한다 — 수정 전 실패는 Good Friday 5곳과 2027-12-31뿐이었으므로 나머지 규칙(MLK·Memorial·Juneteenth 관측 등)이 5개 연도에서 공식 일정과 일치함이 함께 확인됐다.
- **남은 것(사용자 결정)**: ① 조기 마감(추수감사절 다음 날·7/3·12/24는 13:00 마감)은 여전히 모른다 — `SessionWindow.end`=14:30이라 그날 13:00 이후에도 "열림"으로 본다. ② 1회성 임시 휴장(2025-01-09)은 규칙으로 나올 수 없다. ③ 표 자체를 없애려면 브로커 캘린더나 캘린더 라이브러리(위 4절 OP-01)로 정본을 하나로 만든다.

#### 이 분석에서 나온 나머지 (미재검증·미수정)
| ID | 요약 | 수준 |
|---|---|---|
| OPS-5 | `harness/switch.py:_find_running_harness_pids()`가 Windows 분기만 있어 macOS/Linux에서는 항상 `[]` → `stop`이 "안전하게 정지" 성공을 보고하며 `harness.lock`을 지우고, `emergency_stop`은 lockdown은 쓰지만(주문 게이트 차단) 판단·수집은 계속 돎. 같은 함수의 `except Exception: pass`는 Windows에서도 PowerShell 실패를 "하네스 없음"으로 바꿈. 테스트는 이 함수를 항상 patch해 플랫폼 분기를 실행하지 않음. 해결: 탐색 실패와 0건을 구분하는 반환 계약(`None`=확인 불가). **실주문·긴급정지 경로 — 사용자 결정** | 확정, 높음(macOS 배포 시) / Windows 전용이면 잠복 |
| OPS-6 | 프로세스 생존·종료 로직이 `emergency.py`·`switch.py`에 복사본 두 벌이고 둘 다 Windows `OpenProcess` 실패(권한 거부 포함)를 "죽음"으로 읽음(권한 거부 시나리오는 의심) | 확정(중복)/의심, 낮음 |
| OPS-7 | 하네스의 알림·intelligence 단계 실패가 `skipped`로 접혀 Discord로 안 감 — 밖에서 잡을 감시(투자-리포트 72h)가 OPS-1 때문에 꺼져 있었다(**OPS-1 수정으로 후자는 복구**). 실패 사실을 `reporter.error`로 보낼지는 사용자 결정 | 확정, 중간 |
| OPS-8 | 하네스 stage 실패가 예외 **타입 이름만** 남겨(`CommandExecutionError`) 종료 코드·모듈·타임아웃 여부를 잃음. 자체 예외는 비밀이 섞일 수 없는데 다른 예외와 같이 취급 | 확정, 낮음 |
| OPS-10 | `tech_indicators_backfill`이 계산 결과를 artifact 없이 러너에 두고 버림. `tech_indicators`의 `research-features` artifact는 읽는 곳이 자기 자신뿐(월 168분). 문서 보존 7일↔코드 30일 | 확정(폐기·문서)/의심(소비자 부재), 중간 |

### 2.8 research · intelligence · platform (RS/IN/PF)

원본: [research 분석 원본](raw/2026-09-20-research-audit.txt). **아래 높음 4건은 모두 `FEATURE_VERSION` 승격·재적재·기존 ML champion 무효화가 얽혀 사용자 결정이 필요해 고치지 않았다.**

| ID | 요약 | 수준 | 확정 |
|---|---|---|---|
| RS-1 | 13F `guru_*` feature·후보 신호가 영구 결측 — 읽는 컬럼(`ticker`·`mapping_status`)이 원천 `institutional.positions`에 없다. 테스트 픽스처가 그 컬럼을 직접 넣어 가림 | 높음 | 확정 |
| RS-5 | RL 승격 게이트의 DSR 기대 최대 샤프가 1.11로 고정(기간 샤프 단위 불일치) — 기간 샤프 0.34 정책도 확률 0.0. RL은 challenger 전용 | 높음 | 확정(순수 함수 재현) |
| RS-9 | 복수 주식 종류 기업의 시총·PER이 한 종류 주식수만 써서 절반 — GOOGL PER 8.1(실제 약 17). ALPHA factor·ML 학습에 그대로 들어감 | 높음 | 확정 |
| RS-14 | 2021-09-03 S&P 멤버 505종목 중 82종목이 표본에 없다, coverage 1.0 검사가 못 잡음 | 높음 | 확정 |
| RS-2 | replay 96k행에서 technical·macro·revision 22열 100% 결측(live엔 채워져 학습·서빙 분포 불일치) | 중간 | 확정 |
| RS-3 | label 시작 종가가 UTC 날짜 기준, 장전 snapshot은 as_of 이후 가격 | 중간 | 확정, 미발현 |
| RS-11·12·15 | v5 live snapshot 0건 / 종목 일부 실패가 exit 1로 잡 전체 정지 / `portfolio_evaluations` 생산자 없음 | 중간 | 확정 |
| IN-1 | 뉴스 수집이 0건·전부 파싱 실패여도 ok | 중간 | 확정 |
| RS-4·6·7·8·10·13·16·17, IN-2~6, PF-1~6 | 낮음(HAC lag 19 vs 필요 4, 알파벳순 종목 자르기, TTM 연속성 미검사, sqlite 쓰기 연결마다 전체 DDL 등) | 낮음 | 혼합 |

- 이 절의 RS-1·RS-9는 서브에이전트 분석을 저자가 **재검증하지 않았다**(수치는 원본 기준). RS-5는 순수 함수 재현이다.
- PF-2는 PB-2 수정으로 해소됐다. PF-1(sqlite, 실주문 원장 경로)은 정비 보류 하에서 같은 방식으로 고칠 수 있다.

### 2.8-A 구조 — 죽은 코드·미사용 import (ST)

`src` 전체를 텍스트 토큰으로 세어(문자열 디스패치 `"모듈:함수"`·docs·sql·yml 포함) **정의 외 참조가 없는** 최상위 함수·클래스를 뽑고, pyflakes로 미정의 이름·미사용 import를 훑었다.

- **ST-1 참조가 어디에도(테스트 포함) 없던 것 1개 삭제** — `reporting/notifications/earnings_report.py:database_for_config`. 미사용 import 8개도 제거(`data/fundamentals/repository.py`의 `datetime`·`as_date`, `reporting/notifications/earnings_report.py`의 `date`, `intelligence/infrastructure/db.py`의 상수 1, `scripts/verify_postgres_sql_syntax.py`의 `sys`, `scripts/db_bootstrap.py`의 `re` 등). import·관련 테스트 통과. [수정됨]
- **ST-2 src에서는 부르는 곳이 없고 테스트만 부르는 것 22개** — 지우려면 그 테스트도 지워야 해서 남겼다(테스트 삭제는 이번 규칙상 금지). 후보:
  `fundamentals/domain/services/parse_shares.py:aggregate_company_share_history`, `taxonomy/segment_concepts.py:resolve_concept`, `institutional/.../edgartools_13f.py:edgartools_version`, `macro/commands/macro_refresh.py:_rows_for_series`, `market/persistence.py:clear_id_cache`,
  `execution/brokers/toss/client.py:fetch_exchange_rate`·`orders.py:parse_personal_order_event`·`db.py:latest_paper_account_snapshot`·`latest_order`·`latest_reconciliation_run`, `notifications/renderers/reports.py:render_report`, `research/rl/decision_dataset.py:decision_features`,
  `trading/decision/universe.py:rotate_after_latest_cases`, `trading/evidence/report.py:coverage_rows`·`dossier_sections`·`valuation_contract_rows`, `trading/decision/llm/runtime.py`의 `_no_external_data`·`apply_downstream_api_key`·`_llm_max_retries`·`_stock`·`_indicator`.
  이 목록은 TE-14(실주문 경로 죽은 코드)와 겹친다. **삭제 여부와 그 테스트의 운명은 사용자 결정.**
- **ST-3 `execution/db.py`와 `execution/orders/repository.py`에 미사용 import 약 25개**(`hashlib`·`math`·`ZoneInfo`·`sb`·`RuntimeRiskState` 등) — 모놀리식 `db.py`를 쪼갠 잔재로 보인다. 실주문 경로 파일이라 이번에 안 건드렸다. `execution/contracts.py`의 `__all__`이 "미정의 이름" 둘(`AccountSnapshot`·`ExecutionLimits`)을 싣는 것은 모듈 `__getattr__` 지연 로딩이라 **오탐**이다.
- **ST-4 테스트 격리(관찰)**: 가드 주입 테스트 일부가 `src/investment_agent/…/tmpXXXX/probe.py`를 만들었다 지운다. 다른 세션이 같은 트리에서 테스트를 동시에 돌리면 `test_view_reachability`처럼 src 전체를 순회하는 테스트가 그 순간의 임시 파일을 만나 `FileNotFoundError`로 죽는다(이번 전체 실행의 유일한 오류였고, 단독 재실행은 통과). 결함이 아니라 **한 트리에서 병렬 실행할 때만** 나는 경합이다.
- **ST-5 규칙 14 이름**: `CASH_SYMBOL`의 `symbol`은 규칙 14(종목 컬럼은 `ticker`)의 이름이지만 execution 경계는 canonical broker/API 예외에 해당하고, 상수를 `ticker`로 바꾸는 것은 이번 범위에서 뺐다.

### 2.9 미수정 항목 — 사유별 정리

| 사유 | 항목 |
|---|---|
| **실주문·하네스·킬스위치** | TE-8·11·12·15, OP-01~06, PF-1, RS-12. TE-1~4·9는 후속 고도화에서 수정·검증했다(9절) |
| **재적재·FEATURE_VERSION·ML 재검증** | FI-1·FI-2 기존 행 재처리, RS-1·2·9·14, DA-6 |
| **운영 DB DML(정리)** | DA-2 오염 own_model 행, DA-10 유령 이벤트, DA-4 중복 스냅샷 |
| **DDL / 파괴적 스크립트** | SC-03, PB-6(count 9회 → RPC) |
| **알림 재발송·발송 정책** | NT-04 스레드 생성 정책, NT-08 sending 고아, NT-02·03 이미 나간 카드 |
| **제품·설계 결정** | RS-5 승격 문턱, RS-7, IN-6 정본 경로, WF-01·04, DI-1(거장 CIK 교체). TE-5·6은 9절에서 조회 정책·stale 검증을 정해 수정 |
| **후속(코드만, 위험 낮음)** | RP-02·04·05, NT-01(브라우저 재사용), NT-05·06·07, DB-04·05, HC-2·6·7~9·11~16, PB-1·3~5·8, DA-4·5·7·8·11, DM-1·2, DU-1·2, DI-2·3, SC-02·04·05, OP-07~11, WF-06~09, IN-1~6, RS-3·4·6~8·10·13·16 |

## 4. 하드코딩 목록과 이전 목적지

원본 근거: [하드코딩·성능 분석 원본](raw/2026-09-20-hardcode_perf.txt). 새 `config/*.toml` 층은 만들지 않았고, hard risk limit은 코드에 그대로 둔다.

| ID | 무엇이 어디에 박혀 있나 | 이전 목적지 | 상태 |
|---|---|---|---|
| HC-1 | KR 기준금리 2026 일정 8개(코드) | 코드 catalog 유지 + **만료 검증기** | 수정됨 |
| HC-4 | `int(os.environ.get(name, "7"))` 15곳 | `platform/env.py` | unguarded 11곳 수정 |
| HC-5 | ENV.md에 없는 환경변수 13개 | `docs/ENV.md` + 가드 테스트 | 수정됨 |
| HC-10 | `.table(SCHEMA, "리터럴")` 2곳 | `local_store.py` 상수 + 가드 확장 | 수정됨 |
| DB-01·HC-6 | 하네스 상태·RL 정책 폴더를 여러 곳이 각자 선언 | `platform/storage_paths.py` | 하네스 상태·RL 정책 수정됨. TradingAgents 산출물 4곳은 미수정 |
| DA-10 | 주간 지표 관측 요일이 코드 lag 표에 흩어짐 | `series_config.json`의 `observation_weekday` | 수정됨 |
| HC-2 | regime 임계값 일부가 `RegimeThresholds` 밖 인라인, 분산 임계 0.75가 입력 척도와 안 맞아 분기가 사실상 영원히 거짓 | `RegimeThresholds`(version에 실림) | 결정 대기(임계 변경) |
| HC-7 | cwd 상대 `Path("artifacts/…")` 7곳 | `storage_paths` | 후속 |
| HC-8 | `C:\Windows\Fonts\…` 절대경로 | 폰트 탐색 함수 | 후속 |
| HC-9 | Toss 5·Discord 4·FRED 5·SEC 4곳에 endpoint 각자 선언 | 각 provider 모듈의 단일 상수 | 후속 |
| HC-11·12 | earnings 읽기 경로 둘이 표·컬럼 상수 복제(46 vs 66), `SCHEMA_UNIVERSE` 15곳 재선언 | data owner의 `db.py` 상수 | 후속 |
| HC-13 | 대시보드가 매니저 이름 부분 문자열로 성향 선택(한글 needle "클라만"은 카탈로그 "클라먼"과 달라 죽어 있음) | `MANAGER_PRESENTATION`(CIK 키) | 후속 |
| HC-14 | 정적 coverage 표(호출처 0) | 삭제 또는 reporting reader | 후속 |
| HC-15·16 | 배치 크기 250/500/1000 불일치, palette 5벌(대부분 규칙 15로 의도된 분리) | — | 의심·낮음 |
| HC-17 | 의사 종목 `"CASH"`가 선언 4곳(`portfolio_weights`·`execution/orders/intents`·`notifications/investment/embeds`·`reporting/services/investment/system_portfolio`)에 리터럴 30곳(dashboard·research/rl·operations·trading·execution/market_state) | `portfolio_weights.CASH_SYMBOL` 하나. 표시 계층(dashboard·notifications)은 도메인을 직접 import할 수 없어(`test_repo_conventions`·`test_notifications_guards`가 처음 시도에서 실제로 잡았다) `reporting.services.investment`가 다시 내보내는 것을 쓴다. `execution`은 일부러 자기 사본을 유지(CLAUDE.md 표) — 대신 두 값이 같은지 테스트로 고정 | **수정됨** — `tests/investment_agent/test_cash_symbol_single_owner.py` 3개, 리터럴 재도입·execution 값 어긋남 주입으로 각각 실패 확인 |
| — | 특정 ticker·CIK 리터럴 분기 | 없음. `ticker`/`cik`/`symbol` 비교 리터럴을 AST로 전수 조사해 `'CASH'`(위 HC-17)만 나왔다 — 오류를 종목 하드코딩으로 덮은 곳은 0건 | 확인함 |
| NT-07 | `FLASH_NOTIFY_LOOKBACK_DAYS`·`DASHBOARD_HARNESS_STALE_SECONDS` 음수 검증 없음 | `env_int` + 검증 | 후속(문서는 수정됨) |
| OP-01 | NYSE 휴장 규칙 표를 자체 유지 | 규칙 표 유지(휴장일 수정 + 연도 전수 대조 테스트). `pandas_market_calendars`는 `uv.lock`에 전이 의존으로만 있고 `pyproject.toml`에 선언되지 않았으며 `src`에서 쓰이지 않는다 — 전환하면 조기폐장까지 덮지만 의존성 추가라 | 휴장일 수정됨, 라이브러리 전환·조기폐장은 **결정 대기** |

## 5. 성능 병목 (측정값)

| ID | 병목 | 측정 | 상태 |
|---|---|---|---|
| PB-2 | DuckDB 연결마다 DDL 10문장 | 운영 8.4MB 사본 `_connect` 242ms, 백필 480회 ≈ 2분 / **수정 후 빈 DB 40.7→15.4ms(2.6배)**, 운영 크기 재측정은 안 함 | 수정됨 |
| PB-1 | `build_valuations`(live_shadow)가 종목마다 8~10회 왕복 — 배치 사전 적재가 historical에만 연결됨 | 503종목 재무+주식수 약 79초, 배치 약 21초, 분할까지 약 58~75초 절감 견적 | 후속(결과 동일성 테스트 필요) |
| RP-02 | 발송 대상 1건이어도 전 관심종목 재무·가격을 반복 조회 | `_financial_rows` 2.8초×7회, 가격 이력 9.4초 → 후보 1건에도 30초+ 낭비 | 후속(카드 값 동일성 테스트로 검증) |
| PB-3 | 사후 평가가 케이스마다 SPY 경로·ID 조회 반복 | limit 200이면 약 800왕복(약 67초) | 후속 |
| PB-4/HC-3 | 관심종목 동기화의 무변경 UPDATE 50건 | — | **수정됨** |
| PB-5 | 삭제·갱신 행 단위 5곳 | 빈도 낮음 | 후속 |
| PB-6 | 정합성 점검 `count=exact` 9회 직렬 | 약 7.8초 | DDL 필요 — 결정 대기 |
| PB-7/NT-01 | 카드마다 Chromium 재기동 | 1.2초→0.65초, 장당 0.55초 | 재사용은 안 함(이벤트 루프 수명). 누수만 수정 |
| DA-5 | `_summary_rows`가 호출마다 관측치·예상·일정 표 전체를 읽음 | watcher 1회당 최대 12회 | 후속 — DA-1 수정으로 events 전체를 읽는 양이 조금 늘었으니 함께 봐야 함 |
| — | 기각: `series_config` deepcopy 0.01ms, `ddl_statements` 파싱 1.1ms, `schema()` 반복(스키마별 캐시 이미 있음) | | |

## 6. 확인하지 못한 영역

- trading: `portfolio/optimizer.py`·`market_risk.py`·`candidate_ranker.py`·`event_impact.py`·`performance/*`·`evidence/*`·`decision/agents/*`(runner 제외)·`model_pool.py`.
- execution: `brokers/repository.py`, `orders/toss_manual.py` 뒷부분. 토스 API 명세가 저장소에 없어 `commissionRate` 단위·`cashBuyingPower`·주문 상태 enum은 확인 불가.
- operations: `request_toss_approval`, `security_audit`, `switch` 대부분. 로컬 원장이 실제로 내는 값(`runtime_risk_state`, `plan_follow`)은 원장 접근을 안 해 못 봄.
- 의심으로만 남긴 것: `_multpl` 미확정 월값, 200일선 breadth 생존편향, CBOE 휴장/차단 구분, RP-07~10·NT-08~10, RS-17, IN-3·5, PF-6.
- 이번 수정 중 **연결(wiring)을 운영 조회로 확인하지 못한 것**: DA-1(`_summary_rows` 안의 events→schedules→helper 연결), DB-01의 실제 화면 렌더(경로 값만 확인). 카드 시각 검증(스크린샷)은 하지 않았다.
- 테스트 픽스처가 리더보다 풍부해 결함을 가리는 패턴은 RS-1·TE-1·TE-2에서 다시 확인됐으나 전수 점검은 못 했다.

## 7. 수정 순서

이번에 한 순서: 조용한 오류(DB-01·NT·RP·DA·HC-1·3·4) → 가드·문서(HC-5·10) → 성능(PB-2·7). 구조 위반(계층·죽은 코드) 항목은 대부분 후속으로 남겼다.

**남은 수정의 권장 순서 (영향도 × 위험)**
1. **사용자 결정 없이 바로 가능**: SC-04·02, RP-02(카드 값 동일성 테스트 동반), PB-1, NT-05·06, DB-04·05, HC-7~9·11~14, 죽은 코드 삭제(TE-14·HC-14·DA-8·DM-1).
2. **정비 보류 하에서 하네스 코드**: OP-02(재시작 루프) → OP-01의 남은 부분(조기폐장) → OP-04·05 → PF-1. (OP-01 휴장일은 수정됨)
3. **수정 완료·9절 검증 참조**: TE-1(승인 버튼 어휘 불일치)·TE-2(승인 카드 datetime 직렬화). 실주문 활성화 검증을 대신하지 않는다.
4. **재적재가 필요한 묶음**(한 번에 계획): FI-1·2 재처리, RS-9(시총)·RS-1(13F)·RS-14(멤버 누락), FEATURE_VERSION 승격, DA-2·10 오염 행 정리.
5. **운영 조치**: WF-02(Storage 버킷), HC-1(2027 BOK 일정 전사, **2026-11-27 이전**), DI-1(Pershing Square 새 CIK 반영).

## 8. 검증 결과

**이 세션(FI-1·2, OPS-1·3·4·11, HC-17, ST-1)의 최종 실행**: `python -m unittest discover -s tests -t .` → **3,235개 실행, 통과, skipped 1, 실패 0**(140초). 수정 전 기준선은 3,146개 통과·실패 0이었으므로 **이미 있던 실패는 없었다.**
- 이 세션이 만든 실패가 중간에 있었고 그 자리에서 고쳤다: `CASH` 이전 첫 시도에서 표시 계층(dashboard·notifications)이 `portfolio_weights`를 직접 import해 `test_repo_conventions.test_dashboard_domain_dependencies_only_shrink`·`test_notifications_guards.test_notification_boundary` 2건이 실패했다. 가드가 맞고 내 방향이 틀렸다 — `reporting.services.investment`가 다시 내보내게 바꿨다.
- 중간 실행에서 `test_view_reachability`가 1회 오류를 냈다. 다른 세션이 같은 트리에서 동시에 테스트를 돌리며 `src/…/tmpXXXX/probe.py`를 만들었다 지운 경합이다(ST-4). 단독 재실행과 최종 실행은 통과했다.
- 위반 주입으로 실제 실패를 확인한 가드: 킬스위치 게이트 삭제 3종(OPS-3), `notifications` group에서 `jinja2` 제거(OPS-4), `CASH` 리터럴 재도입·execution 값 어긋남(HC-17). FI-1·2와 OPS-11·OPS-1은 수정 **전에** 테스트가 실패하는 것으로 확인했다.
- `graphify update .` 성공(17,857 노드). 아래 다른 세션의 기록(WinError 5 실패)은 그 시점의 것이고 이 세션에서는 재현되지 않았다.
- **commit·push·운영 DB 쓰기·Discord 발송·하네스 조작은 하지 않았다.** 정비 보류는 이 세션이 만들지도 풀지도 않았다.

### 8-A 이전 세션 기록

- `python -m unittest discover -s tests -t .` → **3,220개 통과, skipped 1, 실패 0**(105초). 수정 전 기준선은 3,146개 통과.
- 중간에 **내가 만든 실패 3건**이 있었고 모두 그 자리에서 고쳤다: ① `metrics._total_debt` 사본을 지웠는데 옛 테스트가 그 이름을 불렀다(공개 `total_debt`로 갱신), ② 새 `platform/env.py`가 platform 허용 모듈 목록에 없었다(선언 추가), ③ `notifications/playwright.py`의 `hashlib`이 알림 import 허용 목록에 없었다(순수 표준 라이브러리라 추가). 이미 있던 실패는 없었다.
- 새 가드·계약 테스트는 위반을 하나씩 주입해 실제로 실패하는 것을 확인했다(DB-01·NT-02·RP-03·DB-02·HC-3·HC-5·HC-10). DA-1(창 선택)·DA-2(단위)·DA-10(요일)·HC-1·PB-2는 순수 계약 테스트이며 옛 방식으로 되돌리는 주입은 하지 않았다.
- `graphify update .`는 `graphify-out/.graph.tmp.json` 교체에서 **액세스 거부(WinError 5)로 실패**했다(파일이 열려 있거나 다른 프로세스가 잡고 있는 것으로 보인다). 그래프는 갱신되지 않았다.
- 작업 트리에는 이 감사와 무관한 다른 세션의 미커밋 변경(`execution/approval/*`, `orders/*`, `safety/control.py`, `brokers/toss/orders.py`)이 있다. 이번 작업은 그 파일들을 건드리지 않았고 commit도 하지 않았다.


## 9. 투자 시스템 고도화 — 실행 경로·연구·결정·인계

목표는 실행 경로를 기준선으로 삼아 측정·승인·주문 결과 해석의 재현 가능한 결함을 수정하는 것이다.
안전 경계와 기존 엔진의 공개 계약을 유지하며, 성과 우월성이 증명되지 않은 새 전략은 연구 후보로 둔다.
사용자가 분석·설계·수정·검증을 자율 진행하도록 요청했다. 본 감사 문서에 연구·검증·인계를 통합한다.

- [x] runtime 호출 → 입력/provenance → 저장 → 소비자를 Data부터 평가까지 추적한다.
- [x] covariance/beta/tail risk의 결측 날짜 정렬과 최초 손실의 drawdown 계산을 실패 테스트로 검증한다.
- [x] benchmark regime의 stale/미확정/오염 가격을 재현하고 기존 시장 시간 계약으로 차단한다.
- [x] 승인 서비스 → 실제 SQLite 저장소, 카드 → JSON 직렬화 이음매를 회귀 테스트로 연결한다.
- [x] 주문 POST의 성공 HTTP/파싱 실패를 결과 불명으로 보존하고 재전송하지 않는지 검증한다.
- [x] 계획 단계의 매수·매도 한도를 실행 한도와 일치시키고 기존 계약·문서를 정리한다.
- [x] 최신 TradingAgents/Qlib/FinRL/공분산·최적화 연구를 1차 출처로 비교한다.
- [ ] 단위·통합·대표 오프라인 재현, 전체 unittest, compileall, 문서·아키텍처 검사를 실행한다.
- [ ] 채택 근거·미검증 성능·실패 시나리오·연구 backlog·다음 작업·마지막 검증을 기록한다.

실행은 현재 세션에서 직접 진행한다. production/live 주문·외부 알림·데이터 삭제·자동 승격은 수행하지 않는다.
검토 중인 주요 입력은 중간 결측 봉, 최초 급락, 월말까지 낡은 SPY, 2xx 비JSON 주문 응답,
서명된 approve/reject 이벤트와 반복 소비다. 테스트는 임시 SQLite와 가짜 broker 응답만 사용한다.

### 9.1 범위·작업 상태의 해석

이 절은 2026-09-21 고도화 세션의 기록이다. 0~8절은 병행된 코드 품질 감사의 결과이며 그 테스트 수·
운영 데이터 측정값을 이번 세션의 결과로 합산하지 않는다. **TE-1·2·3·4·5·6·9의 최신 상태는 아래 변경 표를
우선한다**(TE 번호별 세부 범위는 원문과 대조). 6절의 미열람 목록 중 optimizer/market_risk/agents/
performance/evidence는 이번에 실행 경로를 추가 추적했다. 모든 provider·실계좌·모든 시장 구간을 실행 검증한 것은 아니다.
다른 세션의 data/dashboard/platform 변경은 보존했고 광범위 staging·commit은 하지 않았다.

시작 시 harness STOPPED, maintenance ON, kill ON, live false, lockdown true를 확인했다.
정비 보류 사유를 `repository upgrade: runtime audit and offline validation`으로 기록하고 유지했다.
실주문·알림 발송·원격 DB 쓰기·credential 변경·기존 학습 모델 교체는 하지 않았다.

### 9.2 실제 runtime와 저장 경계

아래 경로는 `src/investment_agent/` 기준이다. 존재 여부가 아니라 entry point와 호출·소비 경로를 확인했다.

| 단계 | 실제 연결 | 입력·계산·저장·소비자 | 연결 여부/한계 |
|---|---|---|---|
| Data | data 하위 ETL/commands → provider → db/repository | SEC 공시 시각, 일봉 완료·ingested 시각, macro 관측·공개 시각 → Supabase; `select_all_paged` 기반 대량 조회 → evidence/feature | 원천별 PIT 품질이 같지 않다. 뉴스 live cache는 historical PIT 자료의 대체물이 아니다 |
| Feature/Factor | research/features + `research/factors/core.py` → research/storage/repository | 버전·available_at·source_ids·결측 mask가 있는 feature snapshot, quality/balance_sheet/growth/value/revision/momentum 순위 → 로컬 DuckDB | `features/factors.py`는 compatibility reexport. 이번 세션에서 새 엔진으로 갈아끼운 것이 아니다 |
| Candidate | factor 후보 선택 + `trading/decision/candidate_ranker.py` → analysis | 품질·순위·보유·분석 경과시간 → LLM 분석 큐; 투자 후보와 분석 우선순위는 다른 계약 | ranker 점수 자체는 주문·portfolio weight가 아니다 |
| LLM Research | `operations/adapters/trading.py` → `decision/analysis.py` → ContextBuilder → TradingAgentsRunner → local orchestrator → decision engine | as-of evidence bundle → 역할별 보고/토론 → SecurityProposal; evidence ID·ticker·시각·schema 검증, 한 번 repair → Trading 저장소 | 원격 LLM 연결은 mock으로 검증. 자유문장 역할 출력이 모두 개별 typed evidence contract인 것은 아니다 |
| ML Research | `research/commands/ml_challengers.py` → datasets → purged split → training/baseline → evaluation/alpha | 시간순 train/validation/OOS, forward_end로 purge, embargo → 모델 상태·feature/label manifest·OOS 통계 → candidate artifact | 후보 추천은 active 파일을 쓰지 않는다. universe/PIT 오염을 split만으로 해결하지 못한다 |
| ML Serving | 명시적 adopt → active_ml_model.json → `ml_serving.champion_forecast` | 전체 단면의 같은 날짜 PIT feature로 결측 대체 → 재로딩 모델 → 종목별 초과수익과 OOS 근거 | stale feature/오류/구형 IID artifact는 unavailable → factor fallback. active 파일 자동 변경 없음 |
| Alpha | `trading/system/engine.py::run_system` → `decision/alpha.py` | 품질 통과 상위40+보유; IC(초기 .04)×20일σ×순위 z; ML은 ±σ 절단 후 측정 신뢰도 s로 결합; 논지는 거부권/소폭 tilt | 방향 일치 confidence는 확률 아님. 긍정 논지 tilt에는 LLM 자기평가 confidence가 여전히 관여 |
| Portfolio | `system/target.py::build_target` → portfolio/optimizer | 260일 가격, 20일 covariance, 거래비용, 현 비중/고정 보유, sector/beta/factor 제약 → CLARABEL convex solve → weights와 input/policy hash | force_exit를 재량 turnover에서 분리. factor exposure 오류 시 해당 제약 없이 재시도하는 광범위 fallback은 후속 개선 대상 |
| Risk | `risk/regime_budget.py` → risk/budget → tail fit → RiskGate | SPY 추세·vol/drawdown, macro, CVaR·충격 시나리오 → 노출 축소/신규 증가 제한 → target 재검사 | 마지막 위험 한도는 결정적. hard limit 변경 없음. 휴장 달력 기반 정확한 freshness는 후속 |
| System | `system/engine.py` mark → rebalance → save | System mark/target/model artifact/run/제안/risk decision 저장; 7일 주기 또는 논지 붕괴 재평가 | target 실패는 failed 기록·기존 target 유지. 유지가 현재 보유의 안전을 보장하지는 않는다 |
| Order planning | execution/orders planning → intent → snapshot/handoff | 승격된 System identity + 독립 실계좌 snapshot → 실행 가능 정수 수량·LIMIT 가격·manifest/client_order_id | System 목표 생성은 주문 권한이 아니다. 한도 초과 매도도 승인 전에 거부 |
| Approval/Execution | approval service → repository(SQLite) → live_worker → safety → TossOrderApi | 서명 approve/reject, 원자적 1회 consume, fresh quote/account/session 확인 → 예약/event 원장 → POST | 사용된 approval+manifest 밖 주문 금지. 일일 총예산은 consume 전 검사, 각 POST도 검사 |
| Ledger/Reconciliation | order attempts/events + execution reconciliation → broker open/detail → local storage | unknown/partial/submitted/terminal 상태, broker ID·수량 대조, incremental fill, mismatch 시 차단 | broker ID 없는 unknown은 자동 재전송·자동 종결하지 않음. 수동 조사 필요할 수 있음 |
| Evaluation/Learning | decision evaluator/memory + trading/performance/service·ledger·attribution + system_validation | 만기 가격으로 논지 평가; 계좌·execution_mode별 fill/PnL attribution; 평가 완료 case만 기억; challenger/ablation은 research artifact | memory는 최종 structuring prompt에 연결됨. 개별 analyst post-mortem 학습, 지속 drift 자동 보정, 완전한 arrival-price TCA는 미완성 |

Trading source는 원천 Supabase와 로컬 Trading 저장소를 repository에서 조합하고, Research 산출물은 DuckDB,
주문·승인·대사는 Execution SQLite에 둔다. 정확한 테이블 소유권은 [STORAGE_MAP](../../STORAGE_MAP.md)을 따른다.
`stage / execution_mode / source_kind`를 합치거나 “Paper 성과=Live 실행 허가”로 바꾸지 않았다.

### 9.3 TradingAgents 실체 검증

`decision/agents/runner.py`는 `run_local_graph`를 직접 호출한다. `orchestrator.py`의 실제 순서는
Market → Fundamentals → News → Sentiment → Macro → Bull/Bear → Research Manager → Trader →
Aggressive/Conservative/Neutral Risk → Portfolio Manager다. pyproject와 이 경로에서 외부
`tradingagents`/`langgraph` import나 설치본 monkey patch는 찾지 못했다. dependency reinstall로 로컬 그래프가
사라지는 구조는 아니다. constitution의 옛 upstream 순서 설명만 실제 코드에 맞췄다.

Analyst 5종은 evidence callback을 받는다. analyst/debate는 주로 텍스트, Trader/PM은 구조화 출력,
최종 engine은 SecurityProposal·evidence ID를 검증한다. memory_text는 runner 내부에서 역할에 전달되지 않고
최종 구조화 프롬프트에서 쓰인다. 명시적 falsification-condition 필드, 역할 간 모순의 기계적 검증,
confidence calibration, 실패 기억의 analyst별 귀속은 아직 없다. agent 수를 늘리거나 upstream graph로
복귀할 근거는 없다. 같은 evidence와 model budget으로 역할 제거 ablation을 먼저 수행한다.

### 9.4 영역별 판단과 실제 변경

| 영역 | baseline/실제 문제 | 최종 방식·판단 | 수정 위치 | 검증·교체 단위 |
|---|---|---|---|---|
| Data/Feature/Factor | PIT·rank·결측 mask는 이미 있음. 전 provider 정확성·survivorship·재무 재처리 잔여 문제 존재 | **유지**, 원천 품질은 앞 절의 backlog로 관리; 새 factor 무작정 추가 안 함 | 이번 고도화의 직접 수정 없음 | FeatureSnapshot/FactorModel/version 단위, OOS IC·coverage로 다음 후보 비교 |
| ML uncertainty | 겹치는 20일 label에도 IC×√n의 IID t → 가짜 유의성 | **부분 교체**: HAC t + IID 하한 + 방법/기간 metadata, 구형 근거는 서빙·adopt 거부 | evaluation/alpha.py, training/baseline.py, ml_inference.py, ml_serving.py, commands/adopt_ml_model.py | Bartlett 이중합 독립 oracle, 학습→채택→서빙 계약 테스트; OOS 통계 단위 교체 |
| ML 모델 | naive/ridge/LGBM/XGB 재로딩, purged challenger | **유지**; 새 모델 우월성 근거 없음 | 위 검증 근거만 변경 | 동일 데이터/split/cost의 walk-forward 필요 |
| RL | state=feature/mask/weights, action=logits→투영 long-only weights, reward=수익·초과수익−위험·turnover·집중도; forward-return simulator | **Research 보류**, System target의 실제 weight controller가 아님 | 없음 | 비중 환경은 fill/호가 simulator가 아니다. 비용·부분체결 모델 없이 FinRL로 교체 안 함 |
| LLM | native graph; 같은 날짜 뉴스 요청으로 주말 사건 누락 | **내부 개선**: 7일 조회 창, runner version 변경 | decision/agents/runner.py | Monday lookback/실제 callback 테스트; runner + SecurityProposal 경계 |
| Alpha fusion | factor+ML 연속 혼합과 논지 거부권. selfconfidence/상관된 근거 중복은 미보정 | **유지**, calibration·disagreement shrinkage는 연구 | docs/INVESTMENT_SYSTEM.md 설명 수정 | ExpectedReturnSignal; mean-variance risk 권한과 분리 |
| Covariance/tail | 개별 수익률의 끝 날짜만 교집합 → 1일/2일 수익을 같은 행에 놓음; 첫날 손실 DD 누락 | **내부 개선**: 공통 구간의 가격 날짜 축 동일성 확인 후 수익 계산, wealth=1 시작 | portfolio/market_risk.py | 중간 봉 누락 거부·다른 상장 시작 허용·최초20% 급락 재현; covariance/risk 함수 |
| Portfolio | LW shrinkage+CVXPY 이미 있음; beta constraint가 audit input hash에서 빠짐 | **내부 개선**: 실제 beta 벡터·예산 hash 포함, 최적화 알고리즘 유지 | portfolio/optimizer.py | beta만 변경 시 hash 변경, 대소문자 정규화 동일 hash; optimize 계약 |
| Regime | SPY 마지막 날짜 TTL 없음, 미확정/비정상/중복 close 위험 | **내부 개선**: bar_available_at/cutoff, 4 calendar-day 허용, invalid/conflicting 거부, provenance 저장 | risk/regime_budget.py, risk/budget.py, system/target.py | stale30일·intraday·휴일 gap·오염 테스트; regime v2/System target v3 |
| Approval | 서비스는 approved/rejected, 실제 repo는 approve/reject 요구; datetime 카드 JSON 실패 | **내부 개선**: 명령 어휘 그대로 전달·Discord timestamp 문자열 | execution/approval/service.py, card.py | 실제 SQLite approve/reject·중복·consume 1회, json roundtrip |
| Planning/budget | oversized sell 계획은 통과하나 실제 안전 검사에서 거부; 일일 한도 실패가 승인 소비 뒤 발생 | **내부 개선**: 매수·매도 동일 한도, batch 예산 사전검사와 POST별 공통 검사 | orders/planning.py, live_worker.py, safety/control.py | 과대 매도·일일 수/금액 소진 시 consume/POST 0회 |
| Broker mutation | 2xx nonJSON 응답을 단순 API 오류로 처리해 접수 불명 의미 유실 | **내부 개선**: create/modify/cancel을 outcome_unknown으로 분류 | brokers/toss/orders.py | nonJSON/list/null·timeout·명시 reject, 불명 응답 재전송 없음 |
| Runtime freshness | 첫 POST 후 재조회 없이 risk captured_at 갱신 → 두 번째 주문에 오래된 값 허용 | **내부 개선**: 관측 시각 보존 | orders/live_worker.py | 20초 첫 주문·40초 두 번째 주문, TTL30초: POST 1회 후 stop |
| Ledger/TCA/Learning | event ledger·partial fill·reconciliation·case evaluation 있음, 학습/주문성과 귀속은 제한적 | **유지**, full TCA·drift/calibration/postmortem는 연구 | 이번 직접 변경 없음 | event/fill/평가 artifact 단위. 실브로커 장애 복구 drill 미실행 |

교체 seam은 기존 함수·dataclass·artifact 경계다. 새 abstract factory/registry/framework는 추가하지 않았다.
Data provider 교체는 row provenance/availability를, broker 교체는 command/receipt/reconciliation 의미를
보존해야 한다. target.py의 데이터 중복 조회와 broad fallback은 아직 결합이 남은 부분이다.

### 9.5 외부 연구 기록과 채택 판단

조회일 2026-09-21. `main`/`latest` 링크는 가변 참조다. 아래는 공식 구현/논문을 읽어 적용 가능성을 비교한 것이며
해당 프로젝트의 수익률 주장을 재현한 결과가 아니다. 새 외부 의존성은 추가하지 않았다.

| 후보·1차 출처 | 실제 아이디어/가정 → 우리 문제와 비교 → 결정 |
|---|---|
| [TradingAgents GraphSetup](https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/graph/setup.py), [graph runtime](https://raw.githubusercontent.com/TauricResearch/TradingAgents/main/tradingagents/graph/trading_graph.py) | StateGraph/ToolNode·역할별 route·외부 tool 구성. 우리 repository-owned 고정 순서와 bounded evidence를 대체할 필요 없음. upstream memory/tool 확대는 PIT·권한 계약을 자동 보장하지 않음. **미채택**, 역할 ablation만 연구 |
| [Qlib workflow](https://qlib.readthedocs.io/en/latest/component/workflow.html), [평가 코드](https://raw.githubusercontent.com/microsoft/qlib/main/qlib/contrib/evaluate.py) | data/model/record/backtest 분리, 비용 포함 수익 평가. 우리 manifest/후보/명시적 adopt와 양립. framework 이식은 저장소·PIT 중복 위험. **유지**, 동일 split export/benchmark adapter는 연구 |
| [FinRL environment](https://finrl.readthedocs.io/en/latest/finrl_meta/Environment_layer.html), [논문](https://arxiv.org/abs/2011.09607) | 상태·행동·보상과 비용/risk control을 환경으로 둠. 우리 weights environment와 유사하지만 실주문/부분체결의 증명은 아님. **Research-only**, live RL 미채택 |
| [Ledoit–Wolf constant-correlation shrinkage](https://ledoit.net/honey.pdf) | sample covariance 추정 잡음을 구조적 target으로 축소. 기존 구현이 이미 이 방식이며 테스트로 PSD/대각 보존 확인. estimator 교체보다 잘못 정렬한 수익률 수정이 우선. **유지**; EWMA/nonlinear shrinkage는 같은 panel에서 후속 비교 |
| [statsmodels HAC 공식 문서](https://www.statsmodels.org/dev/generated/statsmodels.stats.sandwich_covariance.cov_hac.html) | 연속·등간격 시계열의 Bartlett 자기상관 보정. h일 label의 IC 독립성 가정을 완화하는 계산을 NumPy로 **채택**, IID 분산 하한은 우리 보수 정책. 일별 IC 누락/불규칙 간격·구조 변화·다중 탐색 편향까지 해결하지는 않음 |
| [Cvxportfolio 비용](https://www.cvxportfolio.com/en/1.3.1/costs.html), [portfolio 논문](https://www.cvxportfolio.com/en/1.5.0/_static/cvx_portfolio.pdf) | 거래/보유 비용·예측 오차를 최적화에 반영. 이미 covariance/half-spread/turnover 있음. market impact·forecast-error penalty는 데이터 추정과 ablation 필요. **Research-only**, framework 전면 교체 안 함 |
| [Nautilus reconciliation](https://nautilustrader.io/docs/latest/concepts/execution/reconciliation/) | broker 상태와 내부 이벤트를 맞추고 불명 상태를 조사하는 운영 구조. 기존 원장 경계 유지, **응답 해석 실패도 unknown이라는 의미를 채택**. broker 멱등성 확인 없이 범용 retry를 이식하지 않음 |

### 9.6 실패 상황: 현재 반응·취약점·fallback·복구

아래는 코드 경로 분석이다. 회귀 테스트로 실행한 행은 검증 열에 표시했고 나머지는 전체 시장 구간 실험을 대신하지 않는다.

| 상황 | 현재 반응/취약점 | 개선·fallback·복구 | 검증 |
|---|---|---|---|
| 강세·저변동 | sigma 기반 기대수익·risk budget, 작은 추정 위험이 낙관적일 수 있음 | 집중/sector/beta hard cap 유지; risk floor/EWMA는 OOS 비교 후 | 기존 optimizer/risk 단위 |
| 약세·급락 | regime 노출 축소/증가 금지, drawdown/tail gate | 첫날 손실 포함; target 실패는 새 목표 발행 중단. 별도 execution lockdown 유지 | 최초 급락 회귀 |
| 횡보·급반등 | 재평가 주기+1%p no-trade band, 회복 지연/whipsaw 가능 | 손실 방어 해제의 비용·회복속도 ablation; 임계값 임의 증설 안 함 | 역사 구간 비교 미실행 |
| 고변동·correlation spike | LW covariance·vol/correlation·CVaR·충격 시나리오 | 정렬 오류 차단. 일별 추정은 intraday 급변 지연, shadow stress replay 필요 | 정렬/기존 tail 테스트 |
| 금리 충격·거시 이벤트 | macro risk budget와 ETF proxy stress, Macro Analyst | 독립 proxy beta는 공동 factor model이 아님; 사건별 손실 귀속 연구 | 기존 macro/risk 테스트 |
| 기업 악재 | negative/broken thesis가 block_increase/force_exit | 뉴스 7일 조회; 출처 없는 주장 거부, stale 논지 TTL; 실제 탐지 민감도는 미측정 | runner/engine 회귀 |
| liquidity stress | half-spread·거래량 비용/한도, LIMIT 주문 | impact와 체결 확률 추정 필요; 주문 분할·추격 자동화 보류 | 실제 shortfall 미측정 |
| factor reversal | factor exposure 제약·다변화·LLM veto | 동일 정보의 factor/ML 중복 및 exposure fallback 공개; IC 안정성/중립화 ablation | 연구 미실행 |
| missing data | feature mask/단면 imputation; held 신호 부재는 고정 | 중간 가격 누락은 Risk ContractError, 수익률 보간 안 함; 데이터 복구 후 재실행 | 중간 봉 누락 회귀 |
| contaminated data | 유한값·양수가격·evidence 계약 | SPY invalid/conflicting close 거부; 원천 정정 이력·다른 종목 전체 검사는 backlog | NaN/음수/중복 테스트 |
| stale data | feature TTL·quote/account TTL, SPY TTL 없었음 | finalized bar+최대4일 SPY TTL; state 관측시각 보존; 새 관측 뒤 새 계획/승인 | stale30일/20→40초 테스트 |
| API outage | 데이터/ML unavailable, target 불가 시 기존 목표 | provenance·failure 기록; 충분한 자료 복구 후 재계산, 누락을 0으로 대체하지 않음 | mock 경로, 외부 outage drill 없음 |
| model drift·ML confidence collapse | 정기 challenger, OOS 신뢰도 미달 시 factor fallback | IID 구형 근거 불허. 실제 온라인 drift 감지/동적 calibration은 아직 아님 | 구형 artifact 거부 |
| LLM failure | 제한된 repair 뒤 failure 저장, 새 논지 없으면 신규 진입 제한 | 모델 버전별 실패율/비용 관측, role ablation 우선 | 기존 engine 실패 테스트 |
| contradictory agents | 토론/최종 제안, 방향 일치도 감쇠 | 모순을 완전히 검출하지 못함. typed claims·반증조건 추가는 evidence fixture+ablation 후 | 전면 검증 없음 |
| optimizer infeasible | ContractError; factor 제약 없는 재시도 가능; 실패하면 이전 target | hard gate 유지, fallback 사유 분류·완화 metadata를 다음 우선순위로 | 기존 infeasible 테스트 |
| broker outage/2xx 손상 | 접수 여부가 불명일 수 있음 | unknown 보존·뒤 주문 중단·재전송 안 함; broker 조회/수동 조사 후 reconciliation | create/modify/cancel 모의 응답 |
| partial fill | cumulative snapshot→incremental fills, 나머지 수량 대사 | fill 중복 억제·수수료 배분 유지; 취소 응답 불명도 대사 필요 | 기존 ledger/reconciliation 단위 |
| reconciliation mismatch | position/order 차이 → breach/lockdown | 오류 해결 전 신규 주문 차단; broker ID 없는 불명 상태 임의 종결 금지 | 기존 대사 단위, 실계좌 미실행 |

### 9.7 결정 로그·성과 주장의 한계

1. **새 모델보다 잘못된 측정 수정**: IC 평균은 같아도 겹친 label의 유효 증거량이 다르다. HAC 근거 없는
   기존 active 모델은 읽기 가능해도 서빙 unavailable로 처리한다. 재학습/재평가 후 명시적 adopt가 migration이다.
기존 모델 파일을 재작성하거나 자동 승격하지 않았다.
2. **추정기보다 입력 의미**: 같은 끝 날짜만 맞춘 1일/2일 수익률을 covariance에 넣는 것은 estimator 개선으로
   해결되지 않는다. 결측 panel을 거부하고 이전 target을 보존한다. 모든 종목에서 같은 날 누락한 경우와
   종목별 끝 시각의 freshness까지 증명한 것은 아니다.
3. **알 수 없는 접수 결과는 실패 확정이 아님**: timeout/손상된 mutation 응답을 outcome_unknown으로 남긴다.
   동일 주문 자동 재전송은 도입하지 않는다. 명시적 HTTP 거부와 인증 갱신 정책은 기존대로다.
4. **승인 전 가능한 실패 제거**: 한도 일치와 batch 예산 검사로 사용 가능한 승인 낭비를 줄인다. 이 검사는
   동시 다중 worker에 대한 DB 예산 reservation이 아니다. 단일 실행 운영/잠금 가정은 여전히 중요하다.
5. **버전과 재현성**: regime v2, System target v3, runner `0.7.1-local-graph-macro-h20-news7d`로 동작 변경을
   식별하고 beta constraint도 optimizer input hash에 담았다. 기존 model/promotion identity와 자동 동치 취급하지 않는다.
6. **미도입**: live RL, agent 증원, 최신 neural forecaster, Black–Litterman/HRP 전면 교체, probabilistic regime,
   adaptive live policy, 범용 plugin registry. 데이터·비용·OOS 우월성이 없고 권한/의존성 부담이 커 채택하지 않았다.

7. **외부 뉴스 시점 한계**: source_kind/live bundle 나이·요청 날짜를 제한해도 기사별 발행시각이 없는
   provider 텍스트는 정확한 intraday PIT를 입증하지 못한다. 7일 창은 coverage 수정이며 이 문제의 해결은 아니다.
   `llm/external_parsing.py`의 published_at=None 경로부터 versioned 기사 저장·시각 검증으로 강화해야 한다.

순위 예측 정확도·Sharpe·Sortino·turnover·실제 구현손실의 개선을 이번 변경만으로 주장하지 않는다.
개선 증거는 회귀 입력에서의 올바른 위험 계산·통계 근거·상태 전이·재현 hash다.

### 9.8 검증·재현 방법

baseline은 세션 시작 당시 공유 working tree이며 고정된 깨끗한 commit이 아니다. 다른 세션 수정이 동시에 진행됐다.
초기 전체 실행은 3,168 tests/145.509초에서 repo convention의 임시 probe.py 소멸로 4 errors, skipped1이었다.
이를 제품 동작 실패나 통과로 보고하지 않는다. 아래 최종 전체 실행을 별도로 남긴다.

| 비교 | baseline → candidate | 재현 근거 |
|---|---|---|
| 겹친 IC 증거 | 100일×10종목, 처음60일 rank +1/나머지40일 −1: IID t=2.031010 → HAC t=0.511145, 평균 IC=.2 동일 | research/evaluation/test_alpha.py, Bartlett kernel 이중합과 비교 |
| 최초 손실 | 최초 −20% 포함 synthetic 경로: baseline DD=0.103896% → candidate DD=20.003200% | trading/portfolio/test_market_risk.py, 뒤 80일은 +.1%/−.1% 반복 |
| 날짜 정렬 | AAPL 중간 1봉 제거: 서로 다른 기간 수익을 통과 → ContractError | 같은 market_risk 테스트; 상장 시작만 다른 정상 panel은 허용 |
| 승인 | 실제 repo action 불일치 실패 → approve/reject/consume 중복 방지 통과 | execution/test_runtime_storage.py의 임시 SQLite 통합 |
| 카드 | datetime JSON TypeError → json encode/decode 성공 | execution/test_approval.py |
| 주문 응답 | nonJSON 성공 응답 단순 오류 → outcome_unknown + 단일 POST | execution/test_toss_orders.py + worker unknown 후 후속 주문 중단 |
| 오래된 risk | 20초 첫 POST 후 관측시각 재설정으로 40초 POST 허용 → 두 번째 차단 | execution/test_live_worker.py, 실 safety 함수 호출 |
| beta hash | beta 1→2, 같은 input hash → 다른 hash; aapl/AAPL 동일 결과 | trading/portfolio/test_optimizer.py |

실패 테스트를 먼저 실행한 뒤 수정했다. 주요 묶음 48/47/68/33개 및 optimizer+worker 46개 통과를 확인했다.
독립 reviewer는 사용량 제한으로 종료되어 **독립 검토 완료로 세지 않는다**. 최종 검증 결과는 이 절 말미에 기록한다.

```powershell
python -m unittest discover -s tests -t .
python -m compileall -q src/investment_agent tests/investment_agent
python -m investment_agent.research.commands.adopt_ml_model --help
python -m investment_agent.operations.commands.harness_switch --help
graphify update .
```

전체 테스트의 repository convention/architecture/doc/schema·SQLite 통합 검사가 적용 범위다. 별도 mypy/remote DB
migration 검증이나 실broker/원격 LLM representative pipeline은 실행하지 않았다. 새 DDL·schema migration은 없다.

### 9.9 다음 세션 인계와 연구 우선순위

- **목표/완료**: runtime 추적·1차 자료 비교·위 표의 국소 코드 수정 완료. 기존 `INVESTMENT_SYSTEM.md`,
  constitution의 graph 순서/ML 혼합 설명을 바로잡고 이 절에 연구/결정/실패 시나리오를 통합했다.
- **불변식**: stage/execution_mode/source_kind, Trading↔Execution 권한, LLM weight/order 금지,
  deterministic hard risk, System↔실계좌 독립, 명시적 promotion, 원장 idempotency/reconciliation을 보존한다.
- **운영 상태**: maintenance를 자동 해제하지 않는다. 기존 LIVE/TOSS_LIVE·kill·lockdown을 바꾸지 않는다.
  기존 active ML이 새 통계 계약을 못 채우면 factor fallback이 의도한 동작이다.
- **다음 코드 우선순위**: target factor-exposure fallback을 infeasible/자료오류별로 분리하고 완화 근거 저장;
  동일 as-of immutable price snapshot을 optimizer/gate/stress에 전달해 중복 조회 줄이기;
  종목별 가격 freshness/완전한 거래일 축 검사; 모델 artifact malformed 통계·예측 길이 경계 강화.
- **Data 선행작업**: 앞 절의 재무/13F/PIT/feature version 재처리 이슈가 해결되기 전 새로운 OOS 우월성 주장 금지.
  quote arrival 시각·spread·fill·decision price를 연결하는 TCA dataset부터 만든다.
- **연구 실험**: 기존 factor+ML/현재 비용을 baseline으로 고정 → 동일 PIT universe·purged walk-forward·
  block bootstrap/기간별 IC, calibration, net Sharpe/Sortino/DD/tail, turnover, 비용/coverage/실패율 비교 →
  factor/ML/LLM 및 각 agent 역할 ablation → Shadow(운영 오류·latency·비용 관측) → 필요시 Paper →
  사용자 explicit adoption/promotion. 자동 winner 채택 없음. 후보 선택에 쓴 OOS를 최종 holdout으로 재사용하지 않는다.
- **후보 순서**: 비용·forecast uncertainty 기반 no-trade region → shrinkage/EWMA covariance →
  regime reliability 연속화 → evidence-grounded typed claims/반증조건/실패 기억. RL은 마지막이며 주문 권한 없음.
- **주요 파일/명령**: 위 9.2/9.4 표와 9.8 명령이 시작점이다. graph 결과가 오래됐으면 실제 소스와 대조한다.
- **알려진 미검증**: 실제 시장 OOS/실시간 outage recovery/실체결 TCA/완전한 drift·calibration·자동 rollback 없음.
  이 개선을 수익성 입증 또는 live-ready 선언으로 읽지 않는다.
