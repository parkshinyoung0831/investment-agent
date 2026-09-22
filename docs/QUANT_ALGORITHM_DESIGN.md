# Quant Algorithm Design — 퀀트·ML·RL 알고리즘 설계 및 평가 기준

> **문서 역할**: Factor → ML → Signal Reliability → Alpha → Covariance → Optimizer → Risk → RL → TCA → Evaluation 구간의 수식·알고리즘·Challenger와 채택 기준을 정의하는 **알고리즘 설계 SSOT**  
> **기준 SHA**: `4e02de453c977461eaee9a07bf5eb6955d28df1c` (및 `ab7e3a6ff33636cbb74f2218a2215d19d6480139`)  
> **원칙**: 최신 알고리즘이라는 이유만으로 교체하지 않는다. 현재 Champion과 동일한 데이터·동일한 OOS·동일한 비용 조건에서 검증한다.

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
| Factor categories | 6개 (Quality, Balance Sheet, Growth, Value, Revision, Momentum) | KEEP | — |
| Factor missingness | available category renormalization | REFINE | coverage-aware penalty |
| Factor weights | equal weight | CHALLENGER | shrunken IC / ICIR weight |
| Factor orthogonalization | 없음 | RESEARCH | residualization / PCA ablation |
| ML regression | Ridge / LightGBM / XGBoost | KEEP | baseline ensemble |
| ML target | 20d benchmark excess return | KEEP | ranking challenger |
| Learning-to-Rank | 없음 | CHALLENGER | LambdaMART / XGBRanker |
| Probabilistic ML | 없음 | CHALLENGER | Quantile Regression / Conformal |
| ML confidence | IC-derived heuristic (`min(0.8, mean_ic*10)`) | PARTIAL REPLACE | calibrated reliability (Brier, coverage) |
| ML validation | single purged split 중심 | REFINE | rolling walk-forward OOS |
| Alpha Fusion | Factor + ML + LLM linear tilt | KEEP | reliability layer 보강 |
| Black-Litterman fusion | 없음 | RESEARCH | Bayesian shrinkage challenger |
| Covariance | Ledoit-Wolf constant correlation | KEEP | EWMA / Factor Covariance |
| Optimizer | CVXPY cost-aware MVO | KEEP | — |
| Soft constraints | 제한적 fallback (제약 삭제) | REFINE | slack variable + violation penalty |
| No-trade band | fixed (20bp/10bp) | CHALLENGER | vol/cost-aware dynamic band |
| Market regime | threshold states (VIX/SPY200MA) | KEEP | hysteresis overlay |
| Continuous exposure | 제한적 step-down | CHALLENGER | vol / DD / macro continuous scaling |
| RiskGate | deterministic hard constraints | KEEP | 절대 유지 (Non-negotiable) |
| RL direct weights | research ($N$ logits $\to$ softmax) | RESEARCH | production 금지 |
| RL overlay | 없음 | CHALLENGER | continuous exposure controller ($g_t$) |
| RL residual | 없음 | RESEARCH | bounded delta ($\delta_t$) |
| PPO | research baseline | KEEP | baseline |
| SAC / TD3 | available research algorithms | CHALLENGER | same environment comparison |
| Offline RL | 없음 | RESEARCH | data 축적 후 (CQL / IQL) |
| Distributional RL | 없음 | RESEARCH | CVaR-sensitive distributional critic |
| TCA feedback | 고정 수수료/슬리피지 추정 | REFINE | realized implementation shortfall 피드백 |
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

현재 Factor + ML + LLM 3자 결합 방식을 유지하되, 주관적 가중치 대신 신뢰도 기반 가중평균을 적용한다:
\[
\alpha_i = \frac{R_F \alpha_{F,i} + R_M \alpha_{M,i} + R_L \alpha_{L,i}}{R_F + R_M + R_L}
\]
- **판정**: **KEEP (가중 합산 인터페이스 유지, 내부 신뢰도 계층 REFINE)**

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
