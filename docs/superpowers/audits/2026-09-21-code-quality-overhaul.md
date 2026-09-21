# 코드 품질 전면 점검 2차 — 확인 못 했던 영역 · 값 로직 · 실측 시각

2026-09-21 시점의 점검 결과다. [1차 감사](2026-09-20-code-quality-overhaul.md)가
"[확인하지 못한 영역](2026-09-20-code-quality-overhaul.md#6-확인하지-못한-영역)"으로 남긴 곳에서 출발했다 —
`trading/portfolio`·`performance`·`evidence`·`decision/agents`, `execution/brokers`·`orders` 뒷부분,
`operations` 나머지, 그리고 값 계산 로직 전반. 1차가 이미 센 항목은 다시 세지 않고 회귀만 확인했다.

원본 분석은 `raw/2026-09-21-*.txt`에 그대로 있다. 이 문서는 그 요약과 판단이다.

## 0. 방법과 한계

| 표시 | 뜻 |
|---|---|
| **확정** | 코드 경로를 끝까지 읽었고, 재현 논리를 적을 수 있거나 운영 데이터·원천 수치로 확인했다 |
| **의심** | 정황은 강하지만 위 수준의 확인을 못 했다 |

- **기준선**: 작업 시작 시 `python -m unittest discover -s tests -t .` → **3,435개 실행, OK, skipped 1, 실패 0**(437초).
  따라서 이후 실패는 전부 이번 작업이 만든 것이다.
- **작업 트리 상태**: 시작 시점에 1차 감사(들)의 미커밋 변경 135개가 이미 있었다. 이번 세션 동안
  그 파일들의 mtime은 변하지 않았고(다른 세션의 진행 없음), 새로 생긴 변경은 이 감사의 산출물뿐이다.
- **운영 데이터 대조**: Supabase는 PostgREST(service role) **읽기 전용 조회**로만 읽었다.
  `SUPABASE_DB_URL`(포트 5432 pooler)은 이 네트워크에서 연결이 막혀 psycopg2 경로는 쓸 수 없었다 —
  그래서 값 대조는 PostgREST `select`로 했고, 집계가 필요한 곳은 페이지네이션으로 받아 파이썬에서 셌다.
- **쓰지 않은 것**: 운영 DB 쓰기·DDL·DML, Discord 발송, 하네스 실행·재시작, commit·push, 재적재.
  하네스·실행 코드는 **정비 보류가 걸린 상태**(`MAINTENANCE_HOLD`, 2026-09-20T15:53Z, 사유
  "repository upgrade: runtime audit and offline validation")에서만 읽고 고쳤다. 보류는 내가 만들지도 풀지도 않았다.
- **분석 분담**: 4개 영역을 읽기 전용 서브에이전트가 병렬로 봤고(발견마다 즉시 raw 파일에 append),
  **높음 항목은 저자가 코드·운영 데이터로 다시 확인했다**. 서브에이전트 3개는 세션 한도로 중간에
  종료됐지만 append 방식이라 발견은 남았다. 재검증하지 못한 항목은 아래 표의 상태에 그대로 적었다.
- **죽은 코드 전수**: AST로 `src/investment_agent` 모듈 최상위 정의 전부를 모아 src 내 참조 0건을 셌다 →
  **5개**(전부 1차 감사가 판단 보류로 남긴 것 + 테스트 전용 헬퍼). pyflakes 미사용 import → **0건**
  (`execution/contracts.py`의 `__all__` 2개와 `llm/runtime.py`의 2개는 각각 모듈 `__getattr__`·재수출로
  실제 사용된다 — 오탐임을 호출부로 확인했다). 1차 감사의 정리가 유효하다.
- **PostgREST 한계 전수**: `.select(…).execute()`로 끝나며 `limit`·`range`·`select_all_paged`가 모두 없는
  조회 → **3건, 전부 로컬 SQLite 미러 경로**(1,000행 상한과 무관). Supabase 경로 누락은 0건이다.
- **읽기 계약 전수**: `reporting` 뷰 14개 × 선언 컬럼·`order_by`·`time_column`·`scope_column`을
  운영 DB와 대조 → **불일치 0건**. 선언 topic 15개 전부 운영 원장에 baseline이 있다(fail-closed 누락 0건).
  `KIND_ENV` 15개 channel_kind 전부 로컬 `.env`에 채널이 있다.

## 1. 요약

| 구분 | 개수 |
|---|---|
| 발견 항목 | **80** (확정 72 · 의심 8) |
| 높음 | 13 |
| 중간 | 41 |
| 낮음 | 26 |
| **수정됨(코드)** | 아래 2절의 "수정됨" 행 |
| 사용자 결정·실행 필요 | 6절 |

영역별: trading 16 (`TR2-*`) · execution 17 (`EX2-*`) · operations 20 (`OP2-*`) ·
research·reporting 20 (`RR2-*`) · 워크플로·시각·그 밖 4 (`AU-*`).

**가장 조용한 결함 셋** (에러 없이 틀린 숫자가 원장에 들어간다)

1. **RR2-06** 사후평가·RL 보상의 총수익률이 분할을 두 번 반영한다. 운영 데이터로 확정했다 — 저장된 종가와
   배당은 이미 분할 조정(back-adjust)돼 있는데 코드가 분할 비율로 주식수를 또 늘린다. 10:1 분할 구간은
   가격이 그대로여도 **+900%**가 된다. 테스트 픽스처가 미조정 시계열을 만들어 이 결함을 정답으로 보이게 했다.
2. **EX2-11** 체결 원장 `fills`에 쓰는 코드가 하나도 없다. 성과·수수료·실현손익과 `investment_trades`
   카드가 "체결 0건"을 사실처럼 보고한다.
3. **RR2-01** 적자·현금소진 기업은 value category가 통째로 빠지고, composite이 **남은 category만으로
   재정규화**되어 종합점수가 오히려 올라간다. 나쁜 관측이 결측과 같은 `None`으로 접힌다.

## 2. 항목표

상태: `수정됨`(테스트 동반 · 검증 기록은 9절) / `예정`(코드만으로 가능하나 아직 손대지 않음 — 10절 인계) /
`보고만`(결정·재적재·실행이 필요) / `잠복`(현재 소비자가 없어 사용자에게 가는 숫자는 없음).

### 2.1 research · reporting — 값 계산 (`RR2-*`, 원본 [raw](raw/2026-09-21-research-reporting.txt))

| ID | 한 줄 | 판정 | 심각 | 상태 |
|---|---|---|---|---|
| RR2-01 | 적자·음의 FCF 기업은 value category가 탈락하고 composite이 남은 category로 재정규화돼 점수가 올라간다 | 확정(재검증) | 높음 | 수정됨 |
| RR2-02 | 2-member category는 factor 하나만 있어도 통과한다 — `>= 0.5`가 주석의 의도와 반대 | 확정(재검증) | 낮음 | 주석만 수정 · 값은 결정 대기 |
| RR2-03 | TTM 매출성장(YoY)만 분기 연속성 검사를 안 받는다 (RP-04·RS-10 수정의 사각) | 확정 | 중간 | 수정됨 |
| RR2-04 | `_total_debt`가 누락 차입 구성요소를 0으로 접어 레버리지를 좋게 만든다 | 의심 | 중간 | 보고만 |
| RR2-05 | `revision_eps_change`에 비교 기간이 없다 — 하루 전과 반년 전이 같은 열에 섞인다 | 확정 | 낮음 | 보고만 |
| RR2-06 | **총수익률이 분할을 두 번 반영한다** (사후평가·RL 보상) | 확정(운영 대조) | 높음 | 수정됨 |
| RR2-06a | 그 결함을 가리던 테스트 픽스처 2개(미조정 종가) | 확정(운영 대조) | 높음 | 수정됨 |
| RR2-07 | 백테스트 시뮬레이터가 분할을 수량에 적용한다 — 저장소 가격은 이미 조정됨 | 확정 | 중간 | 잠복(생산자 없음) |
| RR2-08 | 순부채가 같은 카드 안에서 두 정의로 계산된다(단기투자자산 차감 여부) | 확정 | 중간 | 보고만 |
| RR2-09 | `total_debt` 정의가 reporting과 research에서 다르다(운용리스 포함 여부) | 확정 | 중간 | 보고만 |
| RR2-10 | EBITDA가 음수면 `net_debt_to_ebitda`가 음수로 나와 "건전해 보인다" | 확정 | 중간 | 수정됨 |
| RR2-11 | 역사 EV 시계열이 순부채 결측을 0으로 접어 EV/EBITDA 백분위를 싸게 만든다 | 확정 | 중간 | 보고만 |
| RR2-12 | 분할 조정 기준일 규약이 두 곳에서 다르다(`>=` vs `>`) | 의심 | 낮음 | 보고만 |
| RR2-13 | rate·spread 지표의 고저 계산에 소비자가 없어 금리 4종이 어떤 경보도 못 낸다 | 확정 | 낮음 | 보고만 |
| RR2-14 | `daily_change` 경보가 절대 변화로 걸고 상대 변화율로 적는다 | 확정 | 낮음 | 수정됨 |
| RR2-15 | 최대낙폭 부호 규약이 세 곳에서 다르고 승격 게이트가 하나를 "데이터 오류"로 센다 | 확정 | 중간 | 보고만 |
| RR2-16 | RL 학습·추론이 결측 feature를 0으로 채운다 — layer가 금지한 규칙, log 스케일에서 극단값 | 확정 | 중간 | 보고만 |
| RR2-17 | 판단 한 종목의 가격 경로가 어긋나면 RL 재학습 전체가 예외로 선다 | 확정 | 중간 | 보고만 |
| RR2-18 | 순위 상관을 세 가지 동점 규칙으로 계산한다 | 확정 | 낮음 | 보고만 |
| RR2-19 | 변동성 0인 수익률 시계열이 DSR 검정을 통과한다 | 의심 | 낮음 | 보고만 |

### 2.2 trading (`TR2-*`, 원본 [raw](raw/2026-09-21-trading.txt))

| ID | 한 줄 | 판정 | 심각 | 상태 |
|---|---|---|---|---|
| TR2-04 | 유니버스 한 종목의 가격 공백이 System 목표 생성을 통째로 멈추고 하네스는 성공으로 본다 | 확정(재검증) | 높음 | 수정됨 |
| TR2-01 | 집중도 HHI 한도(0.15)가 종목 상한(0.10) 때문에 영원히 참이 될 수 없다 | 확정(재검증) | 중간 | 수정됨 |
| TR2-02 | `min_position_weight`가 조정 전 비중에만 걸려 승인 비중에 dust가 남는다 | 확정 | 중간 | 보고만 |
| TR2-03 | `RiskDecision.metrics`가 조정 전 `drawdown_fraction`과 조정 후 지표를 한 묶음으로 저장한다 | 확정 | 낮음 | 보고만 |
| TR2-05 | optimizer 위험항이 고정 보유(`fixed_weights`)를 무시해 상관 종목에 몰 수 있다 | 확정 | 중간 | 보고만 |
| TR2-06 | `expected_return`이 confidence를 곱한 값이고 두 이름이 같은 값을 저장한다 | 확정 | 낮음 | 보고만 |
| TR2-07 | 섹터 분류가 없는 종목이 섹터 한도 밖에 놓이고 그 사실이 경고도 없이 통과한다 | 확정 | 중간 | 수정됨 |
| TR2-08 | 보유 한 종목의 짧은 가격 이력이 테마 전체의 사건 민감도를 경고 한 줄로 없앤다 | 확정 | 중간 | 보고만 |
| TR2-09 | `estimate_betas`가 종목마다 benchmark 전체 가격을 다시 파싱한다 | 확정 | 낮음 | 수정됨 |
| TR2-10 | 배당 수익이 어떤 손익에도 안 들어가고 계산된 `dividend_income`을 아무도 읽지 않는다 | 확정 | 중간 | 보고만 |
| TR2-11 | `nav_returns`의 `daily_return`이 하루가 아니라 "마지막 스냅샷 이후"다 | 확정 | 낮음 | 수정됨 |
| TR2-12 | 귀속 불가 체결 카운터가 전역이라 무관한 계좌 보고서에도 품질 결함을 찍는다 | 확정 | 낮음 | 보고만 |
| TR2-13 | 순 기대수익이 정확히 0인 신호의 confidence를 1.0으로 기록한다 | 확정 | 낮음 | 수정됨 |
| TR2-14 | 스트레스 한도 하나를 충격 크기가 다른 8개 시나리오에 그대로 적용한다 | 의심 | 중간 | 보고만 |
| TR2-15 | Evidence Dossier 계층(1,116줄)이 src에서 호출되지 않고 테스트가 살아 있게 유지한다 | 확정 | 중간 | 보고만 |
| TR2-16 | `fundamental_trend`의 연간 합산이 FY 행과 Q1~Q4를 함께 더해 약 2배로 만든다 | 확정 | 낮음 | 수정됨 |

### 2.3 execution (`EX2-*`, 원본 [raw](raw/2026-09-21-execution.txt))

정비 보류 하에서만 읽고 고쳤다. **실주문·킬스위치의 의미를 바꾸는 것은 고치지 않고 보고만 했다.**

| ID | 한 줄 | 판정 | 심각 | 상태 |
|---|---|---|---|---|
| EX2-01 | 승인 시점 planner와 실행 시점 planner가 다른 한도를 써서 재검증이 영구히 "재승인 필요" | 확정(재검증) | 높음 | 수정됨 |
| EX2-02 | 30초 risk state 창이 준비 단계에 소진돼 승인 소비 후 배치가 중간에 잘린다 | 확정 | 높음 | 보고만(사용자 결정) |
| EX2-03 | 브로커 `REPLACED`가 전이표에 없어 대사 패스 전체가 예외로 끊긴다 | 확정(재검증) | 높음 | 수정됨 |
| EX2-07 | 제출 시점 인증 실패가 worker의 except 3개를 모두 통과해 고아 `planned` 주문을 만든다 | 확정(재검증) | 높음 | 수정됨 |
| EX2-11 | **`fills`에 쓰는 코드가 하나도 없다** — 성과·체결 카드·화면이 영구히 "체결 0건" | 확정(재검증) | 높음 | 보고만(설계 결정) |
| EX2-04 | `order_attempts.state`에 UPDATE가 0건이라 재실행 가드 SQL 조건이 공허하다 | 확정 | 중간 | 보고만 |
| EX2-05 | 기준점 보관 2일 vs 조회 5일 — 연휴 뒤 기준점이 비어 실주문이 막힌다 | 확정(재검증) | 중간 | 수정됨 |
| EX2-06 | 주문 직전 위험 계산이 `cash: 0` 가짜 계좌 스냅샷을 성과 읽기 경로에 남긴다 | 확정 | 중간 | 보고만 |
| EX2-08 | 어댑터 문서는 "재시도 없음"인데 `_request`가 401에서 POST를 다시 보낸다 | 의심 | 중간 | 보고만(사용자 결정) |
| EX2-09 | 매수 현금 여유가 세 숫자로 흩어져 서로 모순되는지 아무도 검사하지 않는다 | 확정 | 중간 | 수정됨 |
| EX2-10 | `commissionRate` 단위에 상·하한 검증이 없다 — 퍼센트 단위면 필요 현금 100배 | 의심 | 중간 | 수정됨 |
| EX2-12 | `reconciliation_runs`에 쓰는 코드가 없어 "대사 실행" 패널이 항상 비어 있다 | 확정 | 중간 | 보고만 |
| EX2-13 | `expire_due_approvals`를 아무도 부르지 않아 만료 승인이 `pending`으로 남는다 | 확정 | 중간 | 수정됨 |
| EX2-14 | src 참조 0건인 실행 경계 정의 4개(TE-14 목록 밖) | 확정 | 낮음 | 보고만 |
| EX2-15 | `LifecyclePromotionGate`의 최대낙폭 비교 부호가 거꾸로 — 어떤 낙폭도 위반이 아니다 | 확정 | 낮음 | 수정됨 |
| EX2-16 | 거절·결과불명 주문이 당일 주문 수·금액 한도를 소진한다 | 확정 | 낮음 | 보고만(사용자 결정) |
| EX2-17 | 낮음 묶음 8건 (이벤트 정렬·만료 문자열 비교·`source_kind` 어휘·endpoint 중복 등) | 확정 | 낮음 | (h) 수정됨 · 나머지 보고만 |

### 2.4 operations (`OP2-*`, 원본 [raw](raw/2026-09-21-operations.txt))

| ID | 한 줄 | 판정 | 심각 | 상태 |
|---|---|---|---|---|
| OP2-01 | `waiting`으로 폴링하는 stage가 attempts를 태워 첫 실제 오류가 곧바로 terminal 실패가 된다 | 확정(재검증) | 높음 | 수정됨 |
| OP2-04 | 정비 보류가 진입점 자체를 막지 않는다 — OS 서비스·직접 실행은 그대로 뜬다 | 확정(재검증) | 높음 | 수정됨 |
| OP2-06 | 실주문 플래그와 킬스위치가 확인 문구 없이 한 글자로 바뀐다 | 확정 | 높음 | 보고만(사용자 결정) |
| OP2-15 | 1분 주기 job이 영구 실패하면 운영 webhook으로 분당 1건씩 쏟아진다 | 확정(재검증) | 높음 | 수정됨 |
| OP2-19 | 대사가 "찾은 것이 있다"를 "명령이 실패했다"로 돌려줘 수동 주문 하나로 job이 영구 실패한다 | 확정(재검증) | 높음 | 수정됨 |
| OP2-02 | background 단계가 6개 worker를 13개 stage와 공유하고 대기에 시간 상한이 없다 | 확정 | 중간 | 보고만 |
| OP2-03 | 가장 긴 stage 셋이 background에서 빠져 tick 루프를 최대 3시간 막는다 | 확정 | 중간 | 보고만 |
| OP2-05 | 정비 보류를 걸어도 돌고 있는 하네스는 안 멈추는데 메시지는 멈춘다고 읽힌다 | 확정 | 중간 | 수정됨 |
| OP2-07 | 상태창의 `mode`가 실제 프로세스 모드가 아니라 `.env`에서 다시 계산된다 | 확정 | 중간 | 보고만 |
| OP2-08 | `emergency_stop --lockdown-env`만 쓰면 잠금이 성공해도 종료 코드 1 | 확정 | 중간 | 수정됨 |
| OP2-09 | `.env` 킬스위치 잠금이 파일이 없으면 조용히 아무 일도 안 하고 경로를 깊이로 추측한다 | 확정 | 중간 | 수정됨 |
| OP2-10 | 긴급 정지가 state.json의 PID 하나만 노려 승인 리스너·여분 하네스가 살아남는다 | 확정 | 중간 | 보고만 |
| OP2-11 | 보안 사전점검이 잘못된 한도 값을 검사하지 않고 넘겨 "healthy"를 준다 | 확정 | 중간 | 수정됨 |
| OP2-16 | 일일 점검 카드가 "전부 조회 실패"와 "전부 0"을 구분하지 않는다 | 확정 | 중간 | 수정됨 |
| OP2-17 | embed 본문이 1,900자로 잘려 채널 도착 표가 먼저 사라진다 | 확정 | 중간 | 수정됨 |
| OP2-18 | 채널 ID가 숫자가 아니면 채널 도착 점검 전체가 사라진다 | 확정 | 중간 | 수정됨 |
| OP2-20 | 발표 감시가 1분마다 macro 참조 master 전체를 다시 upsert한다 | 확정 | 중간 | 수정됨 |
| OP2-12 | 보안 사전점검이 `TOSS_MAX_DAILY_ORDERS`를 아예 보지 않는다 | 확정 | 낮음 | 수정됨 |
| OP2-13 | `.gitignore` 비밀 보호 점검이 부분 문자열이라 공허하게 통과할 수 있다 | 확정 | 낮음 | 수정됨 |
| OP2-14 | 봇 토큰 분리 점검이 `DISCORD_BOT_TOKEN`이 없으면 결과를 하나도 내지 않는다 | 확정 | 낮음 | 수정됨 |

### 2.5 워크플로 · 시각 · 그 밖 (`AU-*`, 원본 [raw](raw/2026-09-21-timing-workflows.txt))

| ID | 한 줄 | 판정 | 심각 | 상태 |
|---|---|---|---|---|
| AU-01 | 신규 추적 CIK의 기존 공시가 세그먼트 처리에서 영구 누락 → 정합성 점검이 매일 실패(67%) | 확정(운영 대조) | 중간 | 수정됨 |
| AU-02 | `econ_calendar_ics`가 46% 실패하며 매일 실패 알림, cron·체인 이중 실행 | 확정(운영 대조) | 낮음 | 수정됨 |
| AU-03 | 13F 화면이 매니저 성향을 이름 부분문자열로 고른다 — 카탈로그에 이미 값이 있다 | 확정 | 낮음 | 수정됨 |
| AU-04 | RR2-06 전제(저장 가격·배당이 분할 조정)를 운영 데이터로 확정 | 확정 | — | 근거 |

## 3. 하드코딩 목록과 이전 목적지

새 `config/*.toml` 층은 만들지 않았다. hard risk limit은 `trading/risk/gate.py`에 그대로 둔다.

| ID | 무엇이 어디에 박혀 있나 | 이전 목적지 | 상태 |
|---|---|---|---|
| TR2-01 | 집중도 HHI 한도 0.15가 종목 상한 0.10과 수학적으로 모순(최대 HHI = 0.10) | `PortfolioRiskPolicy` 안에서 두 값의 정합성을 검증 | 수정됨 |
| EX2-09 | 매수 현금 여유 3개(band 25bp · 수수료 10bp · 계획 버퍼 50bp)가 서로 모르는 상수 | 세 값이 모순되지 않는지 검사하는 계약 테스트 | 수정됨 |
| EX2-10 | `commissionRate` 단위 가정이 코드에만 있고 검증이 없다 | 어댑터 경계에서 범위 검증(소수 단위) | 수정됨 |
| AU-03 | 매니저 성향·요약 14쌍이 대시보드에 인라인 | `MANAGER_PRESENTATION`의 `strategy_group` + institutional catalog의 라벨 표 | 수정됨 |
| TR2-14 | 스트레스 한도 하나를 충격 크기가 다른 8개 시나리오에 적용 | 시나리오별 한도(값 결정 필요) | 보고만 |
| EX2-17 | Toss endpoint 경로 상수 일부가 아직 두 곳에 | `platform/endpoints.py` | 예정(코드만) |
| — | 특정 ticker·CIK 리터럴 분기 | 없음 | AST 전수 조사 → **0건** (1차 감사 결론 유지) |

## 4. 성능 (측정값)

| ID | 병목 | 측정 | 상태 |
|---|---|---|---|
| TR2-09 | `estimate_betas`가 종목마다 benchmark 전체 가격을 다시 파싱 | 보유 30종목 × benchmark 500봉 = 15,000행 재파싱/호출 → 1회 파싱 | 수정됨 |
| OP2-20 | 발표 감시가 1분마다 macro 참조 master 전체를 upsert | 창 안 180분 × (series 62 + measures 46) 왕복 → 프로세스 1회 | 수정됨 |
| — | 기각: PostgREST 페이지네이션 누락 0건, `reporting` 뷰 계약 불일치 0건 | | |

## 5. 시각 재설계 — 실측 근거와 판단

측정: `gh run list --limit 1000`(2026-08-21 21:49 ~ 2026-09-21 05:33 UTC, schedule 이벤트).
명목 슬롯은 워크플로 cron을 요일까지 펼쳐 만들고, 실행을 6시간 안의 가장 가까운 이전 슬롯에 1:1
매칭했다(미매칭 슬롯 = 드롭). **HEAD과 작업 트리의 cron 선언은 같다** — 이력이 현재 선언의 실측이다.

### 5.1 핵심 관측 — 지연은 "분"이 아니라 "시"가 정한다

| 명목 UTC시 | KST | 표본 | 지연 중앙(분) | p90 | 최대 |
|---|---|---|---|---|---|
| 21 | 06 | 40 | **119** | 153 | 480 |
| 22 | 07 | 28 | **118** | 179 | 473 |
| 23 | 08 | 24 | **110** | 149 | 449 |
| 15 | 00 | 39 | 170 | 225 | 331 |
| 13 | 22 | 15 | 247 | 314 | 387 |
| 0 | 09 | 64 | 271 | 471 | 687 |
| 3 | 12 | 63 | 286 | 326 | 658 |
| 6 | 15 | 27 | **306** | 379 | 672 |

→ **21:00~23:59 UTC 명목은 110~119분, 00:00~09:00 UTC 명목은 264~307분.** 2.4배다.

**분 정렬은 효과가 없다.** 00~09 UTC 구간만 놓고 명목 "분"별 지연 중앙을 보면
`:00` 269 · `:10` 280 · `:20` 281 · `:25` 270 · `:30` 285 · `:40` 297 · `:50` 272 —
차이가 표본 변동 안에 있다. 시를 통제하지 않은 집계(`+0분` 147 vs `+5분` 266)는 21~23시
워크플로가 `:30`·`:00`에 몰려 생긴 교란이다. **1차 감사 11.3의 "분을 옮기지 않는다"가 맞다.**

**체인은 사실상 즉시다.** `workflow_run` 상류 종료 → 하류 생성 지연 중앙 **0.0분**
(표본: ics 29 · dimensions 15 · expectations 18 · notify_fundamentals 70 · notify_macro_core 26 ·
notify_macro_watch 26 · tech_indicators 19; 최대는 notify_fundamentals의 47.8분 1건).

### 5.2 판단

**예산이 먼저다.** `python scripts/actions_budget.py`(실측 빈도) → **1,818 / 2,000 min/월, 여유 182분(91% 사용)**.
스크립트 자체가 "여유 30% 미만" 경고를 낸다. 따라서 **실행 횟수를 늘리는 제안은 채택하지 않았다**(AU-05).

| 무엇 | 현재 | 제안 | 근거 |
|---|---|---|---|
| 순서가 필요한 모든 체인 | 일부는 cron 시각차에 의존 | `workflow_run` | 체인 0.0분 vs cron 110~307분. 1차 감사 WF-10이 macro_etl에 이미 적용 |
| `econ_calendar_ics`의 cron 안전망 | 체인 + cron `10 5 * * *` 이중 | **cron 제거** | 체인 29/29 발화·지연 0.0분. cron은 드롭 30%·지연 270분·실패 알림만 더한다 (AU-02, 수정됨) |
| `fundamentals_integrity` | cron `0 9 * * *` → 실제 13:30 UTC(22:30 KST) | **바꾸지 않음** (체인 안은 철회) | 체인으로 옮기면 21 → 32회/월(약 +11분)인데 예산 여유가 182분이다. 게다가 `concurrency: fundamentals-etl`(cancel-in-progress: false)이 이미 겹침을 막고, 실측 13:30 UTC는 상류 종료(08:20~09:00 UTC) 뒤다 — 얻는 것이 비용보다 작다 |
| 속보성 경로(경제지표 발표) | 하네스 1차 + Actions 안전망 | 유지 | 1차 감사 WF-01이 적용. Actions cron은 `econ_calendar_watch` 드롭 93%로 속보에 못 쓴다는 실측이 근거 |
| 분 이동 | — | **하지 않음** | 위 실측. 근거 없는 변경은 하지 않는다 |
| `notify_macro_core`·`notify_macro_watch` | cron(22·39회) + 체인(각 26회) 이중 | **cron을 주 1회로** (사용자 결정) | 두 알림이 하루 두 번 같은 판정을 한다. 실측 드롭이 16~20%뿐이라 일별 안전망의 값이 작고, 낮추면 약 **70 min/월**이 빈다. 발송 정책이라 코드만으로 정하지 않았다 |
| 00~09 UTC에 남은 잡 | fundamentals_daily 03:30 · dimensions 04:10 · institutional 04:40 · notify_fundamentals 05:20 | **앞당기지 않음** | SEC 일별 색인이 전일 23:30 ET 이후 확정이고 코드가 그 색인에 의존한다. 21~23시 UTC로 옮기면 하루 전 색인을 읽는다 |

**수신자(KST) 관점**: 21~23시 UTC 명목은 KST 06~08시에 실제 발화한다 — 아침에 보는 카드로 적절하다.
00~09시 UTC 명목은 KST 오후~저녁에 도착한다. 실적·재무 카드가 오후에 오는 것은 미국 장 마감 뒤
SEC 접수를 기다리는 구조상 불가피하다.

### 5.3 지금 깨져 있는 것 (실패율 실측)

| workflow | 총 | 실패 | 실패% | 최근 | 원인 |
|---|---|---|---|---|---|
| `fundamentals_integrity` | 21 | 14 | 67% | 09-17~20 연속 | AU-01. `segment_tracked_coverage`가 신규 추적 CIK 3개(FDXF·HONA·XOM)를 매일 잡는다 |
| `econ_calendar_ics` | 56 | 26 | 46% | 09-17~20 연속 | 공개 버킷 `econ-calendar` 없음(1차 감사 WF-02, 사용자 조치) |
| `market_daily` | 19 | 6 | 32% | 08-27~09-09 | 이번 감사 범위 밖(1차 감사가 다룬 provider 실패 계열) |
| `notify_investment` | 3 | 3 | 100% | 09-08~10 | 로컬 SQLite 원장을 러너에서 열려 했다. **워크플로 파일이 이후 삭제돼 해소됨** |

## 6. 사용자 결정·실행이 필요한 것

- **실주문 안전 의미** (고치지 않고 올림): EX2-02(30초 창 안에 준비 단계가 들어가는 구조 — 창을 늘릴지
  준비를 창 밖으로 뺄지), EX2-08(401 재전송 허용 여부), EX2-16(거절·결과불명 주문의 한도 소진 규칙),
  OP2-06(실주문 플래그·킬스위치 변경에 확인 문구를 요구할지).
- **설계 결정**: EX2-11(`fills`를 브로커 집계 스냅샷에서 파생할지, 소비자를 `orders`의 체결 수량으로
  옮길지 — 개별 체결 id가 없다), EX2-12(`reconciliation_runs` 생산자), TR2-15(Dossier 계층 삭제 vs 연결),
  RR2-07(백테스트 `price_basis` 계약), TR2-14(시나리오별 스트레스 한도 값), RR2-15(최대낙폭 부호 규약 통일).
- **재적재**: RR2-01·RR2-02·RR2-03이 feature 값을 바꾼다 → 저장된 feature snapshot·label·학습 표본을 지우고 다시 적재한다(`scripts/reset_feature_version_stores.py`, 버전 컬럼은 이후 제거됨).
  RR2-06 수정은 이미 저장된 `decision_experiences`·평가 원장의 분할 구간 행을 오염 상태로 남긴다 →
  재계산 대상. **실행은 사용자가 한다.**
- **운영 조치**: `econ-calendar` 공개 버킷 생성(AU-02의 실패가 멈춘다), 신규 추적 CIK 세그먼트 backfill
  (아래 명령), 1차 감사 10.3의 남은 항목(2027 BOK 일정·시크릿 등).

```bash
# AU-01: 신규 추적 종목의 세그먼트 이력 채우기 (dry-run 없음 — 적재 명령이다)
python -m investment_agent.data.fundamentals.commands.backfill_history \
    --content segments --period quarter --scope missing
python -m investment_agent.data.fundamentals.commands.backfill_history \
    --content segments --period annual --scope missing
```

## 7. 확인하지 못한 영역

- `trading/decision/llm/*`(725줄 `runtime.py` 포함)과 `decision/agents`의 LLM 프롬프트 경로: 외부
  TradingAgents 그래프에 의존해 오프라인으로 값을 재현할 수 없다.
- Toss API 명세가 저장소에 없어 확정 불가: `commissionRate` 단위, `cashBuyingPower` 의미,
  주문 상태 enum의 실제 집합, 개별 체결 id 제공 여부 (EX2-08·10·11의 "의심" 사유).
- 로컬 SQLite 실행 원장의 **실제 값**: 읽지 않았다(계약 일치만 봤다). `order_attempts.state`·`fills`가
  비어 있다는 판정은 **쓰는 코드가 없다**는 정적 사실에 근거한다.
- `notifications/*` 카드의 시각 검증(스크린샷)은 하지 않았다.
- 서브에이전트 3개가 세션 한도로 중간 종료돼 `trading/decision/candidates.py` 뒷부분,
  `operations/commands` 일부(`system_ablation`·`build_decision_experiences`),
  `research/datasets`·`models` 뒷부분은 끝까지 읽지 못했다.

## 8. 수정 순서와 검증

이번에 한 순서: **조용한 값 오류**(RR2-06·06a → RR2-01·02·03·10·14 → TR2-16) →
**구조·죽은 코드**(EX2-13·15, TR2-13) → **하드코딩 이전**(TR2-01, EX2-09·10, AU-03) →
**성능**(TR2-09, OP2-20) → **시각**(AU-01·02).

검증 결과는 9절.

## 9. 수정 원장 — 무엇을 고쳤고 어떻게 확인했나

각 항목은 **테스트를 동반**하고, 새 가드·계약 테스트는 **옛 동작을 하나씩 주입해 실제로 실패하는 것을
확인한 뒤 try/finally로 복원**했다. "주입 확인"이 그 뜻이다.

| ID | 고친 것 | 파일 | 검증 |
|---|---|---|---|
| RR2-06 | `total_return`에서 분할 비율로 주식수를 늘리던 곱을 제거. 분할 비율은 **값 검증에만** 쓴다(0 이하는 거절) | `research/evaluation/returns.py` | 테스트 7개. 옛 곱 주입 시 `asset_return` 1.0(정답 0) 등 2건 실패 확인 |
| RR2-06a | 픽스처 2개를 저장 계약(분할 조정된 연속 종가)으로 바꾸고, "분할 비율이 수익률을 바꾸지 않는다"를 단정 | `test_evaluator.py`, `test_decision_learning.py` | 위와 같은 주입에서 이 둘이 실패한다 |
| RR2-01 | 부호를 보존하는 `earnings_to_market_cap`·`fcf_to_market_cap`을 밸류에이션 관측에 추가하고, factor feature 두 개가 비율 대신 그것을 읽게 했다. 적자·음의 FCF가 결측이 아니라 **최하위 관측**이 된다 | `research/valuation/engine.py`, `research/commands/build_valuations.py`, `research/features/layer.py` | 테스트 3개(+기존 갱신 1개). 옛 `1/pe` 유도 주입 시 실패 확인. 재정규화 편향 자체를 고정하는 테스트도 추가 |
| RR2-02 | **코드는 바꾸지 않았다.** 주석이 강제되지 않는 규칙을 주장하고 있었으므로, 실제 규칙과 문턱을 올릴 때의 부작용(RR2-01의 재정규화 편향이 커진다)을 주석에 적었다 | `research/factors/core.py` | — (값 변경은 결정 대기) |
| RR2-03 | 전년 TTM 창에도 연속성 검사를 걸고, 현재 창과 **맞붙는지**까지 8분기를 한 번에 검사 | `research/evidence/statistics.py` | 테스트 1개. 검사 제거 주입 시 비인접 창으로 성장률 0.25가 조용히 계산되는 것을 확인 |
| RR2-10 | `net_debt_to_ebitda`가 음의 EBITDA에서 음수 배수를 내던 것 → 빈칸 | `reporting/notifications/earnings_report.py` | 테스트 1개 |
| RR2-14 | 경보 사유 문구를 **판정한 값과 같은 단위**로. 같은 0.12 변화가 기준값에 따라 `+3.00%`·`+60.00%`로 보이던 것 | `reporting/services/macro/thresholds.py` | 테스트 1개. 옛 상대 변화율 주입 시 실패 확인 |
| TR2-04(관측) | 하네스 `run_system_portfolio` 단계가 실행 전후 최신 System 목표를 비교해, 진전이 없으면 `succeeded`가 아니라 `skipped`(`reason=system_target_unchanged`)를 돌려준다. **거부 단위(종목 vs 배치)는 바꾸지 않았다 — 그쪽은 결정 사항** | `operations/adapters/trading.py` | 테스트 3개. "항상 succeeded" 주입 시 2건 실패 확인 |
| TR2-01 | `reachable_concentration_hhi`(= 종목 상한 × (1−현금 하한))와 `concentration_hhi_limit_binds`를 정책 property로 두고, 위험 판정 `metrics`에 함께 남긴다. **한도 값은 바꾸지 않았다** — 원장이 발동할 수 없는 한도를 통과로 주장하지 않게 하고, 세 값의 관계를 테스트로 고정했다 | `trading/risk/gate.py` | 테스트 3개(상한 0.095 < 한도 0.15, 최대 집중 입력의 HHI가 유도 상한을 넘지 않음) |
| TR2-07 | 섹터 지도를 **받았는데** 분류가 없는 종목의 합계가 섹터 상한을 넘으면 위반으로 올린다(새 임계 없이 기존 상한으로 판정). 목록·비중을 `metrics`에 남긴다. 지도를 아예 넘기지 않은 호출은 `require_sector_map`의 몫으로 남겼다 | `trading/risk/gate.py` | 테스트 3개. 검사 제거 주입 시 실패 확인. 운영 대조: tracked 500 CIK의 `sic_division_name` 결측 **0%** — 이 경로는 비추적 보유에서만 발동한다 |
| TR2-13 | 근거가 방향을 말했는데 최종 기대수익이 0인 경우를 "방향을 말한 근거가 없다"(confidence 1.0)와 분리. 상쇄된 경우는 0.0 | `trading/decision/alpha.py` | 테스트 1개(5가지 조합). 두 경우를 다시 묶는 주입 시 실패 확인 |
| TR2-11 | `daily_return` → `latest_period_return` + `latest_period_start_at`·`end_at`. 스냅샷 간 구간이 하루가 아니라는 사실을 키 이름과 payload가 말하게 했다 | `trading/performance/ledger.py`, `notifications/investment/run_performance.py` | 테스트 1개(주말 건너뛴 69시간 구간). 카드는 옛 키도 읽는다 |
| TR2-16 | 회계연도 합산이 FY 행과 Q1~Q4를 함께 더하던 것 → FY가 있으면 그 한 행만, 없으면 분기 합. 기간 어휘는 fundamentals domain의 `parse_period`를 쓴다 | `trading/evidence/history.py` | 테스트 2개. FY 행을 섞는 주입 시 매출 200.0(정답 100.0) — 정확히 2배 확인 |
| EX2-03 | 주문 상태 어휘·전이표를 `orders/ledger.py` 한 곳으로 모으고 `replaced`를 종결 상태로 추가. 전에는 세 곳이 그 상태를 아는데 쓰는 곳 하나만 몰라 대사 패스가 통째로 끊겼다 | `execution/orders/ledger.py`, `orders/repository.py` | 새 테스트 4개(`classify_remote_order`의 반환 집합 ⊆ 전이 목표, 종결 상태 불변). `replaced` 제거 주입 시 2건 실패 확인. execution 231개 통과 |
| EX2-05 | 기준점 보관 컷오프가 조회 창과 **같은 상수**(`PRIOR_BASELINE_MAX_AGE`)를 쓴다. 보관 2일 · 조회 5일이라 연휴 뒤 첫 장에서 fallback이 이미 지워져 실주문이 전부 막혔다 | `execution/brokers/repository.py` | 테스트 2개. `timedelta(days=2)` 재도입 주입 시 실패 확인 |
| EX2-13 | `expire_due_approvals`를 승인 요청 진입점이 부르고, 만료된 승인은 재요청을 막지 않는다. 만료 판정은 **그 동작의 시각**으로 한다(한 실행 안에서 두 시계가 갈라지지 않게) | `execution/approval/repository.py`, `operations/commands/request_toss_approval.py` | 테스트 3개 + 진입점 Protocol에 계약 선언. 테스트 대역에 같은 계약을 추가해 픽스처가 리더보다 빈약한 상태를 없앴다 |
| OP2-01 | 재시도 예산을 `attempts`(stage 진입 횟수)가 아니라 새 `failures`(handler가 예외로 끝난 횟수)로 판정. 승인 대기·background 감싼 stage가 `waiting`으로 재진입하며 예산을 태워, 첫 일시적 오류가 곧바로 terminal 실패가 되던 것 | `operations/harness/state.py`, `harness/runtime.py` | 테스트 2개(대기 폴링 뒤 실패 1회에도 재시도 남음 / 반복 실패는 여전히 소진). `attempts` 판정 주입 시 실패 확인. 옛 state.json은 `failures`가 없어 0으로 시작(재시도 예산을 한 번 새로 받는 안전한 방향) |
| OP2-15 | ops 경보에 사건 단위 억제 창(30분) + 억제 건수 요약. 주기 60초 job이 영구 실패하면 하루 약 1,400건이 나가고 Discord 429가 삼켜져 **다른 실패가 묻혔다** | `operations/harness/reporting.py` | 테스트 5개(같은 원인 60회 → 발송 2회 이하, 로그는 60회 유지, 다른 job·다른 오류는 따로 발송). 억제 제거 주입 시 2건 실패 확인 |
| OP2-19 | 대사 명령의 종료 코드를 "재실행하면 달라지는가"로 되돌렸다. 사람이 확인할 발견 사항(외부 미체결·포지션 불일치)은 `reporter.error`로 한 번 올리고 0을 돌려준다 — 토스 앱 주문 하나로 job이 60초마다 영구 실패하던 것 | `operations/commands/reconcile_toss.py` | 테스트 3개(발견 사항은 실패 아님·조용하지도 않음 / 실행 실패는 여전히 1). 옛 동작 주입 시 실패 확인 |
| OP2-04 | 정비 보류를 **기동 경로**(`investment_harness.main`)가 확인해 `--serve`·`--run-once`를 거부한다. 거부 코드는 일반 실패(1)와 구분되는 3(`MAINTENANCE_HOLD_EXIT_CODE`) — 서비스가 1분마다 재시작을 시도하기 때문이다 | `operations/harness/maintenance.py`, `operations/commands/investment_harness.py` | 테스트 4개. 검사 제거 주입 시 2건 실패 확인 |
| AU-01 | 세그먼트 결측을 처방별로 두 check로 나눴다 — `segment_backfill_required`(증분 창 밖의 신규 추적 종목, 메시지에 `--scope missing` 명령 포함)와 `segment_processing_stuck`(처리 실패). **둘 다 ERROR 유지** | `data/fundamentals/infrastructure/supabase/integrity.py`, `application/verify_integrity.py` | 테스트 2개. 분리 제거 주입 시 실패 확인. 운영 대조로 FDXF·HONA·XOM이 전자에 해당함을 확인 |
| AU-02 | `econ_calendar_ics`의 cron 안전망 제거. 체인 29/29 발화·지연 0.0분인데 cron은 드롭 30%·지연 270분이라 커버리지 없이 하루 두 번 실행·두 번 실패 알림만 만들었다 | `.github/workflows/econ_calendar_ics.yml` | 워크플로 배선·예산 테스트 63개 통과. **예산 30.4 min/월 확보** |
| AU-03 | 매니저 성향·설명의 owner를 `STRATEGY_GROUP_PRESENTATION`(CIK → `strategy_group` → 라벨)으로 옮기고, 13F 화면의 이름 부분문자열 14쌍을 제거 | `data/institutional/domain/managers.py`, `dashboard/app_pages/gurus.py` | 테스트 4개(추적 7명 전원 라벨 해석 · 선언된 group 전부 라벨 보유 · 화면에 이름 needle 없음). 라벨 하나 제거 주입 시 2건 실패 확인. 7명 모두 옛 하드코딩과 **같은 문구**로 해석됨을 확인 |
| EX2-07(전송 전) | 요청 **전** 토큰 발급 실패를 `ExecutionSafetyError`(사전 안전 차단)로 승격. 전에는 `TossAuthError`가 worker의 except 세 개를 모두 빠져나가 `planned` 주문·`executing` intent가 남고 대사가 `planned`를 안 봐서 사람 손 없이는 안 풀렸다. **401 재전송 뒤(POST를 이미 보낸) 경로는 의미 결정이라 그대로 두고 보고만 했다** | `execution/brokers/toss/orders.py` | 테스트 2개(요청이 나가지 않음 확인). 옛 동작 주입 시 실패 확인 |
| OP2-11·12 | 보안 사전점검이 ① 숫자가 아닌 한도를 건너뛰지 않고 FAIL로 기록하고 ② 게이트가 읽는 다섯 번째 한도 `TOSS_MAX_DAILY_ORDERS`도 본다 | `operations/harness/security_audit.py` | 테스트 4개. **게이트(`LiveTradingControls.from_config`)가 읽는 `TOSS_MAX_*` 키 집합과 대조**해 손으로 나열한 목록이 다시 벌어지지 않게 고정. 한도 하나 제거 주입 시 3건 실패 확인 |
| TR2-09 | 베타 추정이 종목마다 benchmark 가격을 다시 파싱하던 것 → 파싱 결과를 호출 안에서 재사용. 보유 6종목 기준 파싱 12회 → 7회(benchmark 6회 → 1회) | `trading/portfolio/market_risk.py` | 테스트 1개(파싱 횟수 + **캐시 없는 계산과 값이 같음**). 캐시 제거 주입 시 실패 확인 |
| OP2-16 | 카운터 조회 실패를 카드에 적는다. 전부 실패하면 `🔢 대기 상태` 줄이 **그냥 사라져** "0건"과 구별되지 않았다 — 게이트가 정상적으로 0건을 내는 날을 잡는 유일한 줄이다 | `operations/commands/heartbeat.py` | 테스트 2개(일부 실패 / 전부 실패가 빈 성공이 아님) |
| OP2-17 | 자르기 한도를 **목적지가 정한다**(`PLAIN_TEXT_LIMIT` 1900 / `EMBED_LIMIT` 4000). 렌더러가 항상 1,900자로 잘라 4,096자를 쓰려던 embed에서 맨 뒤 `📡 채널 도착` 표가 사고 많은 날에만 사라졌다. 잘리면 `…(N자 생략)`을 남긴다 | `operations/monitoring/digest.py` | 테스트 4개. embed에 평문 한도를 주는 주입 시 실패 확인 |
| OP2-18 | 채널 ID가 숫자가 아닐 때 `snowflake_time`이 `try` 밖에서 터져 16개 채널 점검이 통째로 사라지던 것 → 그 채널만 `error` 행으로 남기고 나머지를 계속 읽는다 | `operations/monitoring/discord.py` | 테스트 3개. 옛 배치 주입 시 2건 실패 확인 |

### 9.1 운영 데이터로 확인한 것 (읽기 전용)

- **분할 조정 여부**(RR2-06의 전제): 최근 분할 4건의 전후 종가가 분할 비율만큼 떨어지지 않는다 —
  APH 2:1 `80.04 → 82.07`, CRWD 4:1 `193.18 → 193.98`, KLAC 10:1 `241.16 → 254.54`, CVNA 5:1 `80.00 → 77.94`.
  배당도 조정돼 있다 — KLAC 분기 배당이 분할 전 `0.19`·후 `0.23`(미조정이면 전자가 약 10배여야 한다).
- **세그먼트 누락 3종목**(AU-01): FDXF·HONA·XOM이 각각 신설 CIK(`0002082247`·`0002089271`·`0002115436`)이고,
  10-K/10-Q의 `filing_processing`에 `content_type='company'`(v1·v2, parsed)는 있으나
  **`segments` 행이 0개**다. 2026-09-13에 universe에 편입됐고 공시일은 08-03~08-05로 7일 lookback 밖이다.
- **섹터 충전율**(TR2-07): tracked 503 종목 / 500 CIK 중 `sic_division_name` 결측 **0건**.
- **알림 원장**: 선언 topic 15개 전부 baseline 보유(fail-closed 누락 0). `reporting` 뷰 14개 컬럼 계약 불일치 0.

### 9.2 이어서 고친 것 (같은 날, 두 번째 묶음)

| ID | 고친 것 | 파일 | 검증 |
|---|---|---|---|
| EX2-01 | 승인 요청·실행 재검증·미리보기가 **하나의 조립**(`whole_share_planner(planning_notionals(...))`)으로 planner를 만든다. 배치 합계 한도는 일 한도(`TOSS_MAX_DAILY_NOTIONAL_USD`)와 같은 값 하나로 줄이고 `TOSS_MAX_TOTAL_NOTIONAL_USD`는 없앴다 | `execution/safety/control.py`, `orders/planning.py`, `orders/live_worker.py`, `request_toss_approval.py`, `toss_preview.py` | 새 테스트 `test_planner_parity`. 기본값과 모두 다른 env로 두 planner의 한도가 같음을 단정. worker를 옛 하드코딩으로 되돌리면 실패 확인 |
| EX2-09 | `LiveExecutionPolicy`가 `(1+band)(1+수수료 여유) ≤ 1+계획 현금 버퍼`를 강제한다. 어기면 승인은 통과하고 실행은 항상 막힌다 | `execution/orders/live_worker.py` | 테스트 2개. 검사를 끄면 실패 확인 |
| EX2-10 | 수수료율이 5%를 넘으면 단위 오해(퍼센트·bp)로 보고 거절한다 | `execution/brokers/toss/orders.py` | 테스트 1개(0.1·7·10). 상한을 끄면 3건 실패 확인. **단위 결론은 여전히 명세 확인이 필요** — 상한은 조용히 100배 커지는 것을 막을 뿐이다 |
| EX2-17(h) | Toss endpoint 경로 상수 중복을 client 한 곳으로 | `brokers/toss/orders.py` | 기존 테스트 |
| OP2-05 | 정비 보류 메시지가 "새로 기동하지 않는다"로 바뀌고, 이미 도는 하네스가 있으면 멈추지 않았다는 경고와 `--off` 안내를 함께 낸다 | `operations/commands/harness_switch.py` | 테스트 2개. 경고를 끄면 실패 확인 |
| OP2-20 | 60초 주기 발표 watcher가 참조 master를 다시 upsert하지 않는다(등록은 daily ETL) | `operations/commands/econ_calendar_watch_releases.py` | watcher 테스트가 `seed_catalog`를 부르지 않음을 단정. 다시 부르면 실패 확인 |
| EX2-15·OP2-08·OP2-09·OP2-13·OP2-14 | 다른 세션이 먼저 고친 것을 확인했다(코드·테스트 존재) | `lifecycle.py`, `emergency.py`, `security_audit.py` | 전체 테스트 |
| TE-14 | 중복 `reconcile_orders`(`reconciliation/service.py`)와 그 전용 테스트를 지웠다. 실제 대사는 `worker.py`가 한다 | — | 참조 0건 확인 |

**하지 않은 것**: EX2-17의 (a)~(g)는 실주문 원장 쓰기 의미를 바꾸는 항목이라 고치지 않고 남긴다. 은행·리츠 매출 합산은 하지 않는다 —
총계 태그가 없는 은행의 매출은 "이자수익+비이자수익"이라는 합성 규칙이 필요하고, 그러려면 fundamentals 전체(약 19,000개 공시)를
`SEMANTIC_POLICY_VERSION` v3로 다시 처리해야 한다. 그 대가로 얻는 것은 P/S가 의미 없는 은행 몇 종목의 매출뿐이고, 재처리 중에는
Actions(v2 코드)와 운영 DB(v3)가 어긋난다.

## 10. 인계 — 다음 세션이 이어서 할 일

**이 절이 작업 목록이다.** 항목표의 `예정(…)` 행이 곧 아래 목록이고, 원본 근거는 `raw/2026-09-21-*.txt`에
ID로 검색하면 나온다. 각 항목은 "고치는 법"까지 raw에 적혀 있다.

### 10.1 코드만으로 가능 (권장 순서)

1. **값 오류 남은 것**: TR2-16(`fundamental_trend` 연간 합산이 FY+Q1~Q4를 더한다 — 현재 죽은 코드),
   TR2-11(`daily_return`이 하루가 아니다), TR2-13(순 기대수익 0인데 confidence 1.0),
   EX2-15(`LifecyclePromotionGate` 낙폭 부호 — 죽은 코드).
2. **실행 경계**(정비 보류 유지 필수): EX2-01(승인·실행 planner 한도 불일치), EX2-03(`REPLACED` 전이),
   EX2-07(제출 시점 인증 실패 → 고아 `planned`), EX2-05(기준점 보관 2일 vs 조회 5일),
   EX2-13(`expire_due_approvals` 미호출), EX2-09·10(현금 여유·수수료율 검증기).
3. **operations**: OP2-01(waiting 폴링이 attempts 소진 — 높음), OP2-04(정비 보류가 진입점을 안 막음 — 높음),
   OP2-15(1분 job 영구 실패 시 webhook 폭주 — 높음), OP2-19(대사 결과를 실패로 오역 — 높음),
   그다음 OP2-08·09·11·12·13·14·16·17·18·20.
4. **워크플로·시각**: AU-01(정합성 점검을 "신규 추적 backfill 필요"와 "처리 실패"로 나눠 각각 ERROR로),
   AU-02(`econ_calendar_ics`의 cron 안전망 제거), `fundamentals_integrity`를 `fundamentals_daily` 체인으로.
5. **하드코딩·구조**: AU-03(13F 화면 성향을 CIK catalog로), TR2-09(benchmark 재파싱), OP2-20(1분마다 master upsert).

### 10.2 함정 (실제로 부딪힌 것)

- **`load_dotenv()`는 스크립트 파일 위치에서 `.env`를 찾는다.** scratchpad에 둔 조회 스크립트는
  `load_dotenv(dotenv_path='.env', override=True)`로 명시해야 한다.
- **`SUPABASE_DB_URL`(pooler 5432)은 이 네트워크에서 timeout**이다. 운영 조회는 PostgREST(`platform.db.postgres.sb`)로 한다.
- **전체 테스트 중 `src/**/tmpXXXX/probe.py`가 생겼다 사라진다**(`test_view_reachability`). AST 전수 스캔은
  파일 목록을 만든 뒤 `OSError`를 견뎌야 한다.
- **콘솔이 cp949**라 파이썬 출력에 한국어가 깨진다. `PYTHONIOENCODING=utf-8`을 붙인다.
- **서브에이전트를 opus로 4개 동시에 돌리면 세션 한도가 빨리 소진된다.** 사용자 지시에 따라
  이번 세션 후반은 서브에이전트 없이 진행했다. 발견을 raw 파일에 즉시 append하는 방식 덕에
  중간 종료된 3개의 결과는 남았다.
- **`RR2-02`처럼 "주석과 코드가 다르다"는 발견은 어느 쪽을 고칠지가 판단**이다. 이번에는 문턱을 올리면
  RR2-01의 재정규화 편향이 커지는 상호작용이 있어 코드를 그대로 두고 주석을 고쳤다.

### 10.3 이번 세션이 하지 않은 것

commit·push, 운영 DB 쓰기·DDL·DML, Discord 발송, 하네스 실행·재시작, 알림 재발송, 재적재,
`LIVE_ENABLED`·킬스위치 변경. 정비 보류(`MAINTENANCE_HOLD`)는 만들지도 풀지도 않았다.
