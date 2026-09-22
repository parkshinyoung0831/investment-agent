# System Upgrade Master Plan — 시스템 고도화 마스터 플랜 및 SSOT

> **문서 역할**: 전체 투자 시스템의 현재 상태, 불변 원칙, 확인된 문제, 목표 아키텍처, 구현 우선순위와 검증 절차를 정의하는 **고도화 계획의 단일 기준 문서(SSOT)**  
> **기준 브랜치**: `main`  
> **분석 기준 SHA**: `494de6b217384369c33b612d17d02bb49df6f80f`  
> **기준일**: 2026-09-22  
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

- **상태**: `OPEN` (설계 결함 확인, 심각도는 플랫폼에 따라 다름)
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

- **상태**: `OPEN`
- **대상 파일**: `src/investment_agent/research/storage/repository.py` 및 artifact 복원 스크립트
- **실제 에러 로그**:
  ```text
  duckdb.duckdb.BinderException: Binder Error: Table "feature_sets" does not have a column named "feature_set"
  ```

#### 현재 문제
GitHub Actions `tech_indicators` 워크플로에서 과거 빌드된 `research.duckdb` artifact를 캐시에서 복원했을 때, 코드베이스의 최신 DDL에 추가된 컬럼(`feature_set` 등)이 과거 DB 파일에 존재하지 않아 크래시가 발생했다.

#### 목표 및 해결 방안
Artifact 복원 시 schema 호환성 계약을 추가한다.
- Artifact 메타데이터 계약 정의: `store_type`, `schema_generation`, `code_commit`, `created_at`
- Restore 시 검증:
  - Compatible $\to$ 캐시 재사용
  - Incompatible $\to$ DDL migration 수행(`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) 또는 손상/불일치 시 fail-safe rebuild 수행.

---

### P0-3 GitHub Workflow input contract mismatch

- **상태**: `OPEN`
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

- **상태**: `OPEN`
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

`INVESTMENT_DECISION_ENGINE_DESIGN.md` §37이 요구하는 Factor/ML/LLM 기여 분해도 마찬가지다.
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

- **상태**: `OPEN`
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
- **남은 것**: 로그는 회전한다. 종목당 합계를 durable하게 둘 자리(case 기록 artifact 또는
  원장 컬럼)는 아직 정하지 않았다. 30일 누적 분석 전에 정한다.

---

## 7. 핵심 고도화 우선순위

### P1 — 정확성과 신뢰도

#### 7.1 Multi-class valuation
회사의 경제적 시가총액은:
\[
MarketCap_{issuer} = \sum_c Shares_c \times Price_c
\]
로 계산하는 것을 목표로 한다.
현재 class share 총합 개선은 존재하지만 BRK.A/B처럼 economic value가 다른 share class는 별도 검증이 필요하다.

#### 7.2 Factor Missingness
현재 available category만 재정규화하면 coverage가 낮은 종목이 불합리하게 높은 점수를 받을 가능성이 있다.
Production에 특정 해법을 바로 넣지 않고 다음 challenger를 비교한다:
- Neutral Missing
- Coverage Penalty
- Mandatory Core Categories
- Bayesian shrinkage toward neutral

판정 기준: OOS Rank IC, ICIR, Turnover, Stability, Coverage bias.

#### 7.3 Signal Reliability Layer
현재 Factor·ML·LLM confidence는 서로 다른 의미를 가진다.
이를:
```text
Signal
Reliability
Uncertainty
Freshness
Data Quality
```
로 분리한다. 개념적으로:
\[
\alpha_{effective} = Signal \times Reliability \times Freshness \times DataQuality
\]
를 사용한다. 단, 실제 계산식은 `INVESTMENT_DECISION_ENGINE_DESIGN.md`의 challenger 검증을 거친다.

#### 7.4 ML Promotion Governance
Model evaluation 당시의:
- candidate count, evaluation ID, dataset hash, required t-stat, multiple-comparison setting
을 artifact에 immutable하게 남긴다. Adoption 단계에서 동일 context를 다시 검증한다.

#### 7.5 Optimizer constraint hierarchy
Constraint를 구분한다:
- **Hard**: Position cap, Sector cap, Cash floor, Long-only, Forced exit, Crisis safety
- **Soft**: Quality target, Momentum target, Value target
Soft constraint는 infeasible 시 전체 삭제하지 않고:
\[
\text{Slack variable} + \text{Violation penalty}
\]
를 사용한다.

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

따라서 "변화 없는 종목의 반복 비용"은 현재 문제로 존재하지 않는다. System-One의 비용 근거는
**측정된 뒤에**(P0-6) 다시 세워야 하며, 이 절이 미리 그 근거를 가정하지 않는다.

- 구체 설계(Intelligence Hierarchy, Capability Router, Change Detection, Question Registry, Escalation, Verification, Champion vs Challenger 벤치마크, Provider Registry)는 `docs/INVESTMENT_DECISION_ENGINE_DESIGN.md` Part II(§41~§53)가 소유한다.
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

### Phase 1 — Data / Factor Correctness
- Multi-class valuation
- Factor missingness
- Feature coverage

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

## 18. 최종 원칙

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
