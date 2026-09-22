# `investment-agent` 퀀트·ML·RL·옵티마이저 의사결정 수식 및 가중치 전면 심층분석 (Mathematical & Algorithmic Audit)

> **기준 브랜치**: `main` (SHA: [`ab7e3a6`](https://github.com/parkshinyoung0831/investment-agent/commit/ab7e3a6ff33636cbb74f2218a2215d19d6480139))  
> **분석 기준일**: 2026-09-22  
> **분석 대상 전 구간**: `Factor → ML → Alpha Fusion → Covariance → Optimizer → Risk/Regime → RL → Execution/TCA → Evaluation/Promotion`  
> **핵심 결론**: 현재 시스템 구조 자체를 다시 뜯어고칠 필요는 없으나, **내부 계산 로직·수식·가중치·신뢰도(Confidence)·RL 액션/보상 함수에는 사람 손으로 정한 휴리스틱 비중**이 상당수 남아 있어 정밀 고도화의 여지가 매우 큽니다.

---

## 1. 27대 알고리즘 컴포넌트 최종 판정 총괄표

| 번호 | 영역 | 현재 상태 | 판정 | 중요도 |
|---|---|---|---|---|
| **1** | **Factor 구성** | 6개 category + percentile 순위화 | **유지** | ✅ |
| **2** | **Factor 결측 처리** | 가용 category만 100% 재정규화 | **내부 개선 필요** | 🔴 P1 |
| **3** | **Factor 가중치** | 기본 동일가중 (`weights: 1.0`) | **Reliability 기반 challenger** | 🔴 P1 |
| **4** | **Factor 통계검정** | 단순 overlap 보정 ($\sqrt{\text{overlap}}$) | **HAC / Block-Bootstrap화** | 🔴 P1 |
| **5** | **ML 기본 모델** | Ridge / LightGBM / XGBoost | **합리적 baseline 유지** | ✅ |
| **6** | **ML 학습목표** | 20d SPY 초과수익률 MSE 회귀 | **Learning-to-Rank 추가** | 🔴 P1 |
| **7** | **ML 불확실성** | 사실상 없음 (점예측만 출력) | **Quantile / Conformal challenger** | 🔴 P1 |
| **8** | **ML Confidence** | $\min(0.8, \text{mean\_IC} \times 10)$ 휴리스틱 | **부분 교체** | 🔴 P1 |
| **9** | **Probability Up** | 전체 일괄 direction accuracy 복사 | **Calibrated Probability로 분리** | 🔴 P1 |
| **10** | **ML 검증 방식** | 단일 60/20/20 purged split | **Rolling Walk-Forward OOS** | 🔴 P1 |
| **11** | **Alpha Fusion** | Factor + ML + LLM 선형 보간/틸트 | **구조 유지, 신뢰도 계층 개편** | 🔴 P1 |
| **12** | **LLM Confidence** | 자기보고 확신도가 실제 알파 크기 왜곡 | **사후 Brier 기반 Calibration** | 🔴 P1 |
| **13** | **Covariance** | Constant-correlation Ledoit-Wolf | **유지 + challenger 확장** | 🟡 P2 |
| **14** | **Optimizer 본체** | MVO + cost + turnover 볼록 최적화 | **유지** | ✅ |
| **15** | **Factor Constraint** | Infeasible 시 팩터 제약 전면 제거 | **Soft Constraint (Slack+Penalty)** | 🔴 P1 |
| **16** | **RiskGate** | Deterministic 불변식 하드 게이트 | **절대 유지** | ✅ |
| **17** | **Regime 판정** | 4단계 고정 hard threshold | **Continuous Overlay + Hysteresis** | 🔴 P1 |
| **18** | **Macro Exposure** | 100 / 90 / 75 / 55% 계단식 스위치 | **연속형 스케일러 challenger** | 🟡 P2 |
| **19** | **RL State** | feature + mask + weights 단순 나열 | **Optimizer / Risk 상태 구조화** | 🔴 대폭 개선 |
| **20** | **RL Action** | 직접 전체 목표비중 산출 시도 | **Risk Overlay / Residual challenger** | 🔴 대폭 개선 |
| **21** | **RL Reward** | 고정 선형합 ($1.0r_t + 0.5(r_t - b_t)$) | **순수익/드로다운 페널티 재설계** | 🔴 대폭 개선 |
| **22** | **RL 알고리즘** | 코드는 5종이나 PPO만 단독 실험 | **SAC / TD3 / PPO 공통 챌린저** | 🟡 개선 |
| **23** | **Distributional RL** | 미도입 | **Research (연구 보류)** | 🧪 장기 |
| **24** | **Offline RL** | 미도입 | **Research (데이터 축적 후)** | 🧪 장기 |
| **25** | **TCA 모델** | ADV bucket vs 백테스트 5bp 혼재 | **비용 모델 일관성 통일** | 🔴 P1 |
| **26** | **체결 피드백 루프** | 부분 계약만 존재 | **Closed-loop TCA 보정** | 🟡 P2 |
| **27** | **모델 자동 승격** | 없음 (사람의 명시적 채택 필수) | **그대로 유지** | ✅ |

---

## 2. 팩터 엔진 (Factor Model): 결측치 재정규화 편향 및 가중치 고도화

### 2.1. 결측치 재정규화 편향 (Missingness Bias) 제거
- **현재 구현 위치**: `src/investment_agent/research/features/factors.py`
- **현행 수식**:
  $$Score_i = \frac{Q_i + B_i + G_i + V_i + R_i + M_i}{6}$$
  데이터가 없는 category는 분모에서 빠진 뒤 남은 것들끼리 다시 100%로 재정규화(Renormalize)됩니다.
- **구조적 결함**:
  - 기업 A: 6개 카테고리 모두 존재 ($Q=0.8, G=0.8, M=0.8, V=0.8, R=0.8, B=0.8$) $\to$ 평균 0.80
  - 기업 B: 3개 카테고리만 존재 ($Q=0.8, G=0.8, M=0.8$, 나머지 결측) $\to$ 남은 3개만으로 100% 재정규화되어 똑같이 평균 0.80 부여
  - 결과적으로 **정보가 결측된 불완전 기업에 대한 페널티가 없어, 데이터가 부족한 기업이 우연히 높은 종합 점수(Composite)를 받는 왜곡**이 발생합니다.
- **개선 수식 (점수와 Coverage의 분리)**:
  $$Score_i = \frac{\sum_k w_k c_{ik} F_{ik}}{\sum_k w_k c_{ik}} \times \text{CoveragePenalty}_i$$
  - $\text{CoveragePenalty}_i = \left(\frac{\sum_k c_{ik}}{K}\right)^\gamma \quad (\gamma \approx 0.5 \sim 1.0)$
  - missing = bad (0점 처리)도 아니고, missing = 아무 문제 없음 (단순 분모 제외)도 아닌, **'점수 $\times$ 커버리지 신뢰도'** 구조로 개편합니다.

---

### 2.2. 팩터 가중치: 단순 IC 비례의 함정과 수축(Shrinkage) 모델
- **현재 구현 한계 (`factor_research.py`)**:
  통계적으로 양수인 category만 단순 $w_k \propto \text{mean}(IC_k)$로 제안합니다.
  또한 현재 팩터 연구 엔진은 상장폐지·합병 종목을 제거하여 생존 편향이 있고, 배당을 미반영하며, 겹치는 보유기간 보정도 단순 $\sqrt{\text{overlap}}$ 수준으로 ML의 Newey-West/HAC보다 취약합니다.
- **개선 수식 (장기 Prior + 롤링 OOS 수축)**:
  $$IC^*_{k, t} = \lambda IC_{\text{long}, k} + (1 - \lambda) IC_{\text{recent}, k}$$
  - 표본이 적거나 최근 IC가 불안정하면 자동으로 장기 안정적 Prior 쪽으로 수축(Shrinkage)시킵니다.
  - **최종 가중치 함수**:
    $$w_k \propto \max(0, IC^*_k) \times \text{Stability}_k \times \text{Coverage}_k \times \text{RedundancyPenalty}_k$$
  - 이번 달 모멘텀 IC가 일시적으로 나빠졌다고 $w_M = 0$으로 만들어버리는 식의 조급한 '팩터 타이밍(Noise Trading)'을 엄격히 방지합니다.

---

### 2.3. 팩터 간 다중공선성(Multicollinearity) 제어
- **현상**: Quality, Growth, Revision, Momentum 간의 상관관계를 측정하거나 잔차화(Orthogonalization)하지 않고 단순 합산하여, 사실상 같은 성격의 기업군에 3중으로 표를 몰아주는 왜곡 위험 존재.
- **원칙**: 수학적으로 무조건 직교화부터 넣지 않고, 먼저 $\text{Corr}(F_i, F_j)$와 OOS Marginal IC를 측정한 후 **Ablation(단일 팩터 제거 vs 결합 vs 잔차화 비교)**을 거쳐 실측 OOS 샤프비율이 개선될 때만 단계적으로 적용합니다. (자동 팩터 직교화는 Research 단계 유지)

---

## 3. 머신러닝 (ML): 회귀에서 랭킹(Ranking)으로, 그리고 신뢰도 분리

### 3.1. Learning-to-Rank (`LGBMRanker`, `XGBRanker`) 챌린저 도입
- **현재 구현**: `baselines.py`는 20일 SPY 초과수익률을 타깃으로 하는 MSE(L2) 회귀 모델(`LGBMRegressor`, `XGBRegressor`)을 사용.
- **금융 데이터와의 괴리**:
  - 포트폴리오 관리가 요구하는 것은 "AAPL이 정확히 +3.43%인가"가 아니라 **"AAPL > MSFT > AMZN 순으로 더 오를 것인가(상대 순위)"**입니다.
  - 2026년 크로스섹션 자산가격결정 연구에서도 절대수익 예측보다 종목 상대순위를 직접 최적화하는 **Learning-to-Rank**를 적용했을 때 Sharpe와 Drawdown이 통계적으로 유의미하게 개선됨이 확인되었습니다 ([SSRN 2026](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6348379)).
- **구현 방식 (Zero Add-on)**:
  - 이미 저장소의 `pyproject.toml`에 내장된 `lightgbm 4.7.0`과 `xgboost 3.4.1` 내부의 `LGBMRanker(objective="lambdarank")`, `XGBRanker`를 활용.
  - 기존 회귀 모델을 삭제하는 것이 아니라, **동일 데이터·동일 purged OOS에서 실시간으로 성능을 겨루는 Challenger**로 추가합니다.

---

### 3.2. ML Confidence의 수학적 결함 및 4개 차원 분리
- **현재 코드의 결함 (`ml_inference.py`)**:
  $$\text{confidence} = \min(0.8, \text{mean\_IC} \times 10)$$
  - $\text{IC} \times 10$이라는 공식에는 금융·통계학적 근거가 전혀 없습니다.
  - 더 심각한 문제는 **날짜별 모델 전체의 단일 수치가 모든 개별 종목에 똑같이 적용**된다는 점입니다. AAPL의 예측이 안정적인지, 변동성이 극심한 NVDA의 예측이 불안정한지를 전혀 구별하지 못합니다.
- **Probability Up의 오류**:
  - 현재 코드는 모델 전체의 방향 적중률(`direction_accuracy`)을 그대로 복사하여 사용합니다. 모델 적중률이 57%라면 예측치가 +0.1%든 +15.0%든 똑같이 `probability_up = 0.57`을 부여합니다.
- **목표 아키텍처 (4대 계약의 완전 분리)**:
  | 계약 필드 | 수학적 정의 | 역할 |
  |---|---|---|
  | `expected_return` | 점예측치 $\hat{\mu}_i$ | 포트폴리오 1차 기대수익 재료 |
  | `probability_up` | Calibrated $P(R_i > R_{\text{benchmark}})$ | 로지스틱/플랫 스케일링 보정 확률 |
  | `uncertainty` | 개별 자산 예측 오차 범위 ($Q_{90, i} - Q_{10, i}$) | 포지션 크기 축소 팩터 |
  | `model_reliability` | 모델의 OOS Walk-Forward ICIR & t-stat | 신호 결합 가중치 |

---

### 3.3. 불확실성 추정 (Quantile / Conformal Prediction)
- 점예측 $\hat{\mu}_i = 4.2\%$만 사용하는 대신, 분위수 회귀(Quantile Regression)를 통해 하방/상방 범위를 함께 추정합니다:
  $$Q_{10, i} = -3.1\%, \quad Q_{50, i} = 4.2\%, \quad Q_{90, i} = 12.8\%$$
  - 종목 A: 예상수익 +6%, 범위 $[-15\%, +22\%]$ (높은 불확실성)
  - 종목 B: 예상수익 +5%, 범위 $[+1\%, +9\%]$ (낮은 불확실성, 확실한 안전마진)
  - 동일한 기대수익이라도 종목 B에 더 높은 신뢰도를 부여할 수학적 근거가 확보됩니다 ([arXiv 2026](https://arxiv.org/abs/2601.00593)).

---

### 3.4. 롤링 Walk-Forward OOS 다중 윈도우 검증 및 승격 거버넌스
- **단일 Split 탈피**: 현재의 2년 데이터 단일 60/20/20 Purged Split을 `Window 1, 2, 3...`의 Rolling/Anchored Walk-Forward 다중 윈도우로 확장.
- **다중비교 보호 복원**: `ml_challengers.py`에서 4개 모델 비교 시 본페로니 보정(`comparisons=4`)으로 탈락한 아티팩트가 수동 채택 CLI(`adopt_ml_model.py`, 기본 `comparisons=1`)로 우회 채택되는 허점을 차단. 아티팩트 내에 `selection_context`를 영구 불변 저장.

---

## 4. 알파 결합 (Alpha Fusion) & 중앙 Signal Reliability Layer

### 4.1. 현재 Alpha Fusion의 3대 문제점
1. **Factor IC의 고정 상수화**: `AlphaPolicy.information_coefficient = 0.04`로 하드코딩되어 연구 결과와 분리됨.
2. **독립성 착시(Correlated Evidence) 문제**: ML 피처에 이미 모멘텀·밸류·퀄리티가 들어가 있는데, `source_agreement()`는 단순 부호 일치 개수만 세어 상관된 증거를 독립된 두 표처럼 과대 계산.
3. **LLM 확신도의 알파 왜곡**: 코드 주석에는 "LLM이 스스로 적은 확신은 사용하지 않는다"고 적혀 있으나, 실제 코드(`alpha.py:260`)에서는:
   $$\text{weight} = \text{policy.llm\_tilt\_weight} \times \text{view.confidence}$$
   로 계산되어 검증되지 않은 LLM의 자체 확신도가 최종 알파 크기를 직접 움직이고 있음.

---

### 4.2. 중앙 Signal Reliability 계층 아키텍처
기존 10단계 파이프라인 뼈대를 보존하면서, Alpha Fusion 직전에 논리적인 **Signal Reliability Layer**를 배치합니다.

```text
Factor  ──────┐
ML / Ranker ──┼──► [SIGNAL RELIABILITY LAYER] ──► [ALPHA FUSION] ──► [CVXPY OPTIMIZER]
LLM Thesis ───┤     ├─ OOS Historical ICIR            │
Events/Macro ─┘     ├─ Asset-level Uncertainty        ▼
                    ├─ Forecast Calibration      Effective Alpha
                    ├─ Data Freshness & Coverage
                    └─ Evidence Disagreement
```

- LLM의 신뢰도는 "LLM 스스로 주장한 0.9"가 아니라, 사후 평가 원장에서 집계된 **Brier Calibration, 방향 적중률, 인용 유효성, 반증 조건 준수율**을 기반으로 객관적 스코어로 산출합니다.

---

## 5. 포트폴리오 최적화 (Optimizer) & 공분산 (Covariance)

### 5.1. 공분산 행렬 (Covariance): Ledoit-Wolf 유지 및 챌린저 체계
- **현행 Ledoit-Wolf Constant-Correlation 유지**:
  샘플 공분산의 노이즈를 제거하고 가역성(Invertibility)을 보장하는 우수한 베이스라인입니다. 최신 비선형 수축(Nonlinear/Spectral Shrinkage)은 턴오버와 HHI 집중도를 악화시키는 트레이드오프가 존재합니다 ([RINAM 2026](https://doi.org/10.1016/j.rinam.2026.100720)).
- **Challenger 로드맵**:
  `Constant-Correlation LW (Champion)` $\to$ `EWMA 변동성 결합 수축`, `Factor Covariance`, `시장 상태 의존형 수축(State-dependent Shrinkage)` ([JFEC 2026](https://academic.oup.com/jfec/article/24/2/nbag002/8512976))을 비교군으로 운영.

---

### 5.2. Factor Constraint Fallback: 하드 제거에서 소프트 슬랙(Soft Slack)으로 전환
- **현재 구현의 위험성 (`system/target.py`)**:
  ```python
  try:
      optimize(..., factor_exposures=limits)
  except ContractError:
      optimize(..., factor_exposures=None)  # 제약 전면 삭제!
  ```
  품질 $\ge 0.55$, 모멘텀 $\le 0.80$, 밸류 $\le 0.80$ 중 단 하나라도 infeasible이 나면 **세 제약을 전부 날려버리고 최적화**를 재시도합니다.
- **개선 수식 (Soft Constraints with Slack Variables)**:
  $$\max_w \left[ \mu^\top w - \lambda w^\top \Sigma w - \gamma \|w - w_0\|_1 - C(w - w_0) - \sum_k \lambda_k \xi_k \right]$$
  $$\text{s.t.} \quad \text{FactorExposure}_k(w) + \xi_k \ge \text{Limit}_k, \quad \xi_k \ge 0$$
  - 목표가 0.55인데 가능한 최선이 0.537이라면, 제약을 전부 지우는 것이 아니라 **0.537을 채택하고 위반량 $\xi = 0.013$을 메타데이터에 정량 기록**합니다.
  - 단, 종목 상한(10%), 최소 현금(5%), Forced Exit, CRISIS 매수 금지는 절대 완화할 수 없는 **Hard Constraint**로 100% 보존합니다.

---

### 5.3. 파라미터 Sensitivity Surface 분석
`risk_aversion = 5.0`, `max_turnover = 0.25`, `no_trade_band = 0.01` 등 하드코딩된 값들을 RL이 실시간으로 조작하게 두지 않고, Walk-forward 환경에서 민감도 곡면(Sensitivity Surface)을 격자 탐색하여 특정 지점 과적합이 아닌 넓고 평탄한 안정 구간(Plateau)을 기본 정책값으로 채택합니다.

---

## 6. 리스크 & 시장 국면 (Regime & Continuous Exposure)

### 6.1. 계단형 하드 임계값 절벽(Cliff) 해소
- **현행**: VIX 31.9% $\to$ NORMAL (현금 0%), 32.0% $\to$ RISK_OFF (현금 15% 강제, 종목 상한 80% 축소). 거시 100% $\to$ 90% $\to$ 75% $\to$ 55% 계단식 스위치.
- **2-Layer 하이브리드 리스크 아키텍처**:
  ```text
  [Layer 1: Deterministic Hard Guard]  ← 절대 안전 보장 (RiskGate, CRISIS 비상 정지)
  ──────────────────────────────────────────────────────────
  [Layer 2: Continuous Risk Overlay]   ← 변동성/낙폭/거시/신호 불확실성에 비례한 부드러운 완충
  ```

---

### 6.2. 비대칭 히스테리시스 (Fast-Down / Slow-Up Hysteresis)
- **위험 발생 시**: 즉시 민첩하게 익스포저 축소 (Fast-Down)
  $$E^*_t = \min(E_{\text{vol}}, E_{\text{CVaR}}, E_{\text{DD}}, E_{\text{macro}}, E_{\text{reliability}})$$
  $$E_t = E^*_t \quad (\text{if } E^*_t < E_{t-1})$$
- **위험 해제/회복 시**: 섣부른 재진입을 막고 천천히 점진적 복귀 (Slow-Up)
  $$E_t = (1 - \eta) E_{t-1} + \eta E^*_t \quad (\eta \approx 0.1 \sim 0.2)$$
- 이를 통해 폭락장 진입 시에는 계좌를 즉시 방어하고, 기술적 반등 후 재폭락하는 이중 바닥 구간에서의 톱니 매매(Whipsaw)를 완벽히 차단합니다 ([arXiv 2026](https://doi.org/10.48550/arXiv.2605.27848)).

---

## 7. 심층강화학습 (RL): 비중 직접 생성에서 Risk Overlay로의 대전환

### 7.1. 현재 RL 파이프라인의 구조적 한계
1. **RL Action의 무리한 범위**: RL 에이전트가 $N$개 종목의 logits $\to$ softmax를 통해 500개 종목의 포트폴리오 비중을 처음부터 끝까지 직접 생성하려고 시도함. 노이즈가 극심한 금융 환경에서 거대한 액션 공간은 필연적으로 과적합과 회전율 폭발로 귀결됨.
2. **RL State의 구조화 부족**: 옵티마이저 기본 비중, 팩터 알파, 공분산, CVaR, 낙폭, 거래비용 등 고수준 리스크 지표가 누락됨.
3. **RL Reward의 수학적 결함**:
   $$R_t = 1.0 r_t + 0.5 (r_t - b_t) - \ldots = 1.5 r_t - 0.5 b_t - \ldots$$
   - 벤치마크 수익률 $b_t$는 에이전트의 행동과 무관한 상수(외생 변수)입니다.
   - 따라서 $0.5(r_t - b_t)$는 알파를 극대화하는 독립적 목표가 아니라, 단순히 포트폴리오 수익률 계수를 1.0에서 1.5로 뻥튀기하는 수학적 왜곡에 불과합니다.

---

### 7.2. RL Action의 3대 실험 및 Risk Overlay 채택

```text
[방식 1: 현행 직접 생성]
RL ──► AAPL 7%, MSFT 5%, NVDA 4% ... (비추천: 거대한 탐색 공간, 노이즈 과적합)

[방식 2: Residual 방식]
Optimizer (AAPL 6%) ──┐
                      ├──► w_final = Projection(w_optimizer + δ_RL)
RL Residual (δ = +0.3%) ┘

[방식 3: Risk Overlay 방식 (★ 적극 권장)]
Optimizer ──► 종목 간 상대 비중 결정 (w_optimizer)
RL Agent  ──► 전체 위험자산 익스포저 계수 g_t 결정 (0.0 ~ 1.0)
                w_final,risky = g_t × w_optimizer
                w_cash = 1 - Σ w_final,risky
```

- **Risk Overlay가 최적인 이유**:
  이미 시스템에 `Factor/ML/LLM (종목 선택)` $\to$ `Optimizer (상대 비중)` $\to$ `Risk (총 익스포저)`라는 훌륭한 책임 분리가 존재하므로, RL을 총 익스포저 조절 챌린저로 배치할 때 기존 아키텍처 불변식을 단 1%도 훼손하지 않습니다.

---

### 7.3. RL Reward 함수 재설계 및 알고리즘 확장
- **개선 보상 함수**:
  $$R_t = \log(1 + r^{\text{net}}_t) - \lambda_{\text{TO}} \text{TO}_t - \lambda_{\text{DD}} \Delta \text{DD}_t^+ - \lambda_{\text{tail}} \text{TailRisk}_t$$
  - 실질 순수익률($r^{\text{net}}_t$), 회전율 비용, 새롭게 악화된 드로다운($\Delta \text{DD}_t^+$), 테일 리스크만을 명확히 분리하여 보상 부여.
  - 하드 세이프티(종목 10% 상한 등)는 보상 함수로 학습시키는 것이 아니라 결정론적 투영(Projection)과 `DeterministicRiskGate`로 강제.
- **알고리즘 챌린저 확장 (PPO 고정 탈피)**:
  `research/rl/trainer.py`에 이미 존재하는 **A2C, DDPG, PPO, SAC, TD3**를 동일 환경·동일 시드에서 공정하게 비교하는 챌린저 러너 구축. 특히 연속 제어에서 엔트로피 탐색이 우수한 **SAC(Soft Actor-Critic)**을 주요 챌린저로 평가 ([arXiv 2026](https://arxiv.org/abs/2605.17307), [Springer 2026](https://link.springer.com/article/10.1007/s44163-026-01869-x)).

---

### 7.4. 장기 연구 보류 (Research Backlog)
- **Distributional / CVaR RL**: 전체 수익률 분포를 학습하는 유망 기술이나 Stable-Baselines3 범위를 초과하므로 장기 연구로 보류 ([ScienceDirect 2026](https://www.sciencedirect.com/science/article/pii/S1568494625015820)).
- **Offline RL (CQL, IQL)**: 오프라인 정책 학습은 데이터 다양성(State-Action Coverage)이 수만 건 이상 누적된 이후에 착수.

---

## 8. 체결 비용 (TCA) 불일치 해소 및 피드백 루프

- **비용 모델 불일치 해결**:
  - 프로덕션 Optimizer: ADV 버킷 모델 (ADV $\ge \$1\text{B} \to 1\text{bp}$, $\ge \$100\text{M} \to 3\text{bp}$, 기타 $\to 10\text{bp}$)
  - 백테스트 엔진: 고정 슬리피지 5bp
  - 연구에서 승리한 모델이 실전 비용 구조에서도 이기도록 **백테스트와 옵티마이저의 비용 모델을 완벽히 일치**시킴.
- **실제 체결 TCA 피드백 (P2)**:
  $$\text{Implementation Shortfall} = \frac{\text{Fill Price} - \text{Decision Price}}{\text{Decision Price}}$$
  실계좌 주문의 선택 편향(Selection Bias)을 방지하기 위해, **Paper/Shadow 체결 데이터로 System 비용 모델을 보정**하고 실제 My Portfolio 체결 데이터는 실계좌 실행 파라미터 보정에만 격리 사용.

---

## 9. 목표 타깃 아키텍처 (Target Decision Flow)

```text
DATA / PIT / INTEGRITY
  │
  ▼
┌────────────────────────────────────────────────────────┐
│  Factor Engine (Coverage-aware & Shrinkage Weighting)  │
│  ML Engine (LambdaMART Ranker + Quantile Uncertainty) │
│  LLM Multi-Agent (Popperian Falsification Triggers)    │
│  Macro & Corporate Events                              │
└────────────────────────────────────────────────────────┘
  │
  ▼
SIGNAL RELIABILITY LAYER (중앙 신뢰도 계층)
  ├─ OOS Walk-Forward ICIR & HAC t-stat
  ├─ Asset-level Prediction Uncertainty
  ├─ Brier Score Calibration
  ├─ Coverage & Data Freshness
  └─ Inter-model Correlation & Disagreement
  │
  ▼
ALPHA FUSION (Effective Alpha = Signal × Reliability)
  │
  ▼
COST-AWARE CVXPY OPTIMIZER (Soft Factor Constraints with Slack)
  │
  ├────────────────────────┐
  ▼                        ▼
CONTINUOUS RISK OVERLAY   RL RISK OVERLAY CHALLENGER
(Hysteresis Fast/Slow)    (g_t 익스포저 조절 연구)
  │                        │
  └───────────┬────────────┘
              ▼
DETERMINISTIC HARD RISKGATE (최종 하드 리스크 SSOT)
              │
              ▼
      SYSTEM PORTFOLIO (이상적 목표 비중)
              │
        ┌─────┴────────────────────┐
        ▼                          ▼
Shadow / Historical Replay   My Portfolio Follow (실계좌)
(지속 평가 및 오답노트 축적)     │
                                  ▼
                            Discord Approval → Toss Execution
```

---

## 10. 21단계 세부 구현 우선순위 로드맵

```text
[P0: 기본 무결성 복구] (선행 필수)
0-1. SQLite Inode Schema Cache 버그 수정 (PRAGMA user_version)
0-2. DuckDB feature_sets Schema Migration 및 Artifact 호환성 계약
0-3. Universe Membership Backfill Workflow Contract 수정

[P1: 알고리즘 및 신뢰도 계층 구축]
1.  Factor 연구 통계를 HAC / Block-Bootstrap 수준으로 강화
2.  Factor 결측치/커버리지 재정규화 편향 제거 (Coverage Penalty)
3.  mean_IC × 10 단순 confidence 제거 및 개별 자산 불확실성 계약 분리
4.  probability_up의 방향 적중률 복사 탈피 및 Calibration 보정
5.  LightGBM / XGBoost Learning-to-Rank (LambdaMART) 챌린저 탑재
6.  ML 검증을 단일 60/20/20에서 Rolling Purged Walk-Forward로 확장
7.  ML 모델 채택(Adoption) 다중검정(Multiple-testing) 컨텍스트 불변 고정
8.  LLM 자체 확신도의 알파 직접 영향 제거 및 사후 Brier 기반 보정
9.  중앙 Signal Reliability Layer 인터페이스 구축
10. Optimizer의 Factor Exposure 제약을 Hard 삭제에서 Soft Slack + Penalty로 전환
11. Backtest와 Optimizer 간의 Transaction Cost Model 정합화
12. 계단식 Regime 위에 Continuous Exposure + Fast-down / Slow-up Hysteresis 오버레이 구축

[P2: 체결 피드백 및 확장 챌린저]
13. EWMA / Factor / Nonlinear Covariance 챌린저 러너 구축
14. PPO / SAC / TD3 공통 알고리즘 챌린저 러너 구축
15. Macro Exposure 계단식 스위치의 연속형 스케일러 전환
16. 실제 및 모의 체결 기반 Closed-loop TCA 피드백 루프 연결

[Research Backlog: 장기 연구]
17. RL State 구조화 및 Risk Overlay 액션 연구
18. RL Reward 함수 다중 목표 재설계 및 컴포넌트별 Ablation
19. Distributional / CVaR RL 타당성 연구
20. HMM / 확률적 시장 국면 모델 연구
21. Wasserstein Distributionally Robust Optimization (DRO) 및 고급 옵티마이저 연구
```

---

## 11. 절대 건드리지 말아야 할 불변의 강점 (Invariants to Preserve)

아무리 최신 논문이나 새로운 기술이 나오더라도, 시스템의 안전과 무결성을 지탱하는 다음 12가지 요소는 **절대 변경하지 않고 보존**합니다:

1. **PIT (Point-in-Time) 및 데이터 계보(Provenance) 구조**
2. **인간 승인(Discord Approval)과 System Portfolio의 완전 분리**
3. **Shadow 지속 학습 및 오답노트 축적의 독립성**
4. **결정론적 하드 리스크 게이트 (`DeterministicRiskGate`) SSOT**
5. **미확인 브로커 주문(Unknown Order) 자동 재전송 절대 금지**
6. **실계좌 대사(Reconciliation) 메커니즘**
7. **논지 붕괴 시 Forced Exit 및 신규 매수 차단(Block Increase) 강제**
8. **롱온리(Long-only) 하드 한도 및 종목 10%, 섹터 30% 상한**
9. **CVXPY의 최종 포트폴리오 비중 결정 독점권**
10. **LLM이 직접 주문을 내거나 비중을 결정하지 못하게 하는 안전 차단선**
11. **검증 없는 모델/파라미터 자동 승격(Automatic Adoption) 금지**
12. **Ledoit-Wolf 수축 공분산 행렬의 기본 챔피언 지위**
