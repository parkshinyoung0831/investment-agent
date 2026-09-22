# Investment Decision Engine Design — 투자 판단 엔진 설계 및 평가 기준

> **문서 역할**: Data → Factor → ML → AI Decision Layer(System-One/Deep LLM) → Signal Reliability → Alpha → Covariance → Optimizer → Risk → RL → TCA → Evaluation 구간 전체의 수식·알고리즘·Challenger와 채택 기준을 정의하는 **투자 판단 엔진 설계 SSOT**  
> **기준 SHA**: `494de6b217384369c33b612d17d02bb49df6f80f`  
> **기준일**: 2026-09-22  
> **원칙**: 최신 알고리즘·최신 AI 모델이라는 이유만으로 교체하지 않는다. 현재 Champion과 동일한 데이터·동일한 OOS(또는 동일한 evidence)·동일한 비용 조건에서 검증한다.  
> **상위 문서**: 전체 원칙·불변 사항·구현 우선순위는 [SYSTEM_UPGRADE_MASTER.md](SYSTEM_UPGRADE_MASTER.md)가 갖는다. 이 문서는 그 §9(AI/Multi-Agent)·§10(ML/RL)이 가리키는 **구체 설계**를 소유한다.  
> **문서 구성**: Part I(§1~§40)은 Factor/ML/Alpha/Optimizer/Risk/RL/TCA, Part II(§41~)는 AI Decision Layer(System-One·Deep LLM·Multi-Agent)를 다룬다.

---

## 1. 판정 체계

모든 컴포넌트는 다음 중 하나로 판정한다.

| 판정 | 의미 |
|---|---|
| **KEEP** | 현행 유지 |
| **REFINE** | 구조는 유지하고 내부 계산 개선 |
| **CHALLENGER** | 현행 Champion을 유지한 채 비교 후보 추가 |
| **PARTIAL REPLACE** | 일부 계산 또는 계약만 교체 |
| **RESEARCH** | 검증 전 Production 반영 금지 |
| **DO NOT IMPLEMENT** | 현재 구조와 위험 대비 가치가 낮음 |

가장 중요한 원칙:

> **Challenger가 존재한다고 Champion이 폐기되는 것은 아니다.**

---

## 2. Master Decision Matrix

| 영역 | 현재 | 판정 | 우선 후보 |
|---|---|---|---|
| Factor categories | 6개 (Quality, Balance Sheet, Growth, Value, Revision, Momentum). Revision의 입력(관측 컨센서스)은 2026-09-13부터 들어오므로 그 이전 feature 스냅샷에서는 비어 있다 | KEEP | feature store 재적재 (`SYSTEM_UPGRADE_MASTER.md` P0-7) |
| Factor missingness | available category renormalization (`quality` 결측은 이미 탈락, `balance_sheet`는 결측 시 검사를 건너뜀) | REFINE | coverage-aware penalty + balance_sheet 구멍 |
| Factor weights | equal weight | CHALLENGER | shrunken IC / ICIR weight |
| Factor orthogonalization | 없음 | RESEARCH | residualization / PCA ablation |
| ML regression | Ridge / LightGBM / XGBoost | KEEP | baseline ensemble |
| ML target | 20d benchmark excess return | KEEP | ranking challenger |
| Learning-to-Rank | 없음 | CHALLENGER | LambdaMART / XGBRanker |
| Probabilistic ML | 없음 | CHALLENGER | Quantile Regression / Conformal |
| ML confidence | `min(0.8, mean_ic*10)`, 단 앞에 HAC t>=2 + horizon 일치 게이트가 있다 | PARTIAL REPLACE | calibrated reliability (Brier, coverage) — P0-5 이후 |
| ML validation | `purged_row_splits`가 walk-forward 기계를 쓰고도 `splits[0]` 하나만 반환 | REFINE | rolling walk-forward OOS (창 전체 사용) |
| AI Decision Layer | Multi-Agent LLM 그래프, 종목당 14호출 순차, 하루 20종목 상한 | KEEP | 구조화 출력 strict 전환·분석가 병렬화 우선. System-One은 RESEARCH ONLY (§49.2) |
| Alpha Fusion | factor+ML은 대칭 결합, LLM은 **비대칭 거부권 + 제한 tilt** | KEEP | tilt 배율의 LLM 자칭 confidence만 검증된 R_L로 교체 (§19) |
| Black-Litterman fusion | 없음 | RESEARCH | Bayesian shrinkage challenger |
| Covariance | Ledoit-Wolf constant correlation | KEEP | EWMA / Factor Covariance |
| Optimizer | CVXPY cost-aware MVO | KEEP | — |
| Soft constraints | infeasible 시 `factor_exposures`를 통째로 제거하고 재풀이 (`exposure_limits_relaxed`로 기록은 남김) | REFINE | slack variable + violation penalty |
| No-trade band | fixed (20bp/10bp) | CHALLENGER | vol/cost-aware dynamic band |
| Market regime | SPY 일봉 기반 4상태 계단. 조이기도 풀기도 즉시 (Slow-Up 없음) | KEEP | hysteresis overlay (Slow-Up) |
| Continuous exposure | `fit_tail_risk`가 vol·CVaR 기준 **연속** 축소를 이미 수행. regime 한도만 4단계 계단 | CHALLENGER | drawdown/macro/reliability 축 추가 |
| RiskGate | deterministic hard constraints | KEEP | 절대 유지 (Non-negotiable) |
| RL direct weights | research 전용. `src/investment_agent/research/rl/`을 trading·execution·operations가 import하지 않음(실측 확인) | RESEARCH | production 금지 |
| RL overlay | 없음 | CHALLENGER | continuous exposure controller ($g_t$) |
| RL residual | 없음 | RESEARCH | bounded delta ($\delta_t$) |
| PPO | research baseline | KEEP | baseline |
| SAC / TD3 | available research algorithms | CHALLENGER | same environment comparison |
| Offline RL | 없음 | RESEARCH | data 축적 후 (CQL / IQL) |
| Distributional RL | 없음 | RESEARCH | CVaR-sensitive distributional critic |
| TCA feedback | ADV 구간별 정적 half-spread 표. IS 계산 없음. 단 `fills(price, filled_at)`가 있어 소급 계산은 가능 | REFINE | realized implementation shortfall 피드백 |
| Automatic promotion | 없음 | KEEP | 자동 승격 영구 금지 |

---

## 3. Factor Engine

Canonical implementation: `src/investment_agent/research/factors/core.py`  
Compatibility export: `src/investment_agent/research/features/factors.py`

### 3.1 현재 구조
Factor categories (6개):
```text
Quality, Balance Sheet, Growth, Value, Revision, Momentum
```
현재 기본 모델은 가용 카테고리에 대한 동일 가중 합산에 가깝다.
\[
Score_i = \frac{1}{K_i} \sum_{k \in available_i} F_{i,k}
\]
여기서 $K_i$는 종목 $i$에서 결측되지 않은 카테고리 수다.

---

## 4. Factor Missingness

문제는 missing을 무조건 나쁜 값(0점)으로 보는 것도 아니고, missing을 완전히 무시하고 가용 카테고리만 100%로 재정규화하는 것도 coverage가 낮은 종목의 점수를 부풀리는 편향을 낳는다는 점이다.

따라서 다음 세 후보를 OOS에서 비교한다:

### Candidate A — Neutral Missing
결측 category에 대해 중립 percentile(예: 0.5)을 부여:
\[
F_{ik} = 0.5 \quad (\text{if missing})
\]

### Candidate B — Coverage Penalty
가용 카테고리의 가중평균에 결측 비율에 따른 패널티 계수를 곱함:
\[
RawScore_i = \frac{\sum_k w_k c_{ik} F_{ik}}{\sum_k w_k c_{ik}}, \quad FinalScore_i = RawScore_i \times Coverage_i^\gamma \quad (\gamma \in [0.5, 1.0])
\]

### Candidate C — Mandatory Core
핵심 카테고리(Quality, Balance Sheet)가 결측된 종목은 유니버스에서 자동 탈락시키고, 나머지 보조 카테고리에 한해서만 중립 보정.

- **판정**: **REFINE (Candidate B 우선 비교 검증 후 확정)**

---

## 5. Factor Weighting

현재 Equal Weight를 Champion으로 유지한다.

### Challenger — Shrunk IC Weight
단순 최근 롤링 IC는 노이즈가 크므로, 장기 IC와 최근 IC를 수축(shrinkage) 결합한다:
\[
IC^*_{k,t} = \rho IC_{long,k} + (1-\rho) IC_{recent,k}
\]
최종 가중치 후보:
\[
w_{k,t} \propto \max(0, IC^*_{k,t}) \times Stability_k \times Coverage_k \times RedundancyPenalty_k
\]
- 최근 IC가 일시적으로 하락했다고 즉시 가중치를 0으로 만들지 않는다.
- 자동 가중치 변경은 금지하며, 오프라인 평가 $\to$ candidate artifact $\to$ manual promotion 절차를 거친다.

---

## 6. Factor Orthogonalization

Quality, Growth, Revision, Momentum 등이 상관될 가능성은 높으나, 상관관계가 존재한다고 무조건 직교화가 OOS 샤프비를 개선하는 것은 아니다.

- **절차**:
  1. Cross-factor correlation 측정
  2. Marginal IC 및 Interaction 분석
  3. Ablation study
  4. Residualized challenger 백테스트
  5. Rolling OOS comparison
- **판정**: **RESEARCH** (Champion equal-weight 유지)

---

## 7. Machine Learning

Canonical:
- Baseline: `src/investment_agent/research/models/baselines.py`
- Training: `src/investment_agent/research/training/`
- Serving: `src/investment_agent/research/ml_serving.py`

현재:
```text
Naive, Ridge, LightGBM, XGBoost
```
를 동일한 20일 초과수익률 계약으로 비교·앙상블한다.

---

## 8. ML Target

현재 Production 타깃 정의:
\[
y_i = R_{i,20d} - R_{benchmark,20d}
\]
즉 20 거래일 기준 S&P 500 대비 초과수익률이다. 이 baseline 타깃 계약을 유지한다.

---

## 9. Learning-to-Rank

MSE 회귀는 종목 간의 상대적 랭킹보다 이상치 예측에 과도하게 반응할 수 있다. Cross-sectional selection 관점에서는 상위/하위 랭킹 정확도가 중요하므로 Ranker를 Challenger로 추가한다.

- **후보**: LightGBM `LGBMRanker` (LambdaMART), XGBoost `XGBRanker`
- **그룹 단위**: 동일 거래일의 유니버스 종목들을 query group으로 설정.
- **평가**: Rank IC, NDCG@K, Top-decile spread, Net Sharpe, Turnover
- **판정**: **CHALLENGER** (Regression 앙상블 유지)

---

## 10. Feature Scaling

현재 ML 전처리 파이프라인의 성격을 엄격히 구분한다:
1. **Missing Value**: `impute_cross_section()`을 통해 동일 시점 cross-section median 대체.
2. **Ridge Regression**: Train sample 기준의 표준화 사용:
   \[
   z = \frac{x - \mu_{train}}{\sigma_{train}}
   \]
3. **Tree Models**: 트리 계열은 단조 변환에 불변하므로 전역 스케일러를 강제하지 않음.
- **판정**: 무분별한 전면 교체가 아닌 모델별 특성에 맞춘 전처리 분리 유지.

---

## 11. ML Prediction Contract

하나의 confidence가 여러 역할을 혼용하던 구조를 다음 4개 필드로 명확히 분리한다:

```text
expected_return
probability_up
uncertainty
model_reliability
```

### 11.1 expected_return
\[
\hat{\mu}_i = \mathbb{E}[R_i - R_b]
\]

### 11.2 probability_up
\[
P(R_i - R_b > 0)
\]
개별 종목 및 예측값에 대한 calibrated probability (Platt scaling 또는 Isotonic regression 적용). 전체 모델 적중률을 일괄 복사하지 않는다.

### 11.3 uncertainty
\[
\text{Uncertainty}_i = Q_{90,i} - Q_{10,i} \quad \text{혹은 Conformal Prediction 구간 폭}
\]

### 11.4 model_reliability
개별 종목 예측값이 아닌, 모델이 역사적으로 얼마나 신뢰 가능한지를 나타내는 척도:
\[
\text{Reliability} = f(\text{Rolling OOS Rank IC}, \text{ICIR}, \text{HAC t-stat}, \text{Calibration Error})
\]

---

## 12. Probabilistic ML

- **후보**: Quantile Regression ($Q_{10}, Q_{50}, Q_{90}$), Conformal Prediction (유효 신뢰구간)
- **목표**: 점추정뿐 아니라 하방 위험 폭을 직접 추정하여 포트폴리오 최적화 페널티로 전달.
- **판정**: **CHALLENGER**

---

## 13. ML Validation

단일 train/test split이나 무작위 K-Fold를 전면 금지하고 시계열 특성을 반영한 검증을 적용한다:
- **구조**: Purged Walk-Forward CV (Embargo 적용)
- **평가 메트릭**: Mean IC, ICIR, Worst-window IC, Regime stability, Cost-adjusted Sharpe

---

## 14. Multiple Testing

다양한 하이퍼파라미터와 모델을 탐색할 때 발생하는 다중 검정 왜곡(False Discovery)을 제어한다:
- White's Reality Check, Deflated Sharpe Ratio (DSR), False Discovery Rate (FDR) 보정.
- Candidate artifact에 `evaluation_id`, `candidate_count`, `dataset_hash`, `required_threshold`를 불변으로 기록하고 검증.

---

## 15. Signal Reliability Layer

Factor, ML, LLM의 서로 다른 신호를 통합하기 전 신뢰도를 정규화하는 계층이다:
\[
EffectiveSignal_i = Signal_i \times Reliability_i \times Freshness_i \times Quality_i
\]

---

## 16. Factor Reliability
\[
R_{F,k} = \text{clip}\left(\frac{\text{ICIR}_k}{\text{Benchmark ICIR}}, 0, 1\right) \times \text{CoverageRatio}_k \times \text{Stability}_k
\]

---

## 17. ML Reliability
\[
R_M = \text{clip}\left(1 - 2 \times \text{BrierScore}, 0, 1\right) \times \mathbb{I}(\text{HAC } t > 2.0)
\]

---

## 18. LLM Reliability
LLM이 자체 보고한 확신도(self-reported confidence)를 그대로 신뢰하지 않는다:
- Historical Brier Score 역산
- Falsification 조건 명시 여부 및 반증 성공률
- 근거(Evidence) 인용 정확도 및 모순점(Contradiction) 유무에 따라 감점.

---

## 19. Alpha Fusion

**현재 구현은 3자 대칭 결합이 아니다.** 이전 판의 이 절은 신뢰도 기반 대칭 가중평균을 제안했는데,
실제 코드(`trading/decision/alpha.py:expected_return_signals`)를 다시 읽은 결과 그 제안은 **현행보다 나쁘다.**
대칭 평균은 LLM에 기대수익을 **생성할 권한**을 주고, 그것은 `SYSTEM_UPGRADE_MASTER.md` §4.2와
`alpha.py`의 "논지는 검증자다"라는 계약을 모두 거스른다.

현행 구조를 기술한다 — 숫자끼리만 대칭이고, LLM은 비대칭이다.

```text
1) factor 사전값   prior = IC × σ × z                       (Grinold)
2) ML 결합(대칭)   α = (1 − c)·prior + c·ml_return,  c = ML 신뢰도
                   ml_return은 ±1σ로 clip
3) LLM(비대칭)
   논지 음/붕괴 →  α = min(α, view_return, 0), + block_increase 또는 force_exit
   논지 양      →  α = α + (llm_tilt_weight × conf) × (view_return − α)
   검증 전 신규 →  α = min(α, 0), + block_increase
4) confidence   = source_agreement(방향을 말한 근거 중 최종 α와 같은 방향인 비율)
                  LLM이 스스로 적은 확신은 여기에 쓰지 않는다
```

- **판정**: **KEEP (비대칭 구조 유지).** 상방을 만드는 것은 factor·ML이고, LLM은 깎거나 소폭 확인만 한다.
- **REFINE 대상은 하나다** — 3단계 tilt 배율에 쓰이는 `view.confidence`가 **LLM 자칭 확신**이다.
  §18이 쓰지 말라고 한 바로 그 값이다. 이것을 §18의 검증된 `R_L`로 교체한다. 결합 구조는 바꾸지 않는다.
- `R_L`을 계산하려면 채점된 결과가 필요하다(`SYSTEM_UPGRADE_MASTER.md` P0-5). **그 전에는 이 REFINE을
  구현하지 않는다** — 근거 없는 대체값을 넣으면 자칭 확신을 다른 자칭 값으로 바꾸는 것뿐이다.

---

## 20. Black-Litterman Fusion

- **구조**:
  \[
  \mu_{posterior} = \left( (\tau \Sigma)^{-1} + P^\top \Omega^{-1} P \right)^{-1} \left( (\tau \Sigma)^{-1} \Pi + P^\top \Omega^{-1} Q \right)
  \]
- **판정**: **RESEARCH** (신뢰도 계층 검증 후 장기 과제로 진행)

---

## 21. Covariance Estimation

- **Champion**: Ledoit-Wolf Constant-Correlation Shrinkage (**KEEP**)
- **Challenger**:
  - EWMA 공분산 (Half-life 63d)
  - Statistical Factor Covariance (PCA 3~5개 팩터)
- **판정**: 현행 Champion 유지 하에 백테스트 비교.

---

## 22. Portfolio Optimizer

CVXPY 기반 Cost-aware Mean-Variance 최적화 유지:
\[
\max_w \left( \mu^\top w - \lambda w^\top \Sigma w - \gamma \text{TC}(w, w_0) - \eta \|w - w_0\|_1 \right)
\]
제약조건:
\[
\sum w_i + w_{cash} = 1, \quad 0 \le w_i \le w_{max}, \quad w_{cash} \ge c_{floor}, \quad \sum_{i \in \text{Sector}_s} w_i \le S_{max}
\]
- **판정**: **KEEP**

---

## 23. Hard vs Soft Constraints

- **Hard Constraints**: Position limit, Sector limit, Cash floor, Long-only, Forced exit (절대 양보 불가)
- **Soft Constraints**: Factor exposure 타깃, 스타일 타깃.
  - 최적화 해가 없을 때 제약을 무조건 삭제하지 않고 Slack variable $\xi_k \ge 0$과 목적함수 벌점 $-\lambda_k \xi_k$를 부여하여 점진적 완화(Soft constraint) 처리.
- **판정**: **REFINE**

---

## 24. No-Trade Band

- **Champion**: 고정폭 밴드 (20bp / 10bp)
- **Challenger**: 종목별 변동성 및 거래비용 연동 동적 밴드:
  \[
  \text{Band}_i = \max\left(\text{Band}_{min}, \beta_1 \sigma_i \sqrt{\Delta t} + \beta_2 \frac{\text{Spread}_i}{\text{Price}_i}\right)
  \]
- **판정**: **CHALLENGER**

---

## 25. HRP / NCO Allocation

- 계층적 리스크 패리티(Hierarchical Risk Parity) 및 중첩 군집 최적화(Nested Clustered Optimization)는 공분산 추정기가 아니라 자산배분 기법이다.
- **판정**: **CHALLENGER / RESEARCH**

---

## 26. Risk Architecture

2단계 리스크 구조 유지:
```text
Layer 1: Deterministic Hard RiskGate (절대 예외 없음)
Layer 2: Adaptive Exposure Overlay (시장 국면별 총 익스포저 조절)
```

---

## 27. Continuous Exposure

계단식(Step-down) 대신 연속형 위험 조절 팩터 적용:
\[
E_t^* = \min(E_{vol}, E_{drawdown}, E_{macro}, E_{reliability})
\]
- $E_{vol} = \text{clip}\left(\frac{\sigma_{target}}{\sigma_{realized}}, E_{min}, 1.0\right)$
- $E_{drawdown} = \text{clip}\left(1 - \frac{DD_t}{DD_{max}}, 0.0, 1.0\right)$

---

## 28. Hysteresis (슈미트 트리거)

위험 감지 시에는 즉시 축소, 위험 해소 시에는 점진적 복구:
\[
E_t = \begin{cases}
E_t^* & \text{if } E_t^* < E_{t-1} \quad (\text{Fast Down}) \\
(1-\eta) E_{t-1} + \eta E_t^* & \text{if } E_t^* \ge E_{t-1} \quad (\text{Slow Up, } \eta \approx 0.1)
\end{cases}
\]

---

## 29. Reinforcement Learning

- **원칙**: 연구 격리 도메인(`research/rl/`)에만 머무르며, Live 포트폴리오 직접 실행 권한을 절대 갖지 않는다.

---

## 30. RL State

개별 종목 특성, 포트폴리오 상태, 리스크 메트릭, 거시지표, 거래비용 환경을 포함하는 다차원 구조 설계.

---

## 31. RL Action Space

1. **Action A (Direct Weights)**: $N$개 종목 비중 직접 산출 $\to$ 차원 폭발 및 과적합 위험으로 **PRODUCTION 불가**.
2. **Action B (Residual Optimizer)**: 옵티마이저 비중에 $\delta_{RL}$ 가산 $\to$ **RESEARCH**.
3. **Action C (Risk Overlay)**: 스칼라 익스포저 $g_t \in [0, 1]$ 조절 $\to$ **CHALLENGER (최우선 연구 대상)**.

---

## 32. RL Reward

단순 수익률을 지양하고 비용 및 드로다운을 페널티로 반영:
\[
r_t = \log(1 + R_{net,t}) - \lambda_{TO} \text{Turnover}_t - \lambda_{DD} \Delta DD_t^+ - \lambda_{tail} \text{TailRisk}_t
\]

---

## 33. RL Algorithms

동일 환경 하에서 PPO(Champion baseline), SAC, TD3 비교.

---

## 34. Offline RL

- CQL, IQL 등 적용은 과거 천 건 이상의 transition 로그가 축적된 후 진행.
- **판정**: **RESEARCH (데이터 축적 후)**

---

## 35. Distributional / CVaR RL

- 기댓값 최적화 대신 하방 위험(CVaR) 분포를 학습하는 연구.
- **판정**: **장기 RESEARCH**

---

## 36. Transaction Cost Analysis (TCA)

실제 집행 가격과 주문 시점 가격 간의 구현 손실(Implementation Shortfall)을 signed cost로 기록:
\[
\text{IS} = \text{side} \times \frac{\text{FillPrice} - \text{DecisionPrice}}{\text{DecisionPrice}}
\]
- ADV, 스프레드, 주문 크기, 세션별 실측 데이터를 축적하여 옵티마이저의 거래비용 파라미터를 보정.
- **판정**: **REFINE**

---

## 37. Evaluation & Attribution

수익률을 억지 분해하지 않고 투명하게 기록:
```text
총 수익률 = Factor 기여 + ML 기여 + LLM 기여 + 자산배분 효과 + Risk Overlay 효과 + 거래비용/슬리피지 + 잔차(Residual)
```

---

## 38. Promotion Governance

```text
Research Candidate
       ↓
Historical Replay
       ↓
Rolling Walk-Forward OOS
       ↓
Shadow Pipeline (동일 실시간 피드)
       ↓
Stress / Infeasible Failure Injection
       ↓
Manual Promotion (사람 승인)
```

---

## 39. Algorithm Implementation Order

### Tier 1 — Correctness & Missingness
1. Factor missingness coverage penalty (`REFINE`)
2. ML prediction contract 4분리 (`PARTIAL REPLACE`)
3. Signal / Reliability 분리 레이어 (`REFINE`)

### Tier 2 — Validation & Governance
4. Rolling walk-forward OOS 검증기 (`REFINE`)
5. Calibration 및 다중 비교 제어 (`REFINE`)

### Tier 3 — Portfolio & Risk
6. Optimizer Soft constraints (`REFINE`)
7. Continuous exposure 및 Hysteresis (`CHALLENGER`)
8. Dynamic No-trade band (`CHALLENGER`)

### Tier 4 — Machine Learning
9. Learning-to-Rank (`CHALLENGER`)
10. Quantile / Conformal Prediction (`CHALLENGER`)

### Tier 5 — Portfolio Research
11. Covariance challengers (EWMA, Factor Cov)
12. HRP / NCO 배분기 (`RESEARCH`)
13. Bayesian Alpha Fusion (`RESEARCH`)

### Tier 6 — Reinforcement Learning
14. State / Reward 재설계
15. Risk Overlay Action ($g_t$)
16. PPO / SAC / TD3 비교
17. Offline / Distributional RL

---

## 40. 최종 원칙

알고리즘 선택의 기준은 "유행"이나 "복잡성"이 아니다.

```text
동일한 PIT 데이터에서
동일한 비용을 적용하고
동일한 OOS 구간에서
현재 Champion보다

더 안정적인가?
더 재현 가능한가?
Drawdown이 줄었는가?
Tail risk가 줄었는가?
Turnover가 감당 가능한가?
실제 비용을 빼고도 좋아졌는가?
여러 regime에서도 살아남는가?
```

이 모든 질문을 통과한 경우에만 프로덕션 정책으로 수동 승격한다.

---
---

## Part II — AI Decision Layer (System-One / Deep LLM)

> Part I이 "무엇이 사실이고 그 기대수익이 얼마인가"(Factor/ML/Alpha/Optimizer)를 다룬다면, Part II는 "구조화되지 않은 근거(공시·뉴스·이벤트)를 어떤 비용 단계로 해석할 것인가"를 다룬다.  
> 이 Part는 **RESEARCH 단계**다. 현재 Production 경로는 여전히 `src/investment_agent/trading/decision/agents/`의 저장소 소유 Multi-Agent 그래프(Champion)이며, 아래 내용은 그 옆에서 Shadow로 검증할 Challenger 설계다. 문서에 있다는 이유로 구현된 것으로 간주하지 않는다(§0 상위 문서 Document Contract 참고).

---

## 41. 판단 세 질문의 분리

AI 하나가 세 역할을 동시에 맡기지 않는다.

| 질문 | Owner |
|---|---|
| 무엇이 사실인가 | DB / Python 결정론적 계산 |
| 그 사실이 무엇을 의미하는가 | Factor / ML / System-One / Deep LLM |
| 그래서 비중을 얼마로 할 것인가 | Alpha Fusion / Optimizer / RiskGate (Part I) |

System-One·Deep LLM은 두 번째 질문에만 답한다. 최종 비중·주문·hard limit는 여전히 Part I과 `trading/risk/gate.py`가 소유한다(`SYSTEM_UPGRADE_MASTER.md` §4.2/§4.3, 절대 불변).

---

## 42. Intelligence Hierarchy — 비용 단계

```text
Level 0  Deterministic code (Python/Factor 계산)
Level 1  Factor / ML (수치 예측)
Level 2  System-One structured judgment (Jev 등 후보)
Level 3  Deep Reasoning LLM (현재 Production 경로)
Level 4  Human review (Discord 승인)
```

원칙: **가장 싼 단계에서 풀리는 문제는 그 단계에서 끝낸다.**

**전제 정정(2026-09-22 실측).** 이전 판은 "현재 구조는 대부분의 종목에 Level 3를 직접 적용한다"고 적었다.
사실이 아니다. Level 0(결정론) 깔때기가 이미 앞단에 있다:

```text
tracked universe (수백)
  → priority lane        보유 + 신규 공시/고영향 사건이 있는 종목만  (candidate_ranker.priority_candidates)
  → factor shortlist 60  + 재분석 주기 28일 게이트                  (select_factor_candidates)
  → 모델 예산 상한       실측 20종목/일 (300 요청 ÷ 15)             (model_pool)
  → 아무것도 due가 아니면 NoCandidatesDue로 회차 전체를 건너뛴다
```

Level 3에 실제로 도달하는 것은 **하루 최대 20종목**이고, 종목당 LLM 호출은 14건(계약 위반 시 15건)이다.
따라서 "변화 없는 종목을 매번 재판단하는 비용"은 **현재 문제로 존재하지 않는다.**

개선 여지가 있다면 Level 2 모델을 새로 끼우는 것이 아니라 **Level 0 게이트의 정밀화**다
(`SYSTEM_UPGRADE_MASTER.md` P0-4가 그 예다 — 예산 소진을 "분석함"으로 세어 232종목을 28일 억제하고 있었다).

---

## 43. Capability Router (모델명이 아닌 능력 기준 routing)

```text
DecisionRouter
├─ CALCULATION          → Python (Part I)
├─ PREDICTION            → Factor / ML (Part I)
├─ STRUCTURED_JUDGMENT   → SystemOneDecisionProvider (신규, RESEARCH)
├─ DEEP_REASONING        → DeepReasoningProvider (현재 LLM 계약 확장)
├─ VERIFICATION          → SystemOne 또는 deterministic validator
└─ PORTFOLIO_DECISION    → Optimizer / RiskGate (Part I, 절대 불변)
```

**판정**: `RESEARCH`. 기존 LLM client 계약(`trading/decision/agents/` 내부 provider 경계, 실제 이름은 재확인 필요)을 무조건 폐기하지 않는다 — 새 세션은 먼저 현재 provider 추상화가 이미 이 역할을 하는지 확인하고, 부족한 부분만 확장한다(§45).

---

## 44. System-One Decision Provider — 추상화이지 특정 벤더가 아니다

Jev를 architecture에 하드코딩하지 않는다. `SystemOneDecisionProvider`라는 인터페이스로 감싼다.

```text
SystemOneDecisionProvider.evaluate(
    state,               # 구조화된 evidence (§46)
    questions,            # atomic question set (§47)
    model_version,
    question_set_version,
)
→ {
    provider, model, model_version, question_set_version, state_schema_version,
    requested_at, latency_ms, input_tokens, cost,
    answers, confidence,
  }
```

- **후보 provider**: Jev(TypeSafe), OpenAI/Anthropic/Gemini structured output, specialized classifier/ranker, deterministic rule 확장.
- **판정**: `RESEARCH`. 어떤 provider도 이름만으로 채택하지 않는다 — §49 Provider Registry와 §48 벤치마크를 통과해야 Shadow 승격 후보가 된다.
- **Jev 관련 사실은 반드시 재조사 후 §49 형식으로만 기록한다.** 이 문서 본문에는 Jev의 가격·rate limit·context 한도를 고정 수치로 적지 않는다 — 모델 사실은 시간에 민감하다(`SYSTEM_UPGRADE_MASTER.md` §9 동일 원칙).

---

## 45. 기존 코드 재사용 우선

새 Provider 추상화를 만들기 전에 다음을 먼저 확인한다(`CLAUDE.md`의 "이미 고른 자리로 통일" 원칙과 동일):

1. `trading/decision/agents/` 내부에 이미 LLM provider를 감싸는 경계가 있는가 — 있다면 그것을 확장한다.
2. `research/evidence/reader.py`의 `PitReader`가 이미 evidence state를 조립하는가 — 있다면 System-One의 `state` 입력은 그 출력 형식을 재사용한다.
3. 신규 `SystemOneDecisionProvider`는 기존 LLM 계약과 나란히 두되 같은 인터페이스 shape(질문→구조화 답변)를 따른다면 병합을 우선 검토한다.

**세 확인의 답(2026-09-22 코드 실측). 이 절의 숙제는 끝났다 — 다시 조사하지 않는다.**

| 확인 | 답 | 위치 |
|---|---|---|
| 1. provider 경계 | **있다.** `LLMClient` Protocol: `complete_json(system, user, output_schema, task_name)` | `trading/decision/llm/client.py` |
| 2. evidence state 조립 | **한다.** `ContextBuilder.build(ticker, as_of)` → `EvidenceBundle` (PIT) | `research/evidence/context.py`, `research/adapters/trading.py` |
| 3. 병합 가능한가 | **가능하다.** 질문→구조화 답변 shape이 이미 `LLMClient`와 같다 | — |

- **결론: `SystemOneDecisionProvider`라는 신규 인터페이스를 만들지 않는다.**
  어떤 System-One provider든 `LLMClient` Protocol의 구현체를 하나 더 붙이는 것으로 충분하고,
  `state` 입력은 `EvidenceBundle`을 그대로 쓴다.
- §43의 `DecisionRouter`도 마찬가지로 **신규 파일이 아니다.** routing이 필요해지면
  `trading/decision/analysis.py`의 후보 선정·엔진 선택 지점에서 한다.

---

## 46. Universe Funnel — Change Detection First

```text
Universe (tracked/관심종목)
        │
        ▼
Factor / ML (Part I, 이미 전량 계산됨)
        │
        ▼
Deterministic Change Detector
   신규 filing? 8-K? guidance 변경? estimate revision?
   price/vol shock? macro exposure 변화?
        │
   변화 없음 ──────────────→ 이전 판단 freshness만 갱신, 재호출 안 함
        │
   변화 있음
        ▼
System-One Light Scan (RESEARCH)
        │
   ordinary ──────────────→ 종료
        │
   interesting / material
        ▼
System-One Deep Scan 또는 현재 Deep LLM Multi-Agent (Champion)
        │
   clear ──────────────────→ Alpha로
        │
   uncertain / novel / disagreement
        ▼
Deep Reasoning (System-Two) + Verification (§ 47.4)
```

**핵심**: Deterministic Change Detector는 **새로 만들 것이 아니라 이미 있는 것이다.**
`trading/decision/candidates.py`의 `candidate_tickers()`와 `candidate_ranker.py`의
`priority_candidates()`·`select_factor_candidates()`가 위 깔때기의 전부를 이미 수행한다 —
신규 공시(`filed_at`), 고영향 사건(`event_feature_snapshots`), 글로벌 사건 민감도,
품질 붕괴(`held_factor_breakdown`), 재분석 주기(28일), 예산 상한까지.

따라서 이 절의 작업은 "도입"이 아니라 **기존 owner의 정밀화**다(`CLAUDE.md`의 "이미 고른 자리로 통일").

- **판정**: Change Detector는 **`KEEP` + `REFINE`** — 신규 컴포넌트를 만들지 않고
  `candidate_ranker`를 고친다. 알려진 REFINE 대상은 `SYSTEM_UPGRADE_MASTER.md` P0-4다.
- System-One Light/Deep Scan은 `RESEARCH` 유지.

---

## 47. Question Design

### 47.1 Atomic Question 원칙

거대한 단일 질문("이 회사가 좋은 투자처인가?")을 지양하고, 하나의 판단만 담당하는 질문으로 분해한다.

```text
revenue_growth_healthy?
margin_improving?
balance_sheet_deteriorating?
valuation_excessive?
estimate_revision_positive?
momentum_supportive?
material_news_present?
thesis_broken?
evidence_sufficient?
deep_reasoning_required?
```

### 47.2 Question Registry

질문 자체를 코드에 흩어진 문자열로 관리하지 않고 버저닝한다.

```text
QuestionSet: name, version, domain, question_id, primitive,
             criteria, allowed_choices, description, owner, created_at
```

예: `fundamental_v1`, `market_v1`, `event_v1`, `macro_v1`, `thesis_v1`, `verification_v1`, `router_v1`. QuestionSet이 바뀌면 새 evaluation artifact로 취급한다(§14 Multiple Testing과 동일한 artifact 불변성 원칙).

### 47.3 Escalation 조건 (Deep Reasoning 호출 기준)

다음 조건을 만족할 때만 Level 3(Deep LLM)를 호출한다 — 전량 호출을 기본값으로 두지 않는다.

```text
low System-One confidence
high signal disagreement (Factor/ML/System-One 방향 불일치)
novel corporate event (과거 evidence로 커버되지 않음)
complex filing (10-K/10-Q 실질 변경)
conflicting evidence
high financial impact (포지션 크기 대비)
insufficient structured representation
```

### 47.4 Verification Layer

Deep LLM 출력은 바로 Alpha에 들어가지 않는다.

```text
claim supported by evidence?
citation valid?
contradiction present?
unsupported assumption?
materiality overstated?
```

`§18 LLM Reliability`의 계산(historical Brier, falsification 성공률, citation 정확도)과 동일 계약을 공유한다 — 별도 reliability 계산을 새로 만들지 않는다.

- **판정**: Question Registry `CHALLENGER`(결정론적 인프라이므로 검증 후 채택 가능), Escalation Router `RESEARCH`, Verification Layer는 `§18`을 재사용하는 `REFINE`.

---

## 48. Multi-Agent 재평가 — Champion vs Challenger

현재 저장소 소유 그래프(Champion, `SYSTEM_UPGRADE_MASTER.md` §9에 기술):

```text
Market → Fundamental → News → Sentiment → Macro → Bull/Bear → Research Manager → Trader → Risk Debate → Portfolio Manager
```

를 sacred architecture로 취급하지 않되, **증명 없이 교체하지도 않는다.** 다음 Challenger와 동일 evidence·동일 종목·동일 기간으로 비교한다.

| Challenger | 설명 |
|---|---|
| B. Parallel Atomic Decisions | §47.1 질문을 병렬로 평가 후 집계 |
| C. System-One + Conditional Deep LLM | §46 funnel 전체 |
| D. Deterministic + ML only (AI 없음) | AI가 실제로 가치를 더하는지의 baseline |

비교 항목: decision quality, calibration(Brier), evidence grounding rate, latency(p50/p95), token/cost, failure rate, 투자 유용성(Rank IC·Sharpe 기여, §37 Attribution과 연결).

**Ablation은 필수**: `Factor only` → `Factor+ML` → `Factor+ML+System-One` → `Factor+ML+Deep LLM` → `Full system`.
AI 계층이 실제로 수익·위험 개선에 기여했는지 이 사다리로 확인하지 않으면 채택 근거가 없다.

**이 사다리의 AI 없는 구간은 이미 구현돼 있다.** `research/system_validation/ablation.py`와
진입점 `operations/commands/system_ablation.py`가 운영 엔진을 그대로 재생하며 다음 변형을 제공한다:

```text
factor_only        AlphaPolicy(use_ml=False, use_thesis=False)     ← Challenger D
factor_ml          AlphaPolicy(use_thesis=False)
factor_ml_thesis   운영 구성 (Champion)
no_tail_risk / no_market_risk / cvar_5 / cvar_12
```

즉 이 절의 다음 행동은 "만들기"가 아니라 **"돌리기"**다.

**단, 지금은 돌려도 결론이 나오지 않는다.** 같은 파일의 주석이 정확히 지적하듯 논지 변형의 차이는
논지가 기록된 기간에서만 의미가 있는데, 현재 기록된 성공 판단은 **57건 / 2026-09-09~15의 7일**뿐이다.
게다가 채점 결과는 0건이다(`decision_evaluations` 0행, `SYSTEM_UPGRADE_MASTER.md` P0-5).

- **판정**: `RESEARCH`. Challenger D(AI 없음)는 baseline으로 반드시 포함한다 — 구현은 이미 있다.
- **선행 조건**: P0-5(채점 루프)가 연결되고 논지·결과가 충분히 쌓이기 전에는 이 벤치마크의
  결론을 인용하지 않는다. 표본 없는 비교는 비교가 아니다.

---

## 49. Provider Registry — 시간에 민감한 사실

모델·가격·API 한도는 architecture fact가 아니라 시점 스냅샷이다. 본문에 고정 수치를 적지 않고 다음 형식으로만 기록한다(값은 예시 skeleton, 실제 값은 조사 시점에 채움).

```text
provider:
model:
version:
checked_at:
official_source:
input_price:
output_price:
rate_limit:
context_limit:
known_limitations:
benchmark_result:   # §48 비교 결과 artifact 참조
```

새 세션은 이 문서를 읽을 때 여기 적힌 값을 그대로 믿지 말고, 작업 시점에 공식 자료로 다시 확인한다(`SYSTEM_UPGRADE_MASTER.md` §9 동일 원칙 — 두 문서가 이 규칙을 중복 선언하는 것이 아니라, 여기는 AI Decision Layer용 registry 위치를 못 박는다).

### 49.1 조사 기록

아래는 **조사 시점 스냅샷**이다. 값이 아니라 형식이 이 문서의 자산이며, 수치는 반드시 재확인한다.

```text
provider:          TypeSafe AI
model:             jev
version:           jev-latest / 핀 가능 (jev-1.12, jev-1.13.0)
checked_at:        2026-09-22
official_source:   https://typesafe.ai/blog/introducing-system-one-models-and-jev
                   https://docs.typesafe.ai/llms-full.txt
input_price:       $0.042 / MTok
output_price:      $0.00 (과금하지 않음)
rate_limit:        공식 문서에 수치 미공개 (429 반환만 명시)
context_limit:     공식 문서에 미공개
latency:           대부분 ~100ms, 공표 70-500ms
calibration:       Choice/Score는 confidence(0-1) + 전체 확률분포 반환.
                   Noul은 확률만 반환하고 confidence는 없다. 학습법 RLCD.
known_limitations: - 문자열 생성 불가 (설계상)
                   - 텍스트 전용 (이미지/음성/영상 불가)
                   - Choice 최대 255 옵션
                   - 비영어(CJK 포함) 정확도가 현재 낮다고 공식 명시
                   - 공개 2026-09-15, GA 2026-09-20 (이력 7일)
benchmark_result:  없음 — 이 저장소에서 벤치마크한 적이 없다
```

```text
provider:          Azure OpenAI (현재 운영 Champion)
model:             gpt-5-mini
version:           2025-08-07
checked_at:        2026-09-22
official_source:   https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs
                   https://developers.openai.com/api/docs/models/gpt-5-mini
input_price:       $0.25 / MTok
output_price:      $2.00 / MTok
context_limit:     400,000 / max output 128,000
rate_limit:        배포별 할당. 우리 쪽 가드는 AI_INVESTOR_AZURE_DAILY_REQUESTS(기본 300)
structured_output: json_schema + strict:true 지원 (Azure v1 엔드포인트).
                   현재 코드는 구식 json_object를 쓴다 → 전환 여지
known_limitations: - strict 스키마가 minimum/maximum/minLength/minItems 등을 지원하지 않는다
                     → 수치 범위 검증은 Python 계약에 남겨야 한다
                   - 전 필드 required + additionalProperties:false 강제
                   - 중첩 5단계 / 속성 100개 상한
                   - structured output 사용 시 logprobs가 비어 온다 → logprob 기반 calibration 불가
benchmark_result:  이 저장소의 운영 Champion. 단 채점 결과 0건(P0-5)
```

### 49.2 Jev 판정 (2026-09-22)

**`RESEARCH ONLY` — SHADOW 승격도 아직 불가.** 근거를 중요도 순으로 적는다.

1. **비교 기준이 존재하지 않는다.** Champion의 채점된 결과가 0건이다(P0-5). §48이 요구하는
   calibration·decision quality 비교를 **수행할 방법이 현재 없다.** Champion을 못 재는데 Challenger를
   재는 것은 의미가 없다.
2. **경제적 동기가 실재하지 않는다.** §42의 전제가 틀렸다. 실제는 20종목/일 상한이고, 병목은 비용이
   아니라 우리가 건 예산 가드다. 절감할 비용의 크기조차 아직 측정되지 않았다(P0-6).
3. **대체재가 아니라 추가 계층이다.** Jev는 문자열을 만들지 않으므로 `thesis`·`key_risks`·`reasoning`을
   생성할 수 없다. 이 필드들은 `SecurityProposal` 계약과 투자 알림 카드의 일부다. Jev를 넣어도
   Deep LLM은 남고 계층이 하나 늘어난다.
4. **CJK 정확도 저하를 공식 문서가 명시한다.** 이 저장소의 system 프롬프트·질문·evidence는 대부분
   한국어다. 영어 재작성이 선행 조건인데, 그 자체가 Champion과 다른 프롬프트가 되어 §48의
   "동일 evidence" 비교 조건을 깬다.
5. **공개 이력이 7일이다.** "환각하지 않는다"는 스키마 일치 보장이지 사실 정확도 보장이 아니다
   (공식 블로그도 그 부분은 실증이 아니라고 적는다). §52의 "이름만으로 채택 금지"에 정면으로 걸린다.

**재검토 트리거 — 아래가 모두 충족되면 SHADOW 후보로 다시 평가한다.**

```text
1. decision_evaluations >= 200행, 최소 3개월 분포   → Champion의 Brier·방향정확도 확정
2. tokens/cost/latency 계측이 30일 이상 누적         → 절감 가능액이 숫자로 존재
3. system_ablation을 논지 커버리지가 충분한 구간에서 실행
4. 3에서 AI 계층의 기여가 유의                       → 아니면 Jev가 아니라 AI 축소가 정답
5. Jev 공개 이력 >= 6개월, rate limit/context 공식 명시
```

**4번이 핵심이다.** AI 계층 자체가 가치를 더하지 못하면 Jev 논의는 불필요하다.

---

## 50. AI Cost / Latency 계측

Part I §15 KPI에 다음을 추가한다 — System-One/Deep LLM 도입 여부와 무관하게 먼저 계측 가능해야 한다.

```text
requests/ticker, input_tokens/ticker, output_tokens/ticker,
cost/ticker, latency p50/p95/p99,
escalation_rate = deep_llm_tickers / system_one_scanned_tickers,
retry_rate, failure_rate
```

계측 없이 "Jev가 90% 저렴하다" 같은 수치를 문서나 코드 주석에 남기지 않는다(`SYSTEM_UPGRADE_MASTER.md` §16.12와 동일 금지 사항).

**현재 상태(2026-09-22 실측): 이 값들은 계측 가능한 것이 아니라 계측 코드가 없다.**
`trading/decision/llm/client.py:complete_json()`이 provider 응답의 `usage`를 버리고 호출 시간도 재지 않는다.

```text
requests/ticker      14 (계약 위반 시 15)   ← 실측 가능 (코드 경로 계수)
종목/일 상한          20                     ← 실측 가능 (예산 ÷ 15)
input/output tokens  측정 불가
cost/ticker          측정 불가
latency p50/p95/p99  측정 불가
escalation_rate      정의 불가 (escalation 계층이 없다)
```

따라서 §50의 선행 작업은 `SYSTEM_UPGRADE_MASTER.md` P0-6(계측 추가)이다. 그전에는 어떤 provider 비교에도
비용·지연 항목을 채우지 않는다.

---

## 51. Promotion Path (AI Decision Layer 전용)

Part I §38 Promotion Governance와 동일한 절차를 따르되, AI 계층은 추가로 다음을 거친다.

```text
Research Candidate (System-One / Challenger 구조)
       ↓
동일 evidence로 Shadow 실행 (Champion과 나란히, 결과만 기록·미사용)
       ↓
§48 Ablation + Benchmark 비교
       ↓
Escalation Rate·Cost·Latency가 계측되어 있는가 (§50)
       ↓
Verification Layer 통과율 확인 (§47.4)
       ↓
Manual Promotion (사람 승인) — 자동 승격 금지
```

Shadow 단계에서도 System-One/Deep LLM은 broker·최종 비중에 어떤 영향도 주지 않는다(`SYSTEM_UPGRADE_MASTER.md` §4.2 절대 불변).

---

## 52. Do Not Implement Yet (AI Decision Layer)

Part I §16과 별개로, AI 계층 전용 금지 목록:

```text
System-One/Deep LLM의 직접 broker 제어
System-One/Deep LLM의 직접 position weight 산출
Question Set의 자동 mutation (사람 리뷰 없는 질문 변경)
Provider model version floating (artifact에 버전 고정 없이 최신 alias 사용)
전량 Universe에 Deep LLM 상시 호출을 benchmark 없이 기본값화
Jev(또는 임의 provider)를 이름만으로 Production 채택
```

---

## 53. Part II 최종 원칙

좋은 투자 판단 엔진은 AI를 더 많이 쓰는 시스템이 아니라:

```text
Python이 계산할 것을 계산하고
Factor/ML이 예측할 것을 예측하고
System-One(검증되면)이 반복적 판단을 싸게 처리하고
Deep LLM이 정말 어려운 문제만 생각하고
Optimizer/RiskGate(Part I)가 최종 비중과 안전을 결정하고
실제 결과가 다시 모든 단계를 평가하는 시스템이다.
```

**AI 계층의 복잡성은 §48 Ablation이 실제 가치를 증명했을 때만 늘린다.**
