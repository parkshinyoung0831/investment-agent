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

(마지막에 채운다)

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

> **TE-1·TE-2는 실주문을 켜기 전에 반드시 해결해야 한다.** 승인 → 주문 이음매가 실제 부품을 붙이면 깨지는데, 단위 테스트가 가짜 저장소·가짜 Discord 클라이언트를 써서 가렸다.

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

(이하 다른 도메인 항목은 분석이 끝나는 대로 추가한다.)
