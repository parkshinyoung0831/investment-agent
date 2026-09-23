# System Upgrade Master Plan — 시스템 고도화 마스터 플랜 및 SSOT

> **문서 역할**: 전체 투자 시스템의 현재 상태, 불변 원칙, 확인된 문제, 목표 아키텍처, 구현 우선순위와 검증 절차를 정의하는 **고도화 계획의 단일 기준 문서(SSOT)**  
> **기준 브랜치**: `main`  
> **분석 기준 SHA**: `d9bb5a3` (main)  
> **기준일**: 2026-09-23  
> **중요**: 이 문서는 “현재 구현”과 “제안된 개선”을 명확히 구분한다. 제안된 알고리즘이 문서에 존재한다는 이유만으로 Production에 채택된 것으로 간주하지 않는다. 새 세션은 이 SHA 이후 `main`이 얼마나 이동했는지부터 다시 확인한다 — SHA는 출발점이지 현재 상태의 보증이 아니다.

---

## 1. 이 문서의 역할

이 문서는 다음 질문에 답한다.

1. 현재 시스템은 실제로 어떻게 동작하는가?
2. 절대로 깨뜨리면 안 되는 구조와 안전장치는 무엇인가?
3. 현재 코드에서 실제로 확인된 문제는 무엇인가?
4. 시스템을 어떤 방향으로 고도화할 것인가?
5. 어떤 순서로 구현·검증·승격할 것인가?
6. 다른 세션이나 Coding Agent가 무엇을 기준으로 작업해야 하는가?

Factor·ML·RL·Alpha·Optimizer의 구체적인 수식과 후보 알고리즘 비교, 그리고 AI Decision Layer(System-One/Deep LLM/Multi-Agent) 설계는 별도 문서인:

`docs/INVESTMENT_DECISION_ENGINE_DESIGN.md`

가 소유한다(Part I: Factor/ML/Alpha/Optimizer/Risk/RL/TCA, Part II: AI Decision Layer).

과거 특정 시점의 조사 기록·실패 로그·실험 결과는:

`docs/superpowers/audits/`

에 보존한다.

---

## 2. 문서 및 코드 Source of Truth

문서와 코드가 충돌할 경우 다음 순서로 판단한다.

```text
실제 실행 코드 / Tests / Trading Constitution
                ↓
현재 상태 문서
                ↓
Upgrade Master
                ↓
Investment Decision Engine Design
                ↓
과거 Audit
```

각 영역의 canonical owner는 다음과 같다.

| 영역 | Canonical implementation |
|---|---|
| Feature | `src/investment_agent/research/features/` |
| Factor | `src/investment_agent/research/factors/core.py` |
| Factor compatibility export | `src/investment_agent/research/features/factors.py` |
| ML baseline | `src/investment_agent/research/models/baselines.py` |
| ML training | `src/investment_agent/research/training/` |
| ML production serving | `src/investment_agent/research/ml_serving.py` |
| RL research | `src/investment_agent/research/rl/` |
| LLM orchestration | `src/investment_agent/trading/decision/agents/` |
| Alpha | `src/investment_agent/trading/decision/alpha.py` |
| Portfolio optimizer | `src/investment_agent/trading/portfolio/optimizer.py` |
| Portfolio market risk | `src/investment_agent/trading/portfolio/market_risk.py` |
| Target construction | `src/investment_agent/trading/system/target.py` |
| Market regime | `src/investment_agent/trading/decision/regime.py` |
| Risk budget | `src/investment_agent/trading/risk/regime_budget.py` |
| Hard risk gate | `src/investment_agent/trading/risk/gate.py` |
| System Portfolio | `src/investment_agent/trading/system/` |
| My Portfolio | `src/investment_agent/trading/my_portfolio.py` |
| Broker execution | `src/investment_agent/execution/` |
| Reconciliation | `src/investment_agent/execution/reconciliation/` |
| Performance attribution | 기존 `performance/attribution` 계층을 우선 재사용 |
| Runtime orchestration | `src/investment_agent/operations/harness/` |

---

## 3. 시스템 철학

이 시스템의 목표는 모델을 많이 붙이는 것이 아니다.

핵심 철학은 다음과 같다.

> **좋은 기업을 합리적인 가격에서 선별하고, 실적 기대·중장기 모멘텀·ML·이벤트·거시환경을 이용해 기대수익을 지속적으로 갱신한다. 포트폴리오에서는 상관관계·Factor·Tail Risk·거래비용을 고려해 비중을 최적화하고, 시장 위험이 커질 때는 개별 종목을 더 정확히 맞히려 하기보다 전체 Exposure를 줄인다.**

이를 시스템 관점에서는 다음과 같이 표현한다.

```text
Better Data Integrity
        +
Calibrated Signal Reliability
        +
Cost-aware Portfolio Construction
        +
Continuous Risk Adaptation
        +
Deterministic Safety
        +
Closed Evaluation Feedback
        +
Controlled Manual Promotion
```

---

## 4. 절대 유지할 불변 원칙

다음 항목은 고도화 과정에서도 변경하지 않는다.

### 4.1 System Portfolio와 My Portfolio 분리

```text
SYSTEM PORTFOLIO
프로그램이 판단한 이상적 포트폴리오
↓
Shadow / Evaluation은 인간 승인과 무관하게 계속 실행

MY PORTFOLIO
System Target과 실제 계좌 차이 계산
↓
Discord 승인
↓
Live Execution
```

사람이 Discord에서 승인·거절·무응답하더라도:

- System Portfolio
- Shadow
- Learning
- Evaluation

은 독립적으로 계속 진행한다.

---

### 4.2 LLM은 실행 권한을 갖지 않는다

LLM은 다음을 직접 결정할 수 없다.

- 최종 포트폴리오 비중
- 주문 수량
- Broker 주문
- Hard Risk Limit
- Kill Switch
- Live activation

LLM의 역할은 정성적 Thesis와 Evidence 해석이다.

---

### 4.3 Deterministic Hard RiskGate 유지

최종 포트폴리오는 반드시 결정론적 RiskGate를 통과한다.

Hard constraint는 ML·LLM·RL confidence와 관계없이 유지한다.

예:

- 종목 상한
- Sector 상한
- Cash floor
- Long-only
- Concentration
- Tail-risk limit
- Forced exit
- Crisis restrictions

---

### 4.4 Broker 결과 불명 주문 재전송 금지

POST 요청 후:

- Timeout
- 5xx
- malformed response
- ID mismatch

등이 발생했다고 해서 주문이 실패했다고 가정하지 않는다.

```text
UNKNOWN
↓
Reconciliation
↓
실제 Broker 상태 확인
```

동일 주문을 무조건 재전송하지 않는다.

---

### 4.5 ML / Factor / RL 자동 Production 승격 금지

학습과 연구는 자동화할 수 있다.

Production 승격은:

```text
Candidate
→ OOS Validation
→ Shadow
→ Comparison
→ Manual Promotion
```

을 거친다.

---

## 5. 현재 실제 시스템 구조

```text
External Data
    │
    ▼
Canonical Storage
Supabase + Local Mirror
    │
    ▼
PIT Research / Feature Store
    │
    ├───────────────┐
    ▼               ▼
Factor            ML
    │               │
    ├──────┐   ┌────┘
           ▼   ▼
       LLM / Event
           │
           ▼
   Signal Reliability
           │
           ▼
       Alpha Fusion
           │
           ▼
   Portfolio Optimizer
           │
           ▼
 Continuous Risk Overlay
           │
           ▼
 Deterministic RiskGate
           │
           ▼
    SYSTEM PORTFOLIO
           │
    ┌──────┴───────┐
    ▼              ▼
Shadow         My Portfolio
Evaluation         │
Learning           ▼
              Discord Approval
                   │
                   ▼
               Execution
                   │
                   ▼
             Reconciliation
                   │
                   ▼
              Performance
                   │
                   ▼
             Evaluation
```

---

## 6. 현재 확인된 P0 문제

이 절은 특정 SHA 기준 실제 코드 및 Actions에서 확인된 문제만 기록한다.

구현 이후에는 반드시 상태를 다시 확인하고:

`OPEN → FIXED → VERIFIED`

형태로 갱신한다.

### P0-1 Runtime SQLite schema cache

- **상태**: `FIXED`
- **대상 파일**: `src/investment_agent/platform/db/sqlite.py`
- **테스트**: `tests/investment_agent/platform/test_sqlite_schema_applied_once.py`

#### 현재 문제
`platform/db/sqlite.py`의 `_PREPARED` 캐시는 `(path, st_dev, st_ino, DDL fingerprint)`를 기반으로 한다.
삭제된 SQLite 파일이 동일한 `inode`를 재사용하면, 새로 생성된 비어있는 DB임에도 불구하고 이미 schema가 적용되었다고 잘못 판단하여 DDL 적용을 건너뛴다.

결함의 본질은 **schema 적용 여부의 진실을 DB가 아니라 파일시스템 신원이 소유한다**는 것이고, 그것은 현재 코드에서 그대로다.

다만 심각도는 실측으로 좁혀 둔다 — 근거 없이 "테스트가 실패 중"이라고 적어 두면 다음 세션이 잘못된 전제로 출발한다.

- 명명된 테스트 `test_a_recreated_file_gets_the_schema_again`은 **현재 통과한다**(3/3 OK).
- Windows/NTFS 실측(2026-09-22): 같은 이름 삭제→재생성 30회에서 inode 재사용 **0회**. 이 호스트에서는 기술된 경로가 재현되지 않는다.
- ext4(GitHub Actions ubuntu 러너·Mac mini)에서는 inode 재사용이 흔하므로 그쪽 실측 전에는 심각도를 확정하지 않는다.
- 즉 이 테스트는 **결함이 있어도 통과할 수 있다**(공허한 통과). 고칠 때 위반 주입으로 먼저 실패를 확인한다.

#### 목표 및 해결 방안
Schema correctness의 진실을 filesystem inode가 아니라 DB 자체가 소유하도록 전환한다.
- `PRAGMA user_version` 또는 schema version sentinel table을 확인하여 실제 DB 내부에 테이블이 생성되어 있는지 검증한다.
- `_PREPARED`는 connection 생성 후 in-process performance cache로만 사용하며, 파일 존재/재생성 시 DB metadata 검증을 거친다.

---

### P0-2 Research DuckDB artifact schema incompatibility

- **상태**: `FIXED`
- **대상 파일**: `src/investment_agent/research/storage/repository.py` 및 artifact 복원 스크립트
- **실제 에러 로그**:
  ```text
  duckdb.duckdb.BinderException: Binder Error: Table "feature_sets" does not have a column named "feature_set"
  ```

#### 현재 문제
GitHub Actions `tech_indicators` 워크플로에서 과거 빌드된 `research.duckdb` artifact를 캐시에서 복원했을 때, 코드베이스의 최신 DDL에 추가된 컬럼(`feature_set` 등)이 과거 DB 파일에 존재하지 않아 크래시가 발생했다.

#### 해결 (`FIXED`)
자동 이관도, 자동 삭제도 하지 않는다. **조용히 늦게 죽던 것을 일찍 크게 말하게** 바꿨다.

- 선언과 `after_ddl` 이관이 끝난 뒤, 이미 있는 표가 현재 선언의 컬럼을 모두 갖고 있는지 본다.
  없으면 어느 표의 어느 컬럼이 빠졌는지와 "재빌드하라"를 담아 `DuckDBStoreError`로 즉시 실패한다.
- 검사는 **이관 뒤**에 한다. 앞에서 하면 `after_ddl`이 옮길 옛 표를 드리프트로 오인한다
  (실제로 `strategy_allocations`의 JSON→관계형 이관이 걸렸다).
- 컬럼 파싱은 SQL 주석을 먼저 지운다. 이 저장소의 선언은 컬럼 사이에 한국어 주석을 두는데,
  지우지 않으면 주석의 낱말이 컬럼으로 잡혀 **멀쩡한 저장소를 옛 artifact로 신고한다**
  (실제로 테스트 42건이 그렇게 죽었다).
- 자동 `ALTER TABLE`이나 fail-safe rebuild는 하지 않는다 — 컬럼 추가는 기본값·제약을 알아야 하고,
  파일을 지우는 것은 데이터 손실이다. 무엇이 어긋났고 무엇을 하면 되는지만 정확히 알린다.

#### 함께 고친 것
잠금 재시도(`_open_with_retry`)가 **영구 오류까지 삼키고 있었다.** 유효한 DuckDB 파일이 아닌
artifact를 기본 180초 동안 다시 열다가 죽는다 — CI에서 잡마다 3분을 태운다. 잠금 메시지는 OS 언어로
번역되지만 "not a valid DuckDB database"는 DuckDB 자신이 만드는 영어 문구라 번역되지 않는다.
그것만 가려 즉시 올린다.

---

### P0-3 GitHub Workflow input contract mismatch

- **상태**: `FIXED`
- **대상 파일**: `.github/workflows/universe_membership_check.yml`, `.github/workflows/universe_monthly.yml`, `.github/workflows/market_backfill.yml`
- **실제 에러**: GitHub Actions API `HTTP 422: Unprocessable Entity` (Unexpected input 'dataset')

#### 현재 문제
`universe_membership_check.yml`에서 S&P 500 종목 변경이 감지되면 후속 단계로 `market_backfill.yml`을 트리거하면서 `-f dataset=both`를 전달한다. 하지만 피호출자인 `market_backfill.yml`의 `workflow_dispatch.inputs`에서 `dataset` 옵션이 이미 삭제되어 있어 GitHub API 422 에러로 실패하며 후속 SEC/재무제표 백필 전체가 중단된다.

**같은 호출이 `universe_monthly.yml`에도 있다**(매월 1일 정합성 경로). 한쪽만 고치면 월간 경로가 같은 이유로 계속 죽는다.

#### 목표 및 해결 방안
1. `universe_membership_check.yml`에서 obsolete input(`-f dataset=both`) 제거.
2. Caller-Callee workflow dispatch 계약을 검증하는 CI 테스트 추가하여 input drift를 사전 차단.

---

### P0-4 예산 소진 실패가 종목 순환을 억제한다

- **상태**: `FIXED`
- **대상 파일**: `src/investment_agent/trading/decision/candidates.py` (`_last_attempted`)
- **성격**: 에러 없이 조용히 틀린다. 로그도 정상으로 보인다.

#### 현재 문제
`_last_attempted()`는 판단 원장의 `status=='failed'` 행도 "마지막 분석 시각"으로 인정한다.
의도는 한 종목의 장애가 순환을 영원히 막지 않게 하는 것이다. 그런데 실패 사유를 구분하지 않으므로
**모델 예산 소진처럼 그 종목과 무관한 시스템 상태**까지 "최근에 분석했다"로 센다.

`select_factor_candidates()`는 `older_than(ticker, refresh_days=28)`로 거르므로, 예산이 떨어져
**시작조차 못 한 종목이 28일 동안 factor 순환에서 빠진다.**

실측(`runtime.sqlite3`, 2026-09-22 기준):

```text
security_decisions 291행 → completed 57 / failed 234
failed 사유 상위: 232건이 "ModelPoolError: no LLM model pool candidate has budget"

28일 내 시도 기록이 있는 종목        : 290
  ├ 마지막이 예산 소진 실패인 종목   : 232   ← 한 번도 판단받지 않았는데 억제 중
  └ 마지막이 성공인 종목             :  57
```

원인이 된 설정(`AI_INVESTOR_DAILY_LIMIT=250` vs 실제 예산 20)은 `analysis_limit()`과
`except ModelPoolError` 가드로 이미 막혔다(`b924290`). **그러나 원장에 남은 232행의 효과는 현재 진행 중이다.**

#### 목표 및 해결 방안
"판단했다"와 "시작조차 못 했다"를 코드가 구분한다.

- 재분석 억제는 **실제로 모델이 답한 시도**(`completed`/`abstained`, 그리고 모델이 답한 뒤 실패한 경우)에만 적용한다.
- 예산 소진·API 키 부재처럼 **종목과 무관한 시작 실패**는 억제에 넣지 않는다.
- 같은 종목이 계속 실패할 때의 무한 재시도는 별도의 짧은 backoff로 막는다 — 28일 순환 게이트를 그 용도로 쓰지 않는다.

---

### P0-5 평가 피드백 루프에 결과가 한 줄도 없다

- **상태**: `OPEN` (원인은 배선이 아니라 입력 부재 — 아래 구분)
- **대상 파일**: `src/investment_agent/trading/performance/attribution.py`(production 호출자 없음)

#### 현재 문제
원장 실측(2026-09-22):

```text
decision_evaluations     0행   ← 판단이 채점된 적이 없다
attribution_reports      0행   ← attribution이 계산된 적이 없다
intents / orders / fills 0행   ← 주문이 나간 적이 없다
performance_reports     64행   ← 전부 fill_count=0, positions=[]
```

**절반은 배선 문제가 아니다.** `evaluate_decisions`는 이미 하네스에 완전히 배선돼 있다 —
`feature_store_job`의 stage로 매일 돈다(`operations/harness/pipeline.py`,
`operations/adapters/research.py`). 표가 빈 것은 다음 둘 때문이다.

- 완료된 판단 57건의 판단 시각이 2026-09-09~15이고 20·60거래일 horizon은 아직 성숙하지 않았다.
- 원장의 마지막 활동이 2026-09-15다. 그 뒤로 하네스가 이 호스트에서 돌지 않았다.

**나머지 절반은 실재하는 구멍이다.** `build_attribution_report()`와
`record_attribution_report()`는 있지만 **production 호출자가 없다**(테스트에서만 부른다).
`update_performance`도 부르지 않는다.

#### 지금 구현하지 않는 이유
attribution은 체결 결과를 분해한다. 그런데 `fills`가 0행이고 `performance_reports`의
positions도 비어 있다 — **분해할 손익이 존재하지 않는다.** 이 상태에서 분해식을 짜 넣으면
검증할 수 없는 계산을 Production에 넣는 것이고, §16.10·§14의 검증 절차를 건너뛰는 것이다.

`INVESTMENT_DECISION_ENGINE_DESIGN.md` §16이 요구하는 Factor/ML/LLM 기여 분해도 마찬가지다
(단, **재현 수익**의 출처별 귀속은 `system_ablation` 사다리 차분으로 지금도 가능하다 — 설계 §16.2).
현재 `AttributionReport`의 성분은 market/selection/allocation/timing/risk_overlay/slippage/fees이고
신호 출처별 분해가 없다. 둘 다 **실제 체결이 쌓인 뒤에** 설계한다.

#### 목표 및 해결 방안
- 이 절의 값은 "고칠 것"이 아니라 **"기다릴 것"** 이다. 다음 세션이 이것을 배선 누락으로
  오해하고 빈 attribution을 만들지 않게 여기 적어 둔다.
- 선행 조건: 실제 체결(`fills` > 0)과 성숙한 판단(`decision_evaluations` > 0).
- 그 뒤에 `update_performance` 경로에서 attribution을 부르고, 성분에 신호 출처별 기여를
  더할지 결정한다.
- **주의**: `SYSTEM_UPGRADE_MASTER.md` §2의 canonical owner 표는 performance attribution을
  "기존 계층 재사용"으로 적는다. 그 계층은 **만들어져 있지만 한 번도 먹인 적이 없다** —
  재사용하라는 말이 이미 동작 중이라는 뜻이 아니다.

---

### P0-6 LLM 비용·지연이 계측되지 않는다

- **상태**: `FIXED` (durable 저장은 남음 — 아래)
- **대상 파일**: `src/investment_agent/trading/decision/llm/client.py`

#### 현재 문제
`complete_json()`은 provider 응답에서 `choices[0].message.content`만 꺼내고 `body["usage"]`를 버린다.
호출 소요 시간도 기록하지 않는다. 따라서 다음이 **전부 측정 불가**다:

```text
input_tokens/ticker, output_tokens/ticker, cost/ticker, latency p50/p95/p99
```

구조적으로 셀 수 있는 것은 종목당 LLM 호출 수(실측 14건, 계약 위반 시 15건)와 하루 상한(20종목)뿐이다.

`INVESTMENT_DECISION_ENGINE_DESIGN.md` §50은 이 값들이 "먼저 계측 가능해야 한다"고 적지만,
**현재는 계측 코드 자체가 없다.** 비용 근거 없이 provider를 비교하면 §16.12가 금지한 수치가 문서에 들어온다.

#### 목표 및 해결 방안
- `complete_json()`의 **반환 타입은 바꾸지 않는다.** 호출부 8곳과 테스트 fake 전부가 깨진다.
  대신 client 인스턴스가 자기가 쓴 자원을 누적한다 — client는 종목 하나의 분석 동안만
  살아 있어 누적값이 곧 종목당 합계다.
- provider가 `usage`를 주지 않으면 토큰을 0이 아니라 **미상(None)** 으로 둔다.
  0으로 적으면 "안 썼다"와 "모르겠다"가 같은 값이 되어 비용을 조용히 과소 추정한다.
- 계측이 30일 이상 쌓인 뒤에만 provider 비교의 비용 항목을 채운다.

#### 진행 상태
- `trading/decision/llm/usage.py`의 `UsageLedger`가 호출당 토큰·지연을 누적한다. **완료**
- `AgentEngineResult.usage`로 종목당 합계가 나오고, `analysis.py`가 종목마다와 회차 끝에
  구조화 JSON 로그로 남긴다. **완료**
- **남은 것 (2026-09-23 재검토로 확대)**: 계측이 비용의 내역을 버린다 — P0-10 참고.
  로그는 회전하고, reasoning 토큰·cached 토큰·역할별 토큰·분석가 입력 원문이 기록되지 않는다.
  **하네스를 다시 띄우기 전에** 닫는다.

---

### P0-7 feature store가 40일 낡아 factor 경로가 통째로 fallback 중이었다

- **상태**: `FIXED` (적재 완료. 재발 감지는 기존 하네스 health·dead-man이 소유)
- **대상**: research feature store 적재(`feature_store` job), `research/features/layer.py`
- **성격**: 에러 없이 조용히 다른 경로로 돈다.

#### 이 절의 앞선 판정은 틀렸다
처음에는 "Revision factor가 한 번도 값을 가진 적이 없다 — 6-factor가 5-factor로 돈다"고 적었다.
증상(259일 전체에서 revision 0건)은 맞지만 **원인이 틀렸다.** 추적 결과:

```text
captured_live 컨센서스 최초 수집 : 2026-09-13   (collected_at 최솟값)
feature store 최신 스냅샷        : 2026-08-14
```

revision feature의 입력인 관측 컨센서스가 **마지막 feature 빌드보다 한 달 뒤에 들어오기
시작했다.** 그래서 모든 과거 스냅샷에서 revision이 비어 있는 것은 정상이다 — 그때는 입력이
없었다. `observed_consensus_as_of`가 `snapshot_kind='captured_live'`만 읽는 것도 설계대로다
(reconstructed 행은 PIT가 아니다).

**오늘 기준으로는 계산된다.** 실측(2026-09-23, 10종목 표본):

```text
AAPL MSFT NVDA JPM XOM WMT PG KO CAT GM  →  10/10에서 revision feature 산출
예: NVDA revision_breadth_30d=0.95, GM revision_eps_change=0.0108
```

즉 `FactorModel`을 5-category로 다시 선언할 이유가 없고, 코드를 고칠 것도 없다.
**feature store를 다시 빌드하면 revision이 채워진다.**

#### 진짜 문제
feature store가 **40일 낡았다**(2026-08-14 → 2026-09-23). 그 결과가 조용하다:

```text
FACTOR_SNAPSHOT_MAX_AGE_DAYS = 4
최근 4일 창의 feature snapshot 행 = 0
→ factor_cross_section()이 None을 돌려준다
   · 후보 선정이 legacy_rotation 경로로 떨어진다 (경고 로그는 남는다)
   · System 목표는 factor 횡단면이 없어 갱신되지 않는다
```

`candidates.py`의 fallback은 의도된 것이다("분석 대상 선정은 주문이 아니므로 fail-open").
문제는 **그 fallback이 40일째 상시 경로가 돼 있다는 것**이다. 설계 문서가 기술하는
factor 기반 후보 선정·System 목표는 지금 돌고 있지 않다.

#### 조치 결과 (2026-09-22, `FIXED`)
선언된 순서대로 적재했다. 과거 백필은 하지 않았다 — 그때는 입력이 없었으므로 backfill해도
revision은 여전히 빈다.

```text
build_valuations : 503종목 upsert (with_market_cap 497, meaningful_pe 463)
build_features   : 503종목 upsert (with_valuation 503, failed 0)
```

적재 전후 category 결측률:

```text                        전      후
  revision            100.0%  →   2.0%
  balance_sheet         5.8%  →   5.8%
  value                 4.0%  →   4.4%
  growth                2.6%  →   3.0%
  quality               2.4%  →   2.2%
  momentum              0.4%  →   1.0%
```

6개 category를 모두 가진 종목 446/503. 품질 게이트 통과 347/503.
`factor_cross_section()`이 다시 값을 돌려주므로 후보 선정이 legacy_rotation fallback에서
정상 경로로 돌아왔다.

#### 재발 감지 — 새 가드를 만들지 않았다
처음에는 일일 ops 카드에 feature store 신선도 카운터를 넣으려 했다. **잘못된 자리였다.**
기존 가드 둘이 그것을 바로 잡았다:

- `ops_heartbeat`는 GitHub Actions에서 돈다. research DuckDB는 **로컬 전용 저장소**라 그 러너에
  파일 자체가 없다. 읽으려 하면 항상 "비어 있음"이 되어 거짓 경보가 된다.
- 그 진입점의 dependency group에 `duckdb`가 없어 import부터 죽는다.

원인을 다시 보면 feature store 신선도는 **증상이지 원인이 아니다.** 실제 상태:

```text
하네스 실행 상태 : 정지됨 (STOPPED)
feature_store job : succeeded (= 마지막으로 돌았을 때의 결과)
```

하네스가 멈춰 있어서 daily job이 돌지 않았을 뿐이다. `feature_store: succeeded`는 현재
신선도가 아니라 **마지막 실행 결과**다 — 상태 단어를 신선도로 읽으면 안 된다.

이 경우를 잡는 장치는 이미 있다:

- `operations/harness/health.py:inspect_health`가 `process_status`를 `running/stale/stopped/
  never_started`로 판정하고 `healthy`는 `running`일 때만 참이다.
- `operations/monitoring/counters.py:ping()`이 외부 dead-man switch에 생존을 알린다.

따라서 새 카운터를 만들지 않는다. **필요한 것은 코드가 아니라 하네스를 다시 띄우는 것**이고,
그것이 멈췄을 때 알리는 경로는 이미 선언돼 있다.

남는 것은 운영 질문 하나다 — 로컬 하네스가 멈췄을 때 그 dead-man ping이 실제로 사람에게
닿는지는 이 세션에서 확인하지 않았다.

#### 남는 질문 (결정 필요 없음, 관찰만)
revision이 채워지기 시작하면 factor composite의 분모가 5에서 6으로 바뀌어
**모든 종목의 종합 점수가 재정규화된다.** 순위가 얼마나 흔들리는지는 적재 직후
과거 재현으로 한 번 보는 것이 좋다 — 판단이 아니라 관찰이다.

---

### P0-8 System Portfolio가 구조적으로 현금에 치우친다

- **상태**: `FIXED` (`system-target-v4`, SPY 대비 위험이 기본값 — 설계 §9.2)
- **대상**: `trading/portfolio/optimizer.py`, `trading/system/target.py`
- **성격**: 에러 없이 조용히 틀린다. 모든 한도를 지키면서 벤치마크에 크게 뒤진다.

#### 현재 문제
optimizer의 기대수익 μ는 **SPY 대비 초과수익**인데, 주식의 대안은 **현금**이다. 주식 위험
프리미엄이 목적함수 어디에도 없으므로 시장 위험이 "보상받지 못한 위험"으로 보이고, λ=5와
confidence 곱이 겹쳐 현금이 합리적 해가 된다.

2025년 재현 실측(`artifacts/research/ablation/latest.json`, factor 스냅샷이 있는 51개 재조정):

```text
factor_only       평균 현금 59.4%   수익 +9.44%   SPY +17.21%   초과 −7.77%p   연변동성 4.9%
                  market_risk 조임 29/51회   tail 한도 발동 0/51회
factor_ml_thesis  현금 100% (그 기간에 논지 0건 → 전 종목 UNVERIFIED_ENTRY_BLOCKED)
```

평균 약 40% 투자로 SPY의 약 0.4배 노출이면 시장 몫이 약 +7%이고 선택 몫은 약 +2.4%p다(베타≈1
가정의 추정). **초과수익 부족의 대부분은 종목 선택이 아니라 이 결함이다.**

#### 목표 및 해결 방안
노출(얼마나 주식을 들 것인가)과 선택(어떤 주식을)을 분리한다. 노출 E_t는 regime/overlay가
결정론으로 정하고, optimizer는 `Σw = E_t` 안에서 SPY 대비 active 위험으로 종목을 고른다.
hard limit은 하나도 완화하지 않는다. 투자 가능 종목이 부족한 날의 fallback(현금 vs SPY)은
사람의 결정이다. 식과 검증 표는 설계 §9.2.

---

#### 원인은 셋이었다 (2026-09-23 재현 추적)

1. **목적함수**: 위 설명 그대로 — μ는 SPY 대비인데 위험은 절대 분산이다. `benchmark_relative_risk`
   스위치로 SPY 대비 위험을 쓸 수 있게 했다(기본 꺼짐, `05a653d`).
2. **주식 클래스 중복 거절 (`FIXED`, `05a653d`)**: GOOG·GOOGL(상관 0.998)·FOX·FOXA(0.986)가 둘 다 상위에
   들어 optimizer가 둘 다 사면 RiskGate의 쌍 상관 한도(0.95)가 목표 **전체**를 거절했다. 2025 재현에서
   목표의 약 40%가 이렇게 버려졌고 그 주는 현금이 그대로 남았다. optimizer가 게이트와 같은 표본 상관으로
   점수 낮은 쪽의 신규 편입을 막는다. 게이트는 그대로다.
3. **현금에서 출발한 증가 속도**: turnover 한도 0.25 때문에 전액 현금에서 투자 비중을 채우는 데 최소 4번의
   재조정(주간이면 4주)이 걸린다. 결함이 아니라 설계다 — 다만 2가 매주 목표를 버리면 이 사다리를 영원히
   못 오른다.

"평균 현금 59%"는 표현이 틀렸다 — 그 값은 마지막 날 현금이다. 재현에 기간 평균을 추가했다.
**재현 도중 회계 결함(P0-12)이 발견돼 그 전의 benchmark_relative 수치는 모두 무효다.**

#### 고친 회계로 다시 잰 5년 (설계 §9.2 표)

```text
2021-09~2026-08, NAV 가격 대사 불일치 0일
factor_only (현행)    초과 −45.8%p  IR −0.52  평균 현금 59.6%  2022 MDD 6.4% (SPY 24.5%)
benchmark_relative    초과 +12.4%p  IR  0.14  평균 현금 14.7%  2022 MDD 19.7%
```

- 현금 편향 교정은 효과가 있다. 다만 초과수익은 거의 전부 2022년(+4.5%p)에서 나오고 2023~2026은 연 ±1%p
  안이다. IR 0.14(5년 t≈0.3)는 "SPY와 비슷하게 가며 약세장 낙폭이 조금 작다"는 뜻이다. 종목 선택 몫이라
  부를 것은 아직 없다.
- 단계 진단(`stage_diagnosis`)이 유의하게 손해로 판정한 단계는 노출(현금) 하나다. factor_only에서는
  optimizer가 남긴 현금(120일 t=−2.9)과 계단식 현금 하한(60일 t=−2.6) 둘 다, benchmark_relative에서는 하한만
  남는다. 연속 노출 변형은 둘 다 판정 불가 수준이다.
- 채택 기준표를 benchmark_relative와 연속 노출 변형이 **모두 통과한다**. turnover 한도 초과 4일은 전부 위험
  축소 재조정이었다.
- **채택 (2026-09-23, 사람 결정)**: benchmark_relative를 System 기본값으로 올렸다(`system-target-v4`). 연속
  노출은 켜지 않았다 — 차이가 판정 불가다. 정책 버전이 바뀌어 System 모델 artifact가 새로 생기므로 실계좌
  추종은 승격 절차를 다시 거친다(자동 승격 없음). 이전 구성은 재현 변형 `absolute_risk`로 비교한다.

---

### P0-12 System 회계가 분할을 두 번 반영했다

- **상태**: `FIXED` (`c17cf23`)
- **대상**: `trading/system/accounting.py` (`_gross`, `session_price`)
- **성격**: 에러 없이 조용히 틀린다. 운영 System NAV·성과 카드에 영향.

`market.prices_daily.close`는 **분할 조정·배당 미조정** 가격이다(DDL 주석). 그런데 회계가 분할일에
`split_ratio`를 한 번 더 곱해, 5년 재현에서 GOOGL 20:1 분할일 하루 +92%, NVDA 10:1 분할일 +25%가 나왔다
(benchmark_relative 5년 +553%, 연변동성 46%, 최대낙폭 19% — 불가능한 조합이 단서였다).

직전 종가를 저장된 mark가 아니라 **같은 조회의 가격표 직전 거래일 종가**로 잰다. market 파이프라인은 새
분할이 생기면 그 종목 이력 전체를 새 기준으로 다시 받고 불연속을 검증하므로 가격표는 늘 한 기준이다.
재현에는 NAV를 가격 변화로 독립 계산해 1%p 넘게 어긋나는 날을 잡는 대사 검사를 붙였다(`91372b8`).

**운영 영향 확인 (2026-09-23)**: 운영 System 원장(`SystemPortfolioStore`)은 target 0건·mark 0건으로 **비어 있다**.
오염된 NAV는 없다. 동시에 System Portfolio가 운영에서 한 번도 목표를 만든 적이 없다는 뜻이다 — feature
store 정체(P0-7)와 하네스 정지 때문이다. 재기동하면 이 수정이 들어간 회계로 처음부터 쌓인다.

---

### P0-13 factor 신호의 20일 IC가 0과 구별되지 않는다

- **상태**: `OPEN` (고칠 결함이 아니라 알아야 할 사실 — 설계 §7.2)
- 2021-09~2026-08 주간 259시점: composite 20일 IC **0.014 (t_adj 0.76)**, 품질 게이트 통과분 0.027 (1.49).
  value만 일관되게 양(+), **quality는 음(-)**. 코드의 가정 IC 0.04는 실측의 약 1.5~3배다.
- 뜻: 약한 신호로 큰 α를 주장하고 있었다. 기관 수준으로 가는 첫 걸음은 모형을 더 붙이는 것이 아니라
  약한 신호를 약한 만큼만 쓰는 포트폴리오(SPY 대비 위험 + 작은 tilt)다(설계 §60).

---

### P0-9 채택된 ML 모델이 없다 — 운영 alpha에서 ML 몫은 0이다

- **상태**: `OPEN` (고칠 결함이 아니라 알아야 할 사실. 채택은 사람의 행위)
- `artifacts/trading/ml_models/active_ml_model.json`이 존재하지 않는다. `champion_forecast`는
  "no adopted ML model artifact"를 돌려주고 ML 몫 c = 0이다. 2025 재현도 `ml_forecasts_applied=0`.
- 따라서 문서가 기술하는 "factor + ML 결합"은 **현재 운영에서 factor 사전값 + LLM 논지**다.
  ML 신뢰도식(`min(0.8, 10·IC)`) 개선은 운영에 영향이 없고, 채택 결정의 근거를 만드는 작업이다
  (설계 §6, §7.4).

---

### P0-10 현재 LLM 엔진은 한 번도 완료되지 않았고, 계측이 비용의 내역을 버린다

- **상태**: `FIXED` (계측 `e3aedd4`. 현재 엔진 판단은 재기동 뒤에 쌓인다 — 설계 §57)
- 완료된 판단 57건은 전부 옛 엔진(`0.5.0` 20건, `0.6.0` 37건)이다. 현재 엔진
  `0.7.1-local-graph-macro-h20-news7d`(macro 분석가, `thesis`·`hard_constraint` 계약)의 완료 판단은
  **0건**이다. 모든 토큰·payload 수치는 옛 엔진으로 재구성한 근사치다.
- `UsageLedger`는 `prompt_tokens`·`completion_tokens`만 읽는다. 다음을 **버린다**:
  - `completion_tokens_details.reasoning_tokens` — gpt-5-mini는 reasoning 토큰을 output으로
    과금한다. output이 단가 8배인데 그 내역을 모른다.
  - `prompt_tokens_details.cached_tokens` — 캐시 최적화의 효과를 확인할 수 없다.
  - 역할별 토큰 — 역할별로는 호출 **수**만 센다.
- 분석가 5명의 입력 원문이 저장되지 않아 분석가 단계를 재현·벤치마크할 수 없다.
- **재기동 뒤 첫 1~2주가 공짜 계측 기간이다.** 계측이 불완전한 채 재기동하면 그 기간을 잃는다.

---

### P0-11 balance_sheet 결측은 게이트 비대칭이 아니라 feature 정의 문제다

- **상태**: `OPEN` (아래 "보류" 항목의 원인 정정 — 설계 §5.4)
- 2026-09-22 횡단면에서 balance_sheet 결측이면서 게이트를 통과한 18종목은 은행이 아니다:

  ```text
  AES AMP ANET AZO CAT CPRT ERIE GM HCA ISRG MNST MO NVR PCAR PM SBAC TDG YUM
  ```

  무차입(이자보상배율 정의 불가 — 건전성 최상위)과 음(-)의 자기자본(D/E 정의 불가 — 건전성
  불확실)이 섞여 있다. 게이트를 어떻게 바꿔도 두 부류를 같은 값으로 다룬다.
- 해결은 feature owner에서: 이자비용 0 → 상위 cap, 자기자본 ≤ 0 → net debt/EBITDA로 대체.
  순위를 바꾸므로 재현과 사람의 결정을 거친다.

---

### 실측으로 보류한 것 (제안했다가 근거가 무너진 것)

제안이 문서에 남아 있으면 다음 세션이 그것을 근거로 삼는다. **왜 안 했는지**를 함께 남긴다.

#### 구조화 출력 strict 전환 — `보류`
`json_object`(구식) 대신 `json_schema` + `strict:true`를 쓰면 계약 위반 재요청(LLM 호출 1건)을
없앨 수 있다고 봤다. Azure `gpt-5-mini(2025-08-07)`이 v1 엔드포인트에서 지원하는 것도 확인했다.

**그런데 그 비용이 실재하지 않는다.** 원장 실측(291건):

```text
모델에 닿은 시도 59건
  성공                         57
  ContractError (근거 ID 인용) 1   ← 스키마 모양이 아니라 의미 위반
  연결 오류                    1
```

관측된 유일한 계약 위반은 **허용되지 않은 evidence ID 인용**이고, strict 스키마는 그것을 막지
못한다(막으려면 허용 ID를 enum으로 넣어야 하는데 evidence bundle은 중앙값 58KB다).
즉 "재요청 1건을 아낀다"는 근거가 데이터로 뒷받침되지 않는다.

여섯 파일의 스키마 리터럴을 전부 바꾸는 변경 폭에 비해 측정된 이득이 없으므로 하지 않는다.
재검토 조건: **현재 엔진에서** 계약 위반율이 측정 가능한 수준(예: 시도의 5% 이상)으로 오르면.
(정정: 허용 ID enum의 크기는 bundle 문자 수가 아니라 evidence ID 개수에 비례한다 — 불가능하지는
않다. 보류 이유는 이득 부족이다. 설계 §55.3)

#### 분석가 5명 병렬화 — `보류`
5명은 서로의 출력을 읽지 않으므로 병렬화할 수 있고 종목당 지연이 줄어든다.

**그러나 지금 지연을 모른다.** 계측(P0-6)을 방금 붙였고 데이터가 0건이다. 측정 전에
최적화하는 것은 이 문서가 다른 곳에서 금지하는 바로 그 행동이다.

부작용도 있다 — 같은 모델에 동시 5요청은 TPM 한도를 건드릴 수 있고, 현재 client는 429를
백오프로 재시도한다. 이득의 크기를 모른 채 그 위험을 들일 이유가 없다.

재검토 조건: `latency_ms_p95`가 30일 이상 쌓인 뒤, 분석가 구간이 실제 병목으로 확인되면.

#### Factor 품질 게이트의 balance_sheet 비대칭 — `원인 정정됨 → P0-11`

아래는 처음 판단이다. 18종목의 정체를 확인한 결과 고칠 곳은 게이트가 아니라 feature 정의였다(P0-11).

`quality` 결측은 게이트에서 탈락시키면서 `balance_sheet` 결측은 검사를 건너뛴다
(`score_cross_section`). `FactorModel` 주석은 "품질·재무건전성이 모두" 기준을 넘어야 한다고
적어 선언과 코드가 어긋난다.

실측(2026-08-14 횡단면 502종목): `balance_sheet`가 결측인데 게이트를 통과하는 종목은
18개(3.6%)다. 고치면 후보 풀이 그만큼 줄고 **포트폴리오가 바뀐다.**

`_MIN_CATEGORY_COVERAGE` 주변은 이미 "감사 RR2-02, 결정 대기"로 표시돼 있다. 순위에 영향을
주는 변경은 과거 재현 비교와 사람의 결정을 거친다 — 여기서 단독으로 바꾸지 않는다.

---

## 7. 단계별 재설계 요약

13단계 각각의 현재 수식(코드 대조)·비평·대체 수식·검증 설계는
[INVESTMENT_DECISION_ENGINE_DESIGN.md](INVESTMENT_DECISION_ENGINE_DESIGN.md)가 소유한다. 여기는 판정만 둔다.

| 단계 | 판정 | 설계 절 | 검증 가능 시점 |
|---|---|---|---|
| 1 Factor 결측·가중 | REFINE(신뢰도 가중 중립 수축) / CHALLENGER(수축 IC 가중) | §5 | 지금 (가격 7년 + 주간 스냅샷 260개) |
| 2 ML | 운영 비활성(P0-9). 스태킹·전 창 walk-forward | §6 | 지금 |
| 2.5 AI 판단 계층 | 구조 KEEP, payload REFINE, escalation은 shadow부터 | §41~§58 | 일부 지금, 품질은 WAIT |
| 3 Alpha | 측정 IC·Blom z·스태킹. LLM 비대칭 유지, 자칭 confidence 제거 | §7 | factor·ML 지금, LLM WAIT(채점 200) |
| 4 공분산 | KEEP, EWMA 수축 challenger | §8 | 지금 |
| 5 Optimizer | **현금 편향 PARTIAL REPLACE(P0-8)**, 노출 제약 slack | §9 | 지금 |
| 6 Regime | 연속 노출 + 느린 복구 CHALLENGER | §10 | 지금 |
| 7 No-trade band | KEEP | §11 | 비용 실측 뒤 |
| 8 Tail | KEEP (2025 재현 발동 0회) | §12 | — |
| 9 RiskGate | KEEP, 완화 금지. HHI 장식은 사람 결정 | §13 | 재현 집계 |
| 10 TCA | KEEP, IS 정의 고정 | §14 | 체결 ≈ 400건 |
| 11 RL | overlay는 RL이 아니라 규칙으로. Offline RL 불가 | §15 | — |
| 12 평가·귀속 | 재현 사다리 차분으로 출처 귀속 | §16 | 재현은 지금, 체결 귀속은 WAIT |

**표본 없이 지금 할 수 있는 것이 Part I에 몰려 있다.** 가장 큰 것은 P0-8이다.

---

## 8. Adaptive Risk 구조

Risk는 2단계로 유지한다.

### Layer 1 — Hard Safety
`DeterministicRiskGate`: 절대 완화하지 않는다.

### Layer 2 — Continuous Risk Overlay
개념적 구조:
\[
Exposure_t = Base \times VolScale \times DrawdownScale \times MacroScale \times ReliabilityScale
\]
후보 기법:
- Volatility targeting
- Drawdown scaling
- Macro stress scaling
- Reliability scaling
- Hysteresis
- Slow recovery

위험 증가 시에는 **Fast Down**, 위험 감소 시에는 **Slow Up**을 기본 연구 방향으로 둔다.

실측(2025 재현): regime 계단이 51회 중 29회 한도를 조였고, tail(변동성·CVaR) 축소는 한 번도
발동하지 않았다. 두 층은 이중으로 겹치지 않는다 — regime은 시장 상태로 노출을, tail은 이
포트폴리오 고유 꼬리의 backstop을 맡는다. P0-8을 풀면 노출 E_t의 owner가 Layer 2가 된다(설계 §10.2).

---

## 9. AI / Multi-Agent 고도화 원칙

현재 저장소 소유 그래프:
```text
Market → Fundamental → News → Sentiment → Macro → Bull/Bear → Research Manager → Trader → Risk Debate → Portfolio Manager
```
를 기본 구조로 유지한다. 외부 TradingAgents runtime이나 monkey patch 구조로 되돌리지 않는다.

개선 후보:
- 역할별 모델 benchmark
- parallelizable analyst extraction
- structured Falsification Conditions
- contradiction map
- citation verification
- objective confidence calibration

모델 선택은 “최신 모델”이 아니라 실제 evidence bundle benchmark로 결정한다.

평가 항목:
- Schema validity, Citation correctness, Hallucination, Contradiction detection, Direction accuracy, Brier score, Stability, Latency, Token usage, Cost, Retry rate.

모델 가격과 이름은 시간에 민감하므로 이 Master 문서에 고정 가격표를 유지하지 않는다.

### 9.1 System-One / 저비용 구조화 판단 — 연구 방향 (RESEARCH)

현재 AI 판단은 Deep LLM Multi-Agent(Level 3) 경로 하나로 이뤄진다. 더 저렴한 구조화 판단 단계
(예: Jev류 System-One 모델)를 앞에 두는 것이 실제로 비용·지연을 줄이면서 품질을 유지하는지는 **검증되지 않았다.**

다만 이 절의 출발 전제 하나는 실측으로 정정한다 — **"변화가 없는 날도 전량 재판단한다"는 것은 사실이 아니다.**
결정론적 깔때기가 이미 앞단에 있다(`trading/decision/candidates.py`·`candidate_ranker.py`):

```text
tracked universe (수백)
  → priority lane (보유 + 신규 공시/고영향 사건이 있는 종목만)
  → factor shortlist 60 + 재분석 주기 28일 게이트
  → 모델 예산 상한 (실측 20종목/일)
  → 아무것도 due가 아니면 NoCandidatesDue로 회차 전체를 건너뛴다
```

2026-09-23 재검토의 결론(설계 §42~§58):

- **정상 상태 수요는 하루 20종목이 아니라 약 4~6종목이다.** 상위 60 신규 진입 주당 5.3 +
  28일 주기 재분석 주당 15(실측·추정). 20종목 상한은 백로그 기간의 처리 속도다.
- **종목당 비용 하한은 약 $0.10**(옛 엔진 57건 재구성, reasoning·분석가 입력 제외). 월 하한은
  정상 상태 약 $12~18, 상한 가동 시 약 $59. 보이는 것만으로도 output이 input보다 비싸다.
- **LLM 판단은 편입 게이트다.** 논지 없는 미보유 종목은 편입이 막히므로 Deep LLM을 건너뛰면
  포트폴리오가 바뀐다. escalation은 "건너뛰기"가 아니라 "변화 없는 재분석의 유효기간 연장"으로
  정의하고, 결정론 router를 shadow로 먼저 돌린다.
- **측정 없이 지금 해도 되는 것**: structuring state의 무손실 중복 제거, 캐시 적중을 위한 메시지
  재배치. **측정이 필요한 것**: reasoning_effort·verbosity, 요약본, 모델 등급.
- §45의 "SystemOneDecisionProvider를 만들지 않는다"는 **틀렸다** — Jev는 `LLMClient`의 어떤
  호출자에도 끼울 수 없다. 별도 계약을 두되, 지금은 비용 0인 결정론 부분만 복원한다.
- Jev는 `RESEARCH`. 질문 집합은 영어로 쓰고 언어를 artifact에 남긴다(evidence 자체가 대부분
  영어·숫자다).

- 구체 설계(Intelligence Hierarchy, Capability Router, Change Detection, Question Registry, Escalation, Verification, Champion vs Challenger 벤치마크, Provider Registry, 토큰 비용 구조와 레버 순위)는 `docs/INVESTMENT_DECISION_ENGINE_DESIGN.md` Part II(§41~§58)가 소유한다.
- 이 절은 원칙만 못 박는다: **어떤 provider도 이름만으로 채택하지 않는다.** Jev를 포함한 모든 System-One 후보는 현재 Multi-Agent Champion과 동일 evidence·동일 종목·동일 기간에서 Shadow 비교를 통과해야 하며, `AI가 없는 baseline`(Factor+ML only)도 반드시 비교군에 포함한다 — AI 계층 자체가 가치를 더하는지 먼저 확인한다.
- 자동 Production 승격 금지(§4.5)와 LLM 실행 권한 없음(§4.2)은 System-One에도 동일하게 적용된다.

---

## 10. ML / RL 전략

상세 수식은 `INVESTMENT_DECISION_ENGINE_DESIGN.md`가 소유한다. Master 수준 원칙은 다음과 같다:

### ML
현재 Regression Champion을 삭제하지 않는다.
```text
Current Regression vs Learning-to-Rank vs Probabilistic / Quantile vs Other challenger
```
를 동일 OOS에서 비교한다.

### RL
RL은 Production weight controller가 아니다.
연구 우선순위:
1. Current research baseline 유지
2. State/Reward 개선
3. Risk Overlay challenger
4. Residual optimizer challenger
5. Algorithm comparison
6. Offline RL
7. Distributional / CVaR RL

Production 직결은 장기 검증 전 금지한다.

---

## 11. Evaluation & Feedback

목표는 무제한 자동 재학습이 아니다. 다음 피드백 루프를 목표로 한다:
```text
Decision → Outcome → Attribution → Evaluation → Candidate Reliability → Shadow Validation → Manual Promotion → Production Policy
```
기존 performance attribution 구현을 우선 확장하며 중복 attribution engine을 새로 만들지 않는다.

평가 가능한 attribution 후보:
- Factor contribution, ML contribution, LLM tilt contribution, Allocation effect, Risk overlay effect, Execution slippage, Fees, Residual.

---

## 12. Execution / TCA

현재 추정 transaction cost model과 실제 체결 결과를 연결한다.
충분한 표본이 쌓인 이후:
```text
Decision Price, Arrival Price, Submitted Limit, Fill Price, Fees, Spread, ADV, Order Size, Implementation Shortfall
```
을 연결해 cost model challenger를 만든다. 현재 비용 모델을 실측 없이 즉시 교체하지 않는다.

---

## 13. 구현 Phase

날짜와 `done` 표시는 사용하지 않는다. 실제 코드 상태가 검증된 경우에만 `OPEN`, `IN_PROGRESS`, `FIXED`, `VERIFIED` 상태를 부여한다.

### Phase 0 — Operational Correctness
순서는 "지금 조용히 틀리고 있는 것" → "앞으로의 판단 근거를 만드는 것" → "복원·재생성 계약"이다.

- Workflow dispatch contract (`P0-3`)
- 예산 소진 실패가 순환을 억제하는 문제 (`P0-4`)
- LLM 비용·지연 계측 (`P0-6`)
- SQLite schema generation (`P0-1`)
- DuckDB artifact compatibility (`P0-2`)
- (`P0-5`는 여기 없다 — 고칠 배선이 아니라 기다릴 입력이다. 해당 절 참고)
- **완료 조건**: 관련 CI green, recreate / restore / dispatch failure injection 통과,
  그리고 각 가드는 **위반을 주입해 실패를 먼저 확인**한 것만 인정한다(§14).

### Phase 0.5 — 재기동 전 계측 (P0-10)
- reasoning·cached·역할별 토큰, 분석가 입력 원문, durable 저장
- 무손실 payload 축소(structuring 중복 제거), 캐시용 메시지 재배치
- 그 뒤 하네스 재기동 — 판단·채점·계측이 이것 없이는 쌓이지 않는다

### Phase 1 — Data / Factor / Portfolio Correctness (지금 검증 가능)
- **P0-8 노출 분리(현금 편향)** — 재현 비교 후 사람 결정
- RiskGate binding 한도 집계(재현 리포트)
- 측정 IC·Blom z
- Factor missingness(신뢰도 가중 중립 수축), balance_sheet feature 정의(P0-11)
- Multi-class valuation, Feature coverage

### Phase 2 — Signal Reliability
- Factor reliability
- ML calibration
- LLM calibration
- Multiple-comparison governance

### Phase 3 — Portfolio / Risk Adaptation
- Soft constraints
- Continuous exposure
- Hysteresis
- Parameter sensitivity

### Phase 4 — AI Research Quality
- Falsification schema
- Contradiction detection
- Role-level model benchmark
- Latency / cost optimization

### Phase 5 — Execution Feedback
- TCA ledger
- Implementation shortfall
- Optimizer cost feedback

### Phase 6 — Research Challengers
- Learning-to-Rank
- Quantile / Conformal
- Covariance challengers
- HRP / NCO allocation challengers
- RL overlay / Offline RL / Distributional RL

---

## 14. 모든 변경의 공통 검증 절차

모든 알고리즘 변경은 다음 절차를 따른다.

```text
Baseline
   ↓
Candidate
   ↓
Unit / Contract Tests
   ↓
Historical Replay
   ↓
Rolling / Anchored OOS
   ↓
Cost-adjusted Evaluation
   ↓
Stress / Failure Injection
   ↓
Shadow
   ↓
Manual Decision
```

---

## 15. 핵심 KPI

- **Prediction**: Rank IC, ICIR, HAC t-stat, Brier, Calibration, NDCG@K, Uncertainty coverage
- **Portfolio**: Net Return, Sharpe, Sortino, Maximum Drawdown, CVaR, Turnover, Concentration, Cash utilization
- **Adaptation**: False de-risk, Recovery lag, Regime whipsaw, Exposure stability
- **Execution**: Fill rate, Slippage, Implementation shortfall, Fees, Partial-fill reconciliation rate
- **System**: Runtime, DB calls, API calls, Stale data rate, Fallback rate, Artifact compatibility failure, LLM token/cost, Retry rate

---

## 16. Do Not Implement

다음은 현재 단계에서 도입하지 않는다.

1. 자동 Production model promotion
2. RL의 Live portfolio 직접 제어
3. LLM의 broker 접근
4. 외부 Agent framework 전면 재도입
5. 근거 없는 최신 모델 일괄 교체
6. 검증 없는 Factor timing 자동화
7. Hard RiskGate 완화
8. Unknown broker order 자동 재전송
9. TCA 증거 없는 TWAP/VWAP/POV 강제
10. OOS 증거 없는 복잡한 Deep Learning 우선 도입
11. 동일 기능의 repository/component 중복 생성
12. 문서에 근거 없는 “40% 향상”, “80% 감소” 같은 성능 수치 기록

---

## 17. Implementation Handoff

새 세션은 반드시 다음 순서로 진행한다.

- **Step 1**: 현재 `main` HEAD를 다시 확인한다.
- **Step 2**: 이 문서의 baseline SHA 이후 변경 사항을 비교한다.
- **Step 3**: 현재 P0/P1 항목이 이미 수정됐는지 실제 코드와 tests로 확인한다.
- **Step 4**: 수정되지 않은 항목만 작업 후보로 남긴다.
- **Step 5**: `INVESTMENT_DECISION_ENGINE_DESIGN.md`에서 해당 컴포넌트의 `Current`, `Champion`, `Challenger`, `Research`, `Validation`, `Promotion criteria`를 확인한다(AI Decision Layer는 Part II).
- **Step 6**: 코드를 바로 수정하지 않고 먼저 `현재 구현 / 문제 / 제안 / 변경 범위 / 검증 계획 / 예상 위험`을 사용자에게 제시한다.
- **Step 7**: 승인 후 구현한다.

---

## 18. 다음 구현 계획 (승인 대기)

문서 확정 뒤의 순서다. 각 단계는 독립 커밋이고 `git revert` 한 번으로 되돌린다. 판단·하네스 코드를
만지는 단계는 정비 보류를 먼저 건다. 상세는 설계 §57.

| 단계 | 내용 | 판단 변화 |
|---|---|---|
| 1 | 계측 보강 (P0-10) | 없음 |
| 2 | structuring state 무손실 중복 제거 + 저장 state로 A/A 대 A/B 재현 | 동등해야 함 |
| 3 | 캐시용 메시지 재배치 | 프롬프트 순서만 |
| 4 | 하네스 재기동 (사람) | — |
| 5 | 결정론 judge + shadow router 복원 — 판정만 기록 | 없음 |
| 6 | `system_ablation`에 노출 분리 변형·binding 집계, 2021-09~2026-08 재현 | 연구만 |
| 7 | 6의 결과로 P0-8 결정 (사람) | — |
| 8 | 계측 2주 뒤 reasoning_effort·verbosity 역할별 A/B 설계 제시 | — |

---

## 19. 최종 원칙

이 시스템의 발전 방향은:
```text
더 많은 모델
더 많은 Agent
더 복잡한 수식
```
이 아니다.

목표는:
```text
정확한 데이터
+ 신뢰할 수 있는 신호
+ 불확실성을 아는 모델
+ 거래비용을 아는 포트폴리오
+ 연속적으로 적응하는 Risk
+ 결정론적인 안전장치
+ 실제 결과를 다시 평가하는 Feedback
+ 검증 후에만 승격되는 Governance
```
이다.
