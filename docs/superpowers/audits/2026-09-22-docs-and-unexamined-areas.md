# 문서 전면 재설계와 미점검 영역 3차 — 실재하지 않는 것을 가리키는 문서

2026-09-22 시점의 점검이다. [2차 감사](2026-09-21-code-quality-overhaul.md)가
"[확인하지 못한 영역](2026-09-21-code-quality-overhaul.md#7-확인하지-못한-영역)"으로 남긴 곳과,
1·2차가 **아예 손대지 않은 문서 계층 전체**에서 출발했다.

1·2차가 이미 센 항목은 다시 세지 않는다. 회귀만 한 줄로 확인한다.
원본 분석은 `raw/2026-09-22-*.txt`에 있다.

## 0. 방법과 한계

| 표시 | 뜻 |
|---|---|
| **확정** | 코드 경로를 끝까지 읽었고 재현 논리를 적을 수 있거나, 운영 데이터·원천 수치로 확인했다 |
| **의심** | 정황은 강하지만 위 수준의 확인을 못 했다 |

- **작업 트리 상태**: 시작 시점에 2차 감사의 미커밋 변경 44개가 있었다(마지막 mtime 14:42,
  이 세션 시작 14:58). 그 세션이 끝난 뒤 이어받았다.
- **다른 세션이 같은 트리를 동시에 고쳤다.** 이 세션이 도는 동안(14:58~15:18) 내가 건드리지
  않은 파일이 새로 바뀌었다 — `operations/harness/background.py`, `operations/harness_adapters.py`,
  `research/storage/repository.py`, `tests/.../test_background_stages.py`(신규),
  `tests/.../test_investment_adapters.py`, `tests/investment_agent/research/storage/`(신규),
  그리고 새 문서 `docs/SYSTEM_UPGRADE_DESIGN.md`(추적되지 않음). **그 파일들은 읽기만 했고
  고치지 않았다.** 내가 고친 파일과 겹치지 않는다.
  그래서 아래 테스트 수 차이에는 **그 세션이 추가한 테스트도 섞여 있다** — 이 세션이 만든
  테스트만의 수는 12절의 가드 목록으로 세는 것이 정확하다.
  `docs/SYSTEM_UPGRADE_DESIGN.md`는 추적되지 않아 이번에 만든 문서 가드의 대상이 아니다.
  커밋되면 제목 형식·링크·모듈 경로 검사를 함께 받게 된다.
- **운영 데이터**: PostgREST(service role) **읽기 전용**만 썼다. DDL·DML·쓰기 없음.
- **쓰지 않은 것**: 운영 DB 쓰기, Discord 발송, 하네스 실행·재시작, commit·push, 재적재,
  `LIVE_ENABLED`·킬스위치 변경. 정비 보류는 만들지도 풀지도 않았다.

## 1. 요약

새로 찾은 항목 **18개**(확정 16 · 의심 2). 1·2차가 센 항목은 다시 세지 않았고, 그중 6개는
회귀만 확인했다(7.1절).

| 심각도 | 개수 | 내용 |
|---|---:|---|
| 높음 | 2 | RS3-01(순위 상관이 행 순서에 따라 ±1) · FD3-01(읽을 수 없는 `qtrs`를 시점값으로 접음) |
| 중간 | 9 | RS3-02 · RS3-04 · RS3-06 · RS3-07 · TR3-01 · DOC-01 · DOC-03 · DOC-05 · DOC-06 |
| 낮음 | 7 | RS3-03 · RS3-05 · TR3-02 · FD3-02 · RP3-01 · DOC-02 · DOC-04 |

**고친 것 11개 / 부분 수정 2개 / 보고만 5개.** 새 테스트는 전부 위반 주입으로 검증했다.

- **테스트**: 시작 기준선 **3,473개 OK**(skipped 1, 184초) → 마무리 **3,499개 OK**(skipped 1, 212초).
  **실패 0.** 늘어난 26개 중 **17개가 이번 세션의 것**이고(아래), 나머지는 같은 시간에 도는
  다른 세션이 추가한 것이다(0절).

  | 파일 | 전 → 후 |
  |---|---|
  | `tests/test_docs_consistency.py` | 16 → 22 (+6) |
  | `tests/investment_agent/research/system_validation/test_ablation.py` | 5 → 9 (+4) |
  | `tests/investment_agent/research/models/test_baselines.py` | 2 → 4 (+2) |
  | `tests/investment_agent/data/fundamentals/test_segment_periods.py` | 2 → 4 (+2) |
  | `tests/investment_agent/dashboard/test_news_social_page.py` | 4 → 6 (+2) |
  | `tests/investment_agent/trading/portfolio/test_market_risk.py` | 10 → 11 (+1) |
- **이번 세션의 무게중심**: 1·2차가 손대지 않은 **문서 계층 전체**와, 2차가 남긴 미점검 영역.
  문서는 줄일 것이 없었고(8.1절) **틀린 것을 고치는 일**이었다.
- 가장 값비싼 두 항목은 둘 다 같은 모양이다 — **결측과 실제 값을 같은 값으로 접은 것**.
  `argsort`가 동률을 순서로 가른 것(RS3-01)과 `qtrs`를 못 읽으면 0으로 둔 것(FD3-01).

## 2. 항목표

| ID | 영역 | 한 줄 | 확정/의심 | 심각도 | 상태 |
|---|---|---|---|---|---|
| RS3-01 | research | `baselines.py` 순위 상관이 동률을 등장 순서로 갈라, 상수 예측(naive)의 값이 표본 행 순서에 따라 ±1이 된다 | 확정 | 높음 | 수정됨 |
| RS3-02 | research | 같은 `rank_correlation` 이름을 네 구현이 서로 다르게 계산한다 | 확정 | 중간 | 부분 수정 |
| RS3-03 | research | `direction_accuracy` 정의가 두 곳에서 다르다(label 0 처리) | 확정 | 낮음 | 보고만 |
| RS3-04 | research | `export_dataset`의 주석이 막았다고 말하는 일(manifest가 학습 구간을 거짓 주장)이 그대로 일어난다 | 확정 | 중간 | 부분 수정 |
| RS3-05 | research | benchmark label 기본값 0.0이 결측을 0% 수익으로 접는다(운영 경로는 strict, 읽는 곳 0건) | 확정 | 낮음 | 보고만 |
| RS3-06 | research | Ablation 정직성 검사가 변형 **이름 목록**에 묶여, `--cvar-limits`로 준 다른 한도는 검사를 건너뛴다 | 확정 | 중간 | 수정됨 |
| RS3-07 | trading | 같은 CVaR95에 한도가 둘(0.08 / 0.0872)이고 서로 유도되지 않는다 | 확정 | 중간 | 보고만(위험 의미) |
| TR3-01 | trading | 사건 재분석이 보유 종목 종가를 proxy마다 다시 파싱(측정 65회 → 17회) | 확정 | 중간 | 수정됨 |
| TR3-02 | trading | 전역 사건 조회가 저장소를 전 기간 읽고 파이썬에서 48시간만 남긴다 | 의심 | 낮음 | 보고만 |
| FD3-01 | fundamentals | 읽을 수 없는 `qtrs`를 `0`(=시점값)으로 접어 3개월 흐름을 잔액으로 라벨링한다 | 확정 | 높음 | 수정됨 |
| FD3-02 | fundamentals | `fy`를 못 읽으면 `period_end.year`로 대체한다(비달력 회계연도에서 어긋날 수 있다) | 의심 | 낮음 | 보고만 |
| RP3-01 | reporting | intelligence 리더 머리주석이 네 함수 중 하나만 지키는 계약을 주장한다 | 확정 | 낮음 | 수정됨 |
| DOC-01 | 문서 | `docs/OPERATIONS.md`가 없는 모듈 경로(`decision.llm.agents.orchestrator`)를 부른다 | 확정 | 중간 | 수정됨 |
| DOC-02 | 문서 | `fundamentals/domain/README.md`가 `domain` 계층을 뺀 경로를 부른다 | 확정 | 낮음 | 수정됨 |
| DOC-03 | 문서·코드 | `institutional` 문서와 **오류 메시지**가 없는 표처럼 읽히는 경로를 부른다 | 확정 | 중간 | 수정됨 |
| DOC-04 | 문서 | `AUTONOMOUS_SYSTEM.md`가 `alpha.py`를 두 줄로 적는다(병합 흔적) | 확정 | 낮음 | 수정됨 |
| DOC-05 | 문서 | 같은 문서가 `evaluator.py`를 `trading/portfolio/`에 있다고 적는다 — 실제는 `research/evaluation/` | 확정 | 중간 | 수정됨 |
| DOC-06 | 문서 | 위험 한도 표가 `max_pairwise_correlation`·`max_concentration_hhi`를 빼먹었다 | 확정 | 중간 | 수정됨 |
## 3. 수정 원장 — 무엇을 고쳤고 어떻게 확인했나

새 가드는 전부 **위반을 하나씩 주입해 실제로 실패하는지 확인**하고 `try/finally`로 복원했다.

| ID | 고친 것 | 파일 | 검증 |
|---|---|---|---|
| RS3-01 | 순위 상관이 동률을 등장 순서로 가르던 것을 **평균 순위**로. 상수 예측(naive)의 값이 0이 된다. 올바른 구현을 `research/evaluation/alpha.py`의 `average_ranks`로 공개해 다섯 번째 사본을 만들지 않았다 | `research/models/baselines.py`, `research/evaluation/alpha.py` | 테스트 2개. 옛 `argsort(argsort(...))` 주입 시 `0.9999 != 0.0`, 동률 재배치에서 `-0.90 != -0.80` 둘 다 실패 확인 |
| RS3-04 | 주석이 "막았다"고 말하던 것을 현실대로 고쳤다 — manifest의 세 기간은 as_of를 1/3씩 나눈 **추정값**이고 학습 구간은 `artifact.train_period`만 말한다. **계약 변경(기간을 optional로)은 사용자 결정으로 올린다** | `research/commands/export_dataset.py` | 기존 `test_periods_group_every_ticker_of_the_same_as_of`가 추정 규칙을 이미 고정한다 |
| TR3-01 | `estimate_betas`에 `closes_cache`를 노출하고 사건 재분석이 테마별 proxy 사이에서 하나를 공유한다 | `trading/portfolio/market_risk.py`, `trading/decision/candidates.py` | 테스트 1개(파싱 9회 + **캐시 없는 계산과 12자리까지 같은 베타**). 캐시 무시 주입 시 `21 != 9` 실패 확인 |
| DOC-01·02·03 | 실재하지 않는 모듈 경로 3곳. DOC-03은 **코드의 오류 메시지**까지 같은 낡은 경로를 말해 운영자가 없는 표(`institutional.managers`)를 찾아가게 했다 | `docs/OPERATIONS.md`, `fundamentals/domain/README.md`, `institutional/README.md`, `institutional/application/etl.py` | 새 가드 `NamedModulePathTest`. 낡은 경로 재주입 시 실패 확인 |
| DOC-04·05 | 중복 `alpha.py` 줄 제거, `trading/portfolio/` 블록에서 없는 `evaluator.py`를 빼고 실제 있는 `market_risk.py`·`contracts.py`를 적었다 | `docs/AUTONOMOUS_SYSTEM.md` | 새 가드 `NamedSourceFileTest`. 없는 경로 재주입 시 실패 확인 |
| DOC-06 | 위험 한도 표에 `max_pairwise_correlation`(0.95)·`max_concentration_hhi`(0.15)를 넣고, **HHI 한도가 종목 상한에 가려 발동하지 않는다**는 사실(2차 TR2-01)을 문서에 적었다 | `docs/INVESTMENT_SYSTEM.md` | 새 가드 `RiskLimitDocumentationTest` |
| RS3-06 | 정직성 검사를 이름 목록이 아니라 **정책 차이**로 판정한다(`use_tail_risk`·`use_market_risk`·`max_cvar_95_5d`를 기준 정책과 비교). 같은 파일이 ml·thesis는 이미 속성으로 판정하고 있었다 | `research/system_validation/ablation.py` | 테스트 4개. 옛 이름 목록 주입 시 `None != 'risk_policy_never_exercised'` 실패 확인 |
| FD3-01 | `_qtrs`가 못 읽으면 `None`을 돌려주고 그 행을 버린다. `0`은 이 도메인의 실제 값이라 결측과 섞일 수 없다 — 같은 파일의 다른 필드는 이미 그 규약을 쓴다 | `data/fundamentals/domain/services/normalize_segment_facts.py` | 테스트 2개(subTest 4). `return 0` 주입 시 4개 전부 `[{...}] != []` 실패 확인 |
| RP3-01 | 머리주석이 실제 계약을 말하게 했다 — 저장소 상태를 말하는 것은 `load_overview()` 하나뿐이고, 화면이 그것을 **먼저** 보는 순서가 실제 보호다 | `reporting/readers/intelligence.py` | 새 가드 `StoreAvailabilityGateTest`(AST). 게이트 밖 호출 주입 2건 모두 실패 확인 |

### 2.1 새 가드 3개 (전부 주입 확인)

모두 `tests/test_docs_consistency.py`에 있다. 문서 테스트는 16개 → **21개**가 됐다.

| 가드 | 무엇을 막는가 | 공허 통과 방지 | 주입 결과 |
|---|---|---|---|
| `NamedModulePathTest` | 문서가 부르는 `investment_agent.…` 경로가 실재하지 않는 것. 트리 그림·본문 코드 표기는 링크가 아니라 기존 링크 검사가 못 봤다 | 경로를 80개 이상 모았는지 먼저 본다 | 낡은 `institutional.managers.MANAGER_CATALOG` 재주입 → 파일·행 번호와 함께 실패 |
| `NamedSourceFileTest` | 문서가 나열하는 `src/investment_agent/….py`가 없는 것 | 40개 이상 모았는지 먼저 본다 | 없는 `trading/portfolio/evaluator.py` 재주입 → 실패 |
| `RiskLimitDocumentationTest` | 코드의 hard risk limit 값·항목이 문서 표와 벌어지는 것. **정책의 모든 수치 한도가 표에 있어야** 하므로 한도를 새로 추가하면 문서를 고칠 때까지 실패한다 | 표를 찾았는지(칸 8개 이상·`10%` 포함)와 한도 10개 이상을 셌는지 | 값 변경 2건(0.10→0.12, 1.50→2.50)과 한도 추가 1건 모두 실패 |

`RiskLimitDocumentationTest`는 처음에 **문서 전체에서 숫자를 찾는** 방식이었고, 그러면
0.10을 0.12로 바꿔도 **통과했다**(777줄 어딘가에 0.12가 있다). 그래서 한도 표의 값 칸으로
좁혔다. 가드를 만들 때 주입을 해보지 않으면 이런 것이 그대로 남는다.

## 4. 음성 결과 — 다음 세션이 다시 하지 않아도 되는 것

전수로 훑었고 **결함이 없었다**. 스캔이 공허하지 않은지 양성 대조로 확인한 것만 적는다.

| 훑은 것 | 결과 | 공허 통과 확인 |
|---|---|---|
| naive datetime(`date.today()`·`datetime.now()` 무시간대) | **0건** (주석 언급 2곳뿐) | — |
| Postgres 선언 컬럼 355개(표 28개) 중 코드·문서·뷰 어디에서도 안 쓰이는 컬럼 | **0건** | `CREATE TABLE` 본문을 코퍼스에서 빼 자기참조 통과를 막고, `zzz_orphan_column`=없음/`sic_division_name`=있음으로 대조 |
| 문서가 부르는 repo 경로(`src`/`db`/`tests`/`scripts`/`prompts`) | 후보 17건 **전부 오탐** | 오탐 원인: `docs/diagrams/src/*.json` 꼬리 매치, `scripts/harness/on|off|status` 파이프 표기, `db/postgres.py` 상대 표기 |
| 문서가 부르는 워크플로 `.yml`·`scripts/` 파일 | **0건 누락** | — |
| `docs/README.md`(문서 지도)가 주장하는 경로 14개 | **전부 실재** | — |
| 위험 한도 표의 9개 값 vs `PortfolioRiskPolicy` | **전부 일치**(빠진 항목 2개만 추가) | — |

## 5. 가드를 만들 때 실제로 겪은 것 — 공허하게 통과한 가드 하나

`StoreAvailabilityGateTest`의 첫 판은 게이트 안팎을 **이름 집합의 차집합**으로 셌다.

```text
outside = {게이트 밖 호출 이름} - {게이트 안 호출 이름}
```

게이트 안에도 `load_news`가 있으므로, 게이트 **밖에** `load_news`를 하나 더 넣어도
차집합이 비어 **통과했다**. 호출 **자리**(`id(node)` + `lineno`)로 세도록 고쳐서야 잡혔다.

`RiskLimitDocumentationTest`도 같은 일을 겪었다 — 처음엔 문서 **전체**에서 숫자를 찾았고,
777줄 어딘가에 `0.12`가 있어서 `max_symbol_weight`를 0.10→0.12로 바꿔도 통과했다.
한도 표의 값 칸으로 좁혀서야 잡혔다.

둘 다 **주입을 해보지 않았으면 그대로 남았을 가드**다. 이번 세션이 만든 가드 5개는
전부 위반을 하나씩 주입해 실패를 확인했다.

## 6. 도구·환경 함정 (2차의 목록에 더한다)

- **빠른 주입/복원 루프에서 `__pycache__`가 재사용된다.** mtime 해상도 때문에 이전 주입의
  실패 메시지가 다음 주입 결과로 보였다. `-B` + `PYTHONDONTWRITEBYTECODE=1` + 1초 이상 간격을
  주거나, 규칙대로 **한 번에 하나씩** 주입한다.
- **한 파일 안에 CRLF와 LF가 섞여 있다.** `tests/.../test_market_risk.py`는 CRLF 149줄 · LF 230줄이다.
  파일 전체로 줄바꿈을 판정하면 치환이 조용히 실패한다 — 치환할 **그 구간**의 줄바꿈을 본다.
- **도구 호출이 정규식의 ``를 백스페이스(``)로 바꿔 저장했다.** 저장 뒤 파일을 다시 읽어
  `repr`로 확인해야 한다. 이번에는 `chr(92)`로 조립해 피했다.
- `subprocess`로 테스트를 돌릴 때 `encoding="utf-8"`을 주지 않으면 콘솔 cp949로 디코딩하다 죽는다.

## 7. 시각·예산 — 이번에는 바꾸지 않았고, 왜 그런지

2차 감사가 `gh run list` 실측으로 시각을 재설계했고(AU-02), 그 수정이 코드에 그대로 있다.
이번 세션은 **예산부터 확인했고, 그 결과가 제안을 막았다.**

`python scripts/actions_budget.py` (이 세션 실행):

```text
SCHEDULED TOTAL      1818.0 min/month
allowance            2000   min/month
headroom              182.0 min/month  (91% used)
```

스크립트가 스스로 "여유가 30% 미만이다. retry·debug·수동 실행 몫이 부족하다"라고 말한다.
**따라서 실행 횟수를 늘리는 어떤 제안도 이번에는 성립하지 않는다.** 시각을 옮기는 제안
(횟수 동일)은 근거 수치가 더 필요하고, 2차가 이미 실측으로 정리한 구간이라 이번에는 손대지 않았다.

실측이 한 가지를 계속 말한다 — `econ_calendar_watch`는 **설계 347.9회/월인데 실측 25.7회/월**이다.
GitHub이 고빈도 cron을 버린다. 이 격차는 2차의 AU-02(체인이 cron보다 정확하다)와 같은 사실의
다른 얼굴이고, 고빈도 감시는 Actions cron이 아니라 로컬 하네스가 맡아야 한다는 뜻이다.

### 2차 감사 수정의 회귀 확인 (다시 세지 않고 존재만)

| 항목 | 확인 |
|---|---|
| AU-02 `econ_calendar_ics` cron 제거 | `workflow_run`만 있고 `schedule` 없음 + 근거 주석 |
| OP2-01 `failures` 기반 재시도 예산 | `harness/state.py`에 6곳 |
| OP2-04 정비 보류가 기동을 막음 | `MAINTENANCE_HOLD_EXIT_CODE = 3` |
| EX2-05 기준점 보관·조회 상수 통일 | `PRIOR_BASELINE_MAX_AGE = timedelta(days=5)` 한 곳에서 공유 |
| TR2-01 HHI 도달 상한 | `reachable_concentration_hhi` 3곳 |
| RR2-09 `total_debt` 공유 정의 | `fundamentals/domain/services/leverage_metrics.py`를 reporting·research 둘 다 사용 |

## 8. 문서 재설계 결과

### 7.1 전수 목록과 판정

저장소가 추적하는 `.md`는 **51개**다(`graphify-out/`·`.claude/`·`.codex/`·`.agents/`·
`.superpowers/`는 외부가 설치·생성하는 것이라 뺐다). 계층은 이미 읽는 순서대로 서 있었다.

| 층 | 개수 | 판정 |
|---|---:|---|
| 루트 진입점 (`README`·`CLAUDE`·`AGENTS`·`DESIGN-system`) | 4 | 유지 |
| `docs/` 중심 문서 | 11 | 유지 — 주제별 owner가 겹치지 않는다 |
| `docs/superpowers/audits/` | 3(+이번 1) | 유지 — 도달 경로만 고쳤다(아래) |
| `prompts/` | 3 | 유지 — 코드가 아니고 외부 GPT 질의 템플릿이다(`CLAUDE.md`가 이미 선언) |
| 패키지 README·계약 문서 | 30 | 유지 |

**합치거나 지운 문서는 없다.** 겹침을 찾으려고 `INVESTMENT_SYSTEM`·`AUTONOMOUS_SYSTEM`·
`SYSTEM_ARCHITECTURE`·`EXECUTION_AND_SAFETY`·`DATA`를 대조했지만, `docs/README.md`의
"목적별로 읽을 문서 하나" 표가 이미 주제마다 owner를 하나로 못박고 나머지는 링크로만 부른다.
같은 사실을 두 곳이 주장하는 경우를 찾지 못했다 — **줄일 것이 아니라 틀린 것을 고치는 일이었다.**

### 7.2 고친 것

| 무엇 | 왜 |
|---|---|
| 모듈 경로 3곳 (DOC-01·02·03) | 실재하지 않는 곳을 가리켰다. DOC-03은 **코드의 오류 메시지**까지 같은 낡은 경로여서 운영자가 없는 표를 찾아가게 했다 |
| `AUTONOMOUS_SYSTEM.md`의 중복 `alpha.py` 줄 (DOC-04) | 병합 흔적. 같은 파일에 설명이 둘이었다 |
| 같은 문서의 `evaluator.py` 위치 (DOC-05) | Trading에 있다고 적었지만 Research 소유다. 계층 방향을 거꾸로 이해하게 만든다 |
| `INVESTMENT_SYSTEM.md` 위험 한도 표 (DOC-06) | 게이트가 강제하는 한도 2개가 빠져 있었다. HHI 한도가 **발동하지 않는다**는 사실도 함께 적었다 |
| `reporting/readers/intelligence.py` 머리주석 (RP3-01) | 네 함수 중 하나만 지키는 계약을 전부가 지키는 것처럼 말했다 |
| `research/commands/export_dataset.py` 주석 (RS3-04) | 막았다고 말한 일이 그대로 일어나고 있었다 |
| `docs/README.md`의 감사 도달 경로 | 아래 |

### 7.3 고아 문서 — 51개 중 3개, 그중 1개가 진짜

어떤 문서도 링크하지 않는 문서를 전수로 셌다.

- `data/fundamentals/data/NOTICE.md`, `data/institutional/NOTICE.md` — 데이터 출처 고지다.
  **코드 주석이 부른다**. 문서 사이 링크가 없는 것이 정상이다.
- `docs/superpowers/audits/2026-09-21-code-quality-overhaul.md` — **진짜 고아였다.**
  `docs/README.md`는 2026-09-20 보고서의 한 절만 링크하고, 그 뒤 보고서는 어디서도 닿지 않았다.
  각 보고서는 **이전** 것을 링크하므로 뒤로는 이어지는데 **앞으로 들어오는 문이 없었다**.

고칠 때 최신 파일 이름을 `docs/README.md`에 적지 않았다 — 적으면 다음 점검 때 갱신되지 않고
낡는다(이 저장소가 이미 겪은 드리프트다). 대신 **폴더**를 링크하고 "각 보고서가 이전 것을
링크하니 최신부터 거슬러 읽어라"고 적었다.

### 7.4 SSOT 판정

이번에 바꾼 owner는 없다. 확인한 것만 적는다.

| 사실 | owner | 확인 |
|---|---|---|
| hard risk limit 값 | `trading/risk/gate.py` | 문서 표 9개 값이 코드와 일치. 새 가드가 방향(코드→문서)을 고정 |
| 13F 매니저 catalog | `data/institutional/domain/managers.py` | 문서·오류 메시지의 경로를 그쪽으로 맞췄다 |
| 순위 상관 계산 | `research/evaluation/alpha.py::average_ranks` | 네 사본 중 틀린 하나를 여기로 모았다 |
| 알림 KIND 목록 | `operations/commands/notify.py::KINDS` | 기존 가드가 이미 강제 |
| 환경변수 목록 | `docs/ENV.md` | 기존 가드가 이미 강제 |

## 9. 시도했지만 가드로 쓸 수 없던 방법 (다음 세션이 반복하지 않게)

두 가지 전수 대조를 만들었고, **둘 다 오탐이 너무 많아 가드로 쓰지 않았다.** 방법과 이유를
적어 둔다 — 결과가 깨끗해 보여도 그것은 방법의 한계일 수 있다.

| 방법 | 결과 | 왜 못 쓰는가 |
|---|---|---|
| 읽기만 하고 아무도 만들지 않는 dict 키(AST) | 85종 후보 → 실제 결함 0 | f-string으로 만드는 키를 못 본다. `output[f"return_{horizon}d"]`가 `return_252d`를, `output[f"{field}_change"]`가 `eps_avg_change`를 만든다. 나머지는 외부 API 응답 키다 |
| research dataset 읽기 vs 쓰기 | 2건 불일치 → 1건은 오탐 | 읽기가 `records()` 직접 호출만이 아니다. `training_samples`는 `load_local_research_records()` 헬퍼와 `record_keys()`로 읽힌다. 메서드 이름 목록에 의존하면 목록이 계속 자란다 |

그 과정에서 얻은 사실 하나는 남길 가치가 있다 — **`ResearchStore._dataset_root`는 dataset
이름의 형식만 검사하고 선언 목록과 대조하지 않는다**(`research/storage/repository.py:571`).
그래서 이름을 잘못 적으면 예외가 아니라 **빈 목록**이 온다. `portfolio_evaluations`가 조용히
비어 있는 구조적 이유이기도 하다.

## 10. 확인 못 한 영역

- **`trading/decision/llm/*`** (`runtime.py` 725줄)과 `decision/agents`의 프롬프트 경로: 2차와
  같은 이유로 오프라인 재현이 불가하다. 이번에도 값 로직을 검증하지 못했다.
- **`notifications/*` 카드의 시각 검증**(스크린샷): 하지 않았다. 1·2차도 하지 않았다 —
  세 세션 연속 미점검 영역이다.
- **로컬 SQLite·DuckDB의 실제 값**: 읽지 않았다. `portfolio_evaluations`가 비어 있다는 판정은
  "쓰는 코드가 없다"는 정적 사실에 근거한다.
- **`FD3-01`의 과거 오염 규모**: `is_instant`·`period_start`가 저장되지 않아(메모리 전용)
  Postgres로는 셀 수 없다. 코드가 옳아진 것만 확실하다.
- **`FD3-02`**(`fy` 결측 시 `period_end.year` 대체): SEC `sub.txt`의 `fy`가 실제로 비는 빈도를
  확인하지 못해 의심으로 남긴다.
- **`TR3-02`**(전역 사건 전 기간 조회): `events` 행에 `as_of`가 있는지, `available_at`과 얼마나
  벌어지는지 확인하지 못했다. 좁히면 늦게 공개된 사건을 놓칠 수 있어 손대지 않았다.
- Actions 실패율·체인 지연 **재측정**은 하지 않았다. 2차가 한 달 창으로 측정했고 그 수정이
  코드에 있다. 다시 재는 것은 그 창이 갱신된 뒤가 의미 있다.

## 11. 사용자 결정·실행이 필요한 것

이번 세션은 **운영 DB 쓰기·DDL·DML, Discord 발송, 하네스 실행·재시작, commit·push, 재적재,
`LIVE_ENABLED`·킬스위치 변경을 하지 않았다.** 정비 보류(`MAINTENANCE_HOLD`, 2026-09-20T15:53Z,
사유 "repository upgrade: runtime audit and offline validation")는 그대로이고 만들지도 풀지도 않았다.

### 10.1 결정이 필요한 것

| ID | 무엇 | 왜 내가 안 했나 |
|---|---|---|
| RS3-07 | 같은 CVaR95에 한도가 둘(System 0.08 / Gate 0.0872)이고 서로 유도되지 않는다. "게이트 한도 ≥ System 한도"를 계약으로 고정할지 | **hard risk limit의 의미를 바꾸는 변경**이다(규칙 C). 지금은 System 한도를 0.0872 위로 올리면 파이프라인이 자기 게이트가 거절하는 목표를 만든다 |
| RS3-04 | `DatasetManifest`의 세 기간을 optional로 바꿔 "여기서 split을 정하지 않았다"를 표현할지 | 계약 변경이고 테스트 2개(`tests/native/test_native_core.py`, `test_dataset_export.py`)를 함께 고쳐야 한다. 지금은 주석이 사실을 말하게만 고쳤다 |
| RS3-03 | `direction_accuracy` 정의를 두 곳에서 통일할지(label 0을 어느 쪽으로 셀지) | 값의 의미를 정하는 결정이다. 통일하면 저장된 artifact의 수치와 새 수치가 달라진다 |
| RS3-02 | `rank_correlation`을 dense rank(`evaluation/metrics.py`)와 average rank(`evaluation/alpha.py`) 중 하나로 통일할지 | 둘 다 행 순서에 의존하지 않아 **조용히 틀리지는 않는다**. 통일은 값이 바뀌는 결정이다 |

### 10.2 이전 세션에서 넘어온, 아직 사용자 몫인 것

2차 보고서 6절이 원본이다. 이번에 상태가 바뀐 것은 없다.

- 실주문 안전 의미: EX2-02 · EX2-08 · EX2-16 · OP2-06
- 설계 결정: EX2-12(`reconciliation_runs` 생산자) · TR2-14(시나리오별 스트레스 한도) · RR2-07(백테스트 `price_basis`)
- 재적재·운영 조치: `econ-calendar` 공개 버킷 생성, 신규 추적 CIK 세그먼트 backfill, 은행·리츠 매출 `SEMANTIC_POLICY_VERSION` v3 승격
- RS-15: `portfolio_evaluations` 생산자가 없어 승격 게이트가 영구 fail-closed다. 생산자를 만들지, 게이트에서 그 조건을 빼지 결정이 필요하다

### 10.3 예산이 막은 것

`scripts/actions_budget.py`가 **91% 사용 / 여유 182분**을 말한다. 실행 횟수를 늘리는 제안은
지금 성립하지 않는다. `econ_calendar_watch`(설계 347.9회/월 → 실측 25.7회/월)를 Actions cron에서
로컬 하네스로 옮기는 것은 **횟수를 늘리지 않으면서** 감시 빈도를 회복하는 방향이지만,
하네스 부하·정비 보류 상태와 얽혀 있어 결정으로 올린다.

## 12. 인계 — 다음 세션이 이어서 할 일

**이 절이 작업 목록이다.** 근거는 `raw/2026-09-22-docs.txt`에 ID로 검색하면 나온다.

### 11.1 코드만으로 가능 (권장 순서)

1. **3세션 연속 미점검인 것부터**: `notifications/*` 카드의 **시각 검증**. 1·2·3차가 모두
   건너뛰었다. 카드는 Jinja2 → Playwright PNG라 렌더해 눈으로 봐야 하는 유일한 영역이고,
   값 테스트가 전부 통과하는 동안 레이아웃이 깨져 있을 수 있다(대시보드가 실제로 그랬다 —
   메모리 `dashboard-had-no-render-test`).
2. **`trading/decision/llm/runtime.py`(725줄)**: 세 세션이 "오프라인 재현 불가"로 넘겼다.
   값 재현은 못 해도 **계약**은 볼 수 있다 — 외부 호출 한도·중복 탐지·`_sanitize_external_text`의
   경계, `_external_usage_ledger_path`의 예약 시점. 그쪽은 네트워크 없이 검증 가능하다.
3. **TR3-02**: `_recent_global_events`가 저장소를 전 기간 읽는다. 먼저 `events` 데이터셋에
   `as_of_at`이 있는지와 `available_at`과의 최대 격차를 **실측**하고, 그만큼 여유를 둔 창으로
   좁힌다. 격차를 모르면 좁히지 마라 — 늦게 공개된 사건을 조용히 놓친다.
4. **FD3-02**: SEC `sub.txt`의 `fy` 결측 빈도를 확인하고, 결측이면 `period_end.year`로 채우지
   않고 행을 버릴지 판단한다. FD3-01과 같은 클래스다.
5. **`research/rl/`과 `research/promotion/`**: RS-15의 반대쪽. 승격 게이트가 읽는 컬럼을
   어느 producer가 채울지 정해지면 그 배선을 만든다.

### 11.2 다시 하지 않아도 되는 것

4절(음성 결과)과 9절(가드로 쓸 수 없던 방법)에 근거와 함께 있다. 요약:
naive datetime · 고아 DB 컬럼 · 문서의 repo 경로 · 워크플로·scripts 경로 · 위험 한도 표의 값 —
전부 깨끗하다. dict 키 생산자 대조와 dataset 읽기/쓰기 대조는 오탐이 많아 가드로 쓸 수 없다.

### 11.3 이 세션이 만든 가드를 고칠 때

새 가드 5개는 모두 **위반 주입으로 검증**했다. 그 검증을 지우지 말고, 가드를 고치면 주입을
다시 해라. 두 개는 처음 판이 **공허하게 통과했고**(5절) 주입으로만 잡혔다.

| 가드 | 파일 |
|---|---|
| `NamedModulePathTest` · `NamedSourceFileTest` · `RiskLimitDocumentationTest` | `tests/test_docs_consistency.py` |
| `RankCorrelationTieTest` | `tests/investment_agent/research/models/test_baselines.py` |
| `CoverageHonestyTest` | `tests/investment_agent/research/system_validation/test_ablation.py` |
| `UnreadableQuarterCountTest` | `tests/investment_agent/data/fundamentals/test_segment_periods.py` |
| `StoreAvailabilityGateTest` | `tests/investment_agent/dashboard/test_news_social_page.py` |
| 공유 캐시 결과 동일성 | `tests/investment_agent/trading/portfolio/test_market_risk.py` |

### 11.4 이 세션이 하지 않은 것

commit · push · 운영 DB 쓰기/DDL/DML · Discord 발송 · 하네스 실행/재시작 · 알림 재발송 ·
재적재 · `LIVE_ENABLED`·킬스위치 변경. 정비 보류는 만들지도 풀지도 않았다.
