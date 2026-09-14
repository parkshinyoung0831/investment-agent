# 투자 시스템 — 판단, ML/RL, Backtest와 Portfolio Risk

이 문서는 Supabase 데이터가 투자 신호와 포트폴리오 제안으로 바뀌는 과정을 설명한다.
`src/investment_agent/trading`은 투자안을 만드는 계층이며 broker 주문을 직접 보내지 않는다.

## 전체 판단 흐름

```text
tracked universe
→ data quality·coverage·liquidity filter
→ 후보 순위와 실행 limit
→ PIT EvidenceBundle / FeatureBundle
├→ TradingAgents 정성 분석
├→ ML expected-return baseline
└→ RL challenger research
→ 공통 ExpectedReturnSignal
→ CVXPY Portfolio Optimizer
→ PortfolioProposal
→ DeterministicRiskGate
→ RiskDecision
→ Backtest 또는 Shadow/Paper/Live 실행 경계
```

LLM은 분석·토론·설명과 종목별 신호를 만든다. 최종 비중은 optimizer가 계산하고 hard risk는
RiskGate가 강제한다. AI/ML/RL은 risk policy, broker credential과 durable safety control을
수정할 권한이 없다.

## 현재 실행 경로

현재 로컬 하네스가 호출하는 분석 진입점은
`src/investment_agent/trading/decision/portfolio_shadow.py`다.

| 구분 | 파일 | 현재 역할 |
|---|---|---|
| 현재 주 경로 | `trading/decision/portfolio_shadow.py` | TradingAgents→signal→optimizer→RiskGate Shadow 실행 |
| 현재 adapter | `agents/tradingagents_adapter.py` | Supabase EvidenceBundle을 TradingAgents에 전달 |
| LLM provider | `llm.py` | OpenAI-compatible endpoint와 structured output |
| 보조 Shadow 경로 | `trading/decision/shadow_daily.py`, `role_runner.py` | 로컬 multi-role Shadow와 계약 검증 |

파일이 존재한다는 이유만으로 예약 실행 경로라고 판단하지 않는다. 실제 호출 여부는
`src/investment_agent/operations/harness_adapters.py`와 `.github/workflows`에서 확인한다.

## 후보 선정과 Evidence

S&P 500 전체를 매일 LLM에 보내지 않는다.

| 단계 | 주요 코드 | 결과 |
|---|---|---|
| Universe 확인 | `universe.py::select_tracked_tickers` | 허용 member와 제외 사유 |
| 후보 정렬 | `candidate_ranker.py::rank_candidate_features` | coverage와 변화 기반 분석 순서 |
| 근거 생성 | `context.py::ContextBuilder.build` | PIT `EvidenceBundle`, missing/warnings |
| Agent 실행 | `TradingAgentsDecisionEngine.run` | role output와 외부 evidence manifest |
| 계약 검증 | `SecurityProposal.from_dict` | ticker/as-of/range/evidence ID 검증 |
| 신호 보관 | `SignalBook` | batch, TTL, 성공·실패 ticker |

### EvidenceBundle 도메인 구성

`ContextBuilder.build`는 아래 8개 도메인을 순서대로 채우고, 그 시점에 데이터가 없는 도메인은
evidence 대신 `missing_data`에 사유를 남긴다. `news_archive`는 Supabase에 시점 저장소가 없어
매번 missing으로 남는다.

| 도메인 | 소스 | `available_at` 기준 | 비어있을 때 |
|---|---|---|---|
| market | `market.prices_daily` | 최신 행 `ingested_at` | "market: 시점 기준 사용 가능한 가격 없음" |
| technical | ResearchStore `feature_signals_daily` + `market.prices_daily` | feature 행 `ingested_at` | "technical: 시점 기준 기술지표 없음" |
| fundamentals | SEC EDGAR/FSDS, `fundamentals.financials` + `fundamentals.filings` | live: 최신 `ingested_at` / historical_replay: `filed_at`·`available_at` cutoff | source_kind별 문구로 "fundamentals: ..." |
| estimates | yfinance observed snapshots | 최신 `collected_at` | "estimates: 시점 기준 실제 관측 컨센서스 없음" |
| macro | `macro.series`+`observation_versions` | 관측치 `collected_at` 최댓값 | historical_replay는 항상 제외; live에서 실행·관측이 없으면 missing |
| segments | SEC XBRL, `fundamentals.segment_metrics` | filings `updated_at` | provider unavailable 여부로 사유 분기 |
| gurus | SEC 13F, `institutional.filings` + `institutional.positions` | filings `accepted_at` | "gurus: 추적 매니저의 매핑된 보유 근거 없음" |
| economic_calendar | `macro.release_events` + release versions | 최신 `collected_at` | "economic_calendar: 시점 기준 관련 발표 일정·관측값 없음" |
| news_archive | Supabase 시점 저장소 없음 | — | 항상 missing; live 외부 provider 사용 여부는 Agent 정책에 따름 |

### 후보 정렬 점수 계산

후보 점수는 매수 점수가 아니라 분석 순서다. 가장 오래 분석되지 않은 종목을 먼저 보고,
같은 조건이면 구조화 데이터 변화가 큰 종목을 우선한다. `rank_candidate_features`는 도메인별
percentile을 가중 평균해 이 우선순위를 계산한다.

| 도메인 | 가중치 | percentile로 바꾸는 신호 |
|---|---:|---|
| market | 0.30 | 20일 수익률 절대값, 20일 거래량비 log 절대값 |
| fundamentals | 0.25 | 매출 YoY 성장률 절대값, 영업이익률 절대값 |
| technical | 0.20 | RSI14의 50 이탈폭, MACD-signal 스프레드 절대값 |
| gurus | 0.15 | guru 보유자 수, guru 총 보유금액(log1p) |
| segments | 0.10 | 세그먼트 집중도, 세그먼트 품질 |

각 신호는 그날 tracked universe 안에서 dense percentile(0~1)로 바뀐다 — 값 자체의 크기가 아니라
다른 종목 대비 변화폭이 큰 종목일수록 1에 가깝다.

```mermaid
flowchart TD
    CF["CandidateFeatures<br/>(도메인별 원본 지표)"] --> PCT["도메인별 dense percentile<br/>(0=평균적 · 1=가장 극단적)"]
    PCT --> AVAIL{"데이터 있는 도메인이<br/>하나라도 있는가"}
    AVAIL -- "없음" --> ZERO["score = 0"]
    AVAIL -- "있음" --> RAW["raw_score =<br/>합(weight × percentile) / 합(있는 도메인 weight)"]
    RAW --> COV["coverage_multiplier =<br/>0.80 + 0.20 × (있는 도메인 수 / 5)"]
    COV --> SCORE["score = raw_score × coverage_multiplier"]
    SCORE --> SORT["정렬키: last_analyzed_at 오름차순(미분석 우선)<br/>→ -score 내림차순 → ticker"]
    ZERO --> SORT
```

## TradingAgents와 LLM의 역할

TradingAgents는 Market/Fundamental/News/Social 분석, Bull/Bear 토론과 risk reasoning을 수행한다.
자연어 토론은 설명 자료이지 주문 계약이 아니다. 최종 parser는 다음과 같은 구조화 필드만
허용한다.

- ticker와 timezone-aware as-of
- signal, probability, confidence
- expected excess return과 risk score
- reasoning과 실제 bundle에 존재하는 evidence ID
- missing data와 model/engine version

다음은 계약 오류다.

- 다른 ticker/as-of 또는 허용 목록 밖 signal
- 0~1 범위 밖 probability/confidence
- 존재하지 않는 evidence ID
- NaN/Infinity expected return
- 빈 reasoning 또는 임의 schema field

호환용 `target_weight`가 output에 있어도 optimizer 입력에서는 무시한다.

### 외부 텍스트와 비용

뉴스·소셜은 live 계열에서만 untrusted evidence로 사용할 수 있다. URL/content 중복 제거,
instruction-like text 제거, 길이 제한과 provider quota/cache를 적용한다. broker key와 execution
control은 prompt/context에 포함하지 않는다.

```text
tracked universe
→ 정량 후보 축소
→ AI_INVESTOR_DAILY_LIMIT
→ request/content cache
→ provider daily cap
→ 소수 ticker만 deep analysis
```

`OpenAICompatibleClient`는 원격 endpoint와 Ollama/local model 교체를 허용하지만 provider,
model, prompt와 engine version이 달라지면 별도 artifact로 기록하고 Shadow 검증을 다시 한다.

## Memory와 평가

`memory.py`는 horizon이 끝나고 `evaluator.py`가 실제 결과를 기록한 case만 같은 ticker의 참고
기억으로 사용한다. 아직 미래 가격이 확정되지 않았거나 benchmark가 없으면 0점으로 만들지 않고
미평가로 남긴다. 기억은 현재 evidence를 대체하지 않고 주문 권한도 없다.

## Feature Layer

`FeatureLayer`는 `EvidenceBundle.as_of_at` 이하 evidence만 사용해 version/hash가 있는
`FeatureBundle`을 만든다. 이는 현재 TradingAgents 주 실행 경로의 필수 호출이 아니라 ML/RL/Qlib
학습과 serving이 공유할 연구 입력 경계다.

feature와 1D·5D·20D label은 시각적으로 분리한다 — feature는 `as_of_at` 시점에 바로 만들어지지만,
label은 그 뒤 실제 종가가 확정돼야만 만들어진다. dataset identity에는 feature version, cutoff,
universe snapshot과 dataset hash가 포함된다.

```mermaid
flowchart TD
    subgraph NOW["지금 시점 T (EvidenceBundle.as_of_at)"]
        EB["EvidenceBundle<br/>(도메인별 EvidenceItem)"] --> EXT["도메인별 추출<br/>_close_returns · _technical · _fundamental · _macro · _gurus"]
        EXT --> CHK{"모든 evidence.available_at ≤ as_of_at ?"}
        CHK -- "아니오" --> ERR["RLSafetyError<br/>(미래정보 유출 차단)"]
        CHK -- "예" --> FS["FeatureSnapshot<br/>feature_version · source_ids<br/>provenance.definition_hash"]
        FS --> FB["FeatureBundle<br/>definition_version + definition_hash<br/>horizons = 1 · 5 · 20"]
    end

    subgraph LATER["T+H 거래일 이후 (H = 1 · 5 · 20)"]
        FUT["future_closes[H]<br/>benchmark_closes[H]<br/>(실제 종가 확정 후)"] --> LBL["FeatureLayer.labels()"]
        LBL --> FL["ForwardReturnLabel<br/>forward_return · benchmark_forward_return"]
    end

    FS -. "같은 snapshot 참조" .-> LBL
    FB --> DS["dataset_hash =<br/>feature_version + cutoff + universe snapshot"]
    FL --> DS
```

같은 `snapshot`(feature_version·as_of_at·ticker)을 참조해야만 feature와 label이 나중에 하나의
학습 row로 합쳐진다 — label을 feature와 같은 시점에 만들지 않는 이유가 이 시차다.

## ML baseline을 먼저 비교한다

`src/investment_agent/research/models/baselines.py`는 같은 train/validation/OOS 배열로 다음 모델을 비교한다.

| 모델 | 목적 | 의존성 |
|---|---|---|
| Naive | 복잡한 모델이 실제로 개선됐는지 기준 | NumPy |
| Ridge | 안정적 선형 expected return | NumPy |
| LightGBM | 비선형 tree boosting 비교 | 선택 설치 |
| XGBoost | 독립 boosting 구현 비교 | 선택 설치 |

기본 목표는 5D expected return이며 1D·20D도 사용할 수 있다. RMSE/MAE와 방향 정확도 외에,
학습 결과에는 **OOS 날짜별 단면 IC**(`research/evaluation/alpha.py`: 평균 IC·ICIR·t-통계량·
상위-하위 분위 spread)가 `out_of_sample_alpha`로 남는다. 날짜를 섞은 순위 상관은 시장 전체의
공통 움직임을 순위 능력으로 착각하므로 채택·신뢰도 판단에 쓰지 않는다.

### ML을 판단에 합치는 경로

```text
TradingAgents SecurityProposal ─┐
                                ├→ research/ml_serving.py (fusion) → SignalBatch → construct.py
채택된 ML artifact + PIT feature ┘
```

- 채택은 `python -m investment_agent.research.commands.adopt_ml_model --artifact <json>` 하나다.
  재로딩 가능한 모델(naive·ridge)이고, OOS 평균 IC > 0, IC t ≥ 2, OOS 20일 이상, 분위 spread > 0일
  때만 `artifacts/trading/ml_models/active_ml_model.json`으로 복사된다.
- ML 반영 비중은 사람이 정하지 않는다. 신뢰도 = min(0.8, 평균 IC × 10)이고 t < 2면 0이라 합치지 않는다.
- ML은 기대수익·상승확률·신뢰도만 바꾼다. `exit`·`reduce` 같은 행동은 TradingAgents 의견 그대로이고,
  부정 의견(avoid·watch·exit)의 기대수익을 0 위로 올리지 못한다.
- 추론 feature는 판단 시점 이전에 공개된 가장 최근 한 날짜의 **전 종목** snapshot으로 결측을 대체한다
  (학습 dataset과 같은 규칙). 분석한 몇 종목만으로 중앙값을 내면 training-serving skew가 생긴다.
- 반영되면 LLM·ML 조합이 새 artifact ID로 기록되어, paper/live는 그 조합이 승격돼야 실행된다.
  `AI_INVESTOR_ML_FUSION_ENABLED=false`면 비교만 기록한다.

### 분석 후보의 우선 레인

정기 후보 순위는 오래 안 본 종목을 앞세운다. 그 앞에 `candidate_ranker.priority_candidates`가
**마지막 분석 이후 새 정보가 생긴 종목**을 먼저 넣는다 — tier 0은 보유 중이면서 새 공시(`filed_at`)나
고영향 사건(`event_feature_snapshots`)이 공개된 종목과 한 번도 분석하지 않은 보유종목, tier 1은
미보유지만 중요도 0.75 이상 사건이 난 종목이다. 보유 목록은 최근 7일 안의 live position snapshot이다.

```powershell
uv sync --group ml
python -m unittest tests.investment_agent.research.rl.test_baseline
```

## Dataset split과 재현성

시계열 투자 데이터는 random shuffle하지 않는다.

```text
train
→ label horizon이 경계를 넘는 row purge
→ embargo
→ validation
→ out-of-sample
→ rolling/walk-forward 반복
```

같은 날짜의 종목 cross-section은 같은 split에 두며, 현재 S&P 구성 종목을 과거 전체에 고정하지
않는다. universe snapshot이 없는 구간은 승격 dataset으로 만들지 않는다.

모든 artifact에는 다음 identity를 남긴다.

- algorithm과 parameter
- feature version과 dataset hash
- train/validation/OOS 기간
- random seed와 code commit
- model file SHA-256
- 평가 metric과 benchmark

파일과 DB metadata/hash가 일치하지 않으면 inference와 promotion에 사용하지 않는다.

## RL은 ML 다음의 Challenger다

`src/investment_agent/research/rl`은 Stable-Baselines3 PPO를 대표 baseline으로 사용한다. action은 주문 수량이
아니라 target-weight policy다. environment는 transaction cost, turnover와 drawdown penalty를
반영한다.

```text
동일 OOS PPO 결과가 ML baseline보다 우수
→ challenger 후보
그 외
→ research_only
```

PPO라는 이름만으로 실전에 승격하지 않는다. 여러 walk-forward window와 Paper 무사고 조건을
별도로 통과해야 한다. algorithm class 경계를 통해 A2C/SAC/TD3/DDPG 등을 나중에 추가할 수 있다.

## Qlib의 제한된 사용 범위

`qlib_adapter.py`는 PIT `FeatureSnapshot`을 `(datetime, instrument)` frame으로 바꾸고
`DataHandlerLP`/`DatasetH`와 recorder에 연결한다.

Qlib는 다음만 담당한다.

- versioned research dataset 구성
- train/valid/test segment와 rolling workflow
- experiment parameter, metric와 artifact 기록

Supabase ETL이나 이 프로젝트의 source of truth를 Qlib vendor data로 교체하지 않는다.

```powershell
uv sync --group research
```

## 공통 ExpectedReturnSignal

ML/RL/TradingAgents output은 다음 계약으로 정규화한다.

| 필드 | 의미 |
|---|---|
| `symbol` | canonical symbol |
| `expected_return` | horizon 예상 수익률 |
| `confidence` | 0~1 신뢰도 |
| `risk_score` | 0~1 상대 위험 |
| `horizon_days` | 1, 5, 20 trading days |
| `source`/`version` | model/engine artifact identity |
| `timestamp` | timezone-aware 생성시각 |
| `evidence_ids` | 사용한 stable evidence IDs |

## Portfolio Optimizer

`RiskAwareOptimizer`는 CVXPY로 다음 목적을 결정론적으로 최적화한다.

```text
expected return × confidence
- risk aversion × variance
- turnover penalty (L1)
- Σ 반스프레드·|Δw| + Σ impact·σ·√(NAV/ADV)·|Δw|^1.5
```

거래비용 항은 cvxportfolio의 선형+1.5승 시장충격 모형이다. 주문이 20일 평균 거래대금(ADV)에
비해 클수록 단위 비용이 커져, 기대수익이 약간 높아도 거래하기 비싼 종목은 비중이 줄어든다.
반스프레드는 호가 이력이 없어 ADV 구간(1·3·10bp)으로 근사한다 — TCA 실측이 쌓이면 대체할 자리다.
늘리는 금액은 ADV의 5%(`max_adv_participation`)를 넘지 못한다. 매도는 이 한도로 묶지 않는다.
paper/live는 비용 재료(거래량·변동성)가 없으면 fail-closed한다. 실행 원장에 같은 종목 체결이
5건 이상 쌓이면 승인 기준가 대비 평균 체결가·수수료로 잰 편도 비용 중앙값이 추정 반스프레드보다
클 때만 그 값으로 **올린다**(`calibrate_trading_costs`) — 몇 건의 유리한 체결로 비용을 낮춰 잡으면
회전이 늘어난 손해가 나중에 드러난다. 포트폴리오 시장 베타는 RiskGate의 사후 검사와 같은 상한
(`max_abs_beta`)을 optimizer 제약으로도 건다. 미분석 보유가 이미 상한을 넘기면 신호 종목은 베타를
지금보다 늘리지 못한다. 총합 1, long-only, 종목·섹터 최대, 현금 최소와 turnover 최대를 명시적
constraint로 사용한다. 실전 경로(`construct.py`)는 PIT 가격 260일의 Ledoit-Wolf 수축 공분산을
넣고, covariance가 없으면 risk score 기반의 보수적 diagonal 근사를 metadata에 표시한다.

종목 의견의 **행동**은 기대수익과 별개로 비중의 방향을 강제한다.

| action | optimizer 제약 | 이유 |
|---|---|---|
| `exit` | 비중 = 0 | 전량 청산 명령. 기대수익만 낮추면 turnover 벌점이 잔량을 남긴다 |
| `reduce`·`avoid`·`watch` | 비중 ≤ 현재 | 늘리지 못하게만 막고 얼마나 줄일지는 optimizer가 정한다 |
| `open`·`increase`·`hold` | 없음 | 의견이다. 자금이 한정돼 있어 더 나은 후보에 밀려 0이 될 수 있어야 한다 |

turnover 최대는 **재량 매매**에만 건다. `exit` 청산과 종목 상한 초과분의 현금화를 먼저 반영한
출발점에서 turnover를 잰다. 그렇지 않으면 여러 종목을 한꺼번에 빼야 하는 날 한도가 위험 축소를
막는다(optimizer는 infeasible, RiskGate는 잘라 둔 비중을 도로 살린다).

## DeterministicRiskGate

optimizer 결과도 반드시 RiskGate를 통과한다.

- 종목·섹터 비중, 최대 position 수와 최소 position
- 최소 cash와 최대 turnover(청산·상한 준수분을 뺀 재량 turnover, 축소는 그 출발점 쪽으로)
- `exit` 의견을 받은 보유가 남아 있으면 거부
- volatility, beta, concentration/HHI와 최대 pairwise correlation
- stale proposal

주문 notional·daily loss·drawdown·stale quote·market session은 RiskGate가 아니라 실행 단계
(`execution/orders/live_worker.py`, `execution/safety/control.py`)가 주문 직전에 검사한다.
### Regime 위험 예산

`trading/risk/regime_budget.py`가 판단 시점까지의 SPY 일봉(20일 수익률·20일 실현 변동성·252일
고점 대비 낙폭)으로 regime을 정하고, 기본 한도를 **조이기만** 한다.

| regime | 종목 상한 | 섹터 상한 | 최소 현금 | 신규 위험 |
|---|---|---|---|---|
| RISK_ON·NORMAL | 기본 | 기본 | 기본 | 허용 |
| RISK_OFF | ×0.8 | ×0.8 | ≥15% | 허용 |
| CRISIS | ×0.5 | ×0.6 | ≥40% | 금지(어떤 종목도 현재 비중을 넘지 못함) |

조인 정책은 `portfolio-risk:<regime>` key로 원장에 따로 남는다(같은 key·version은 무시되므로).
최소 현금도 의무 출발점에 들어가, turnover 축소가 채워 둔 현금을 되돌리지 않는다. optimizer는 움직일
수 없는 미분석 보유가 허용하는 만큼만 현금을 요구하고, 나머지는 RiskGate가 비례로 현금화한다.
배율은 초기값이며 쌓이는 stress 지표 분포로 다시 보정한다.

RiskDecision 원장의 market risk 기록에는 평소 변동성과 따로 꼬리 위험(`stress`)이 남는다 —
5거래일 historical CVaR95, 최근 창의 최악 5·20거래일 손실, 시장 -10% 충격 시 베타 손실.
분포가 쌓이기 전이라 아직 한도가 아니라 기록이다.

주문 직전 거래 상태는 셋이다(`execution/safety/control.py`).

| 상태 | 조건 | 허용 |
|---|---|---|
| `ACTIVE` | 정상 | 매수·매도 |
| `REDUCING` | 당일 손실 또는 drawdown 한도 도달 | 보유 수량 이하를 파는 매도만 |
| `HALTED` | 실주문 꺼짐·kill switch·durable lockdown | 없음 |

손실 한도가 매도까지 막으면 탈출구가 닫힌다. 보유 수량을 모르는 매도는 줄인다고 증명할 수
없어 늘리는 주문으로 본다. REDUCING인데 주문표에 매수가 섞여 있으면 매도만 골라 내보내지
않고 승인을 소비하기 전에 멈춘다. 원장에 결과가 확정되지 않은 주문(`planned`·`submitted`·
`partially_filled`·`outcome_unknown`·`reconciling`)이 하나라도 있으면 재시작 직후를 포함해
새 실주문을 내지 않는다.

새 live intent가 저장되면, 아직 주문이 하나도 나가지 않은 이전 승인 대기 intent는 `cancelled`
(`superseded_by`)로 닫힌다. 시간이 지나서가 아니라 더 새로운 판단이 대체했기 때문이다. 이미 주문이
나간 intent는 건드리지 않는다 — 미체결 취소는 운영자 승인이 필요한 별도 동작이고, 미체결이 있는 동안
새 포트폴리오 구성 자체가 막힌다.

보유를 줄이는 매도가 주문 한도(`max_order_notional`)를 넘으면 한도 이하 자식 주문 여러 건으로 계획
단계에서 나눈다. 전부 승인 카드에 보이므로 승인한 것과 나가는 것이 같고, 총액 한도는 그대로다. 매수는
나누지 않고 거부한다. 시간 분할 TWAP은 쓰지 않는다 — 실주문 permit이 120초·주문표 1장 단위라 시간을
두고 나눠 내려면 permit 모델을 느슨하게 하거나 조각마다 승인해야 하기 때문이다.

현재 현금으로 매수를 다 댈 수 없으면 주문표는 **매도만** 담는다(`funding_phase=funding_sells`).
아직 체결되지 않은 매도대금은 현금으로 치지 않는다. 매수 일부만 고르지 않는 이유는, 무엇을
살지는 분석 순서가 아니라 optimizer가 실제 현금으로 다시 정해야 하기 때문이다.

한 signal batch는 원칙적으로 실행을 한 번만 한다. 예외는 하나다 — 직전 주문표가 `funding_sells`였고
그 주문이 모두 종결(체결·취소·거부)됐으면, 같은 batch로 **한 번 더** 포트폴리오를 구성한다
(`execution/db.py`의 `funding_followup_allowed`). 이때 계좌를 새로 읽어 다시 최적화하므로 부분체결로
생긴 실제 현금만 쓰고, 그 사이 가격이 움직였으면 그것도 반영된다. 후속 실행은 batch당 1회라
체결 부족 → 재매도가 같은 신호로 되풀이되지 않는다. 진입 재판단(entry review)이 이미 만료됐으면
실행 단계의 진입 가격 검사가 막고, 매수는 다음 batch로 넘어간다.

문서의 기본값은 설명용이며 실제 SSOT는 `OptimizerPolicy`와 `PortfolioRiskPolicy` 코드다.
LLM prompt나 문서 수정으로 완화할 수 없다.

| 제한 | V1 기본 설명값 |
|---|---:|
| 종목 최대 | 10% |
| 섹터 최대 | 30% |
| turnover 최대 | 25% |
| 현금 최소 | 5% |
| 최대 종목 수 | 25 |
| 최소 position | 0.5% |
| proposal age | 36시간 |
| 연환산 volatility | 30% |
| absolute beta | 1.5 |

Paper/Live에서 필수 market-risk 입력이 없으면 fail-closed한다.

## Partial universe와 Full portfolio

하루에 5종목만 분석했다면 그 결과는 `partial_universe`이지 전체 계좌 목표가 아니다.

```text
partial SignalBatch
+ fresh AccountSnapshot
+ 유효한 과거 SignalBook records
→ PortfolioConstructor
→ full_portfolio
→ RiskGate
```

미분석 보유는 유지하고 명시적 exit/reduce만 줄인다. 현재 universe에서 빠진 기존 보유는 추가
매수할 수 없지만 위험을 줄이는 매도는 허용할 수 있다.

## Native Backtest

`WeightBacktestEngine`은 실행 중 DB나 인터넷을 조회하지 않고 완전한 `BacktestRequest`만 소비한다.

- t 종가 뒤 생성한 `WeightPoint`
- 다음 실제 session인 t+1 시가 체결
- PIT universe snapshot과 OHLCV
- commission, minimum fee, slippage와 sell fee
- split/dividend corporate action
- order/fill/cash/position/NAV append-only ledger

월요일 종가로 판단했다면 월요일 종가에 체결하지 않는다. 화요일이 휴장이면 다음 실제 session
시가를 사용한다. effective session이 틀리면 engine이 거절한다.

metric은 Total Return, CAGR, Sharpe, Sortino, Max Drawdown, volatility, turnover, win rate,
exposure, transaction cost와 trade count다.

```powershell
python -m investment_agent.research.backtest.cli --input <INPUT.json> --output <OUTPUT.json>
```

## LumiBot 외부 검증

`LumiBotValidationEngine`은 Native와 같은 bars, weights, corporate actions, calendar와 cost model을
사용한다. 공통 input manifest hash가 다르면 비교하지 않는다. metric별 tolerance를 넘으면
`is_compatible=false`로 표시하며 차이를 평균 내거나 숨기지 않는다.

adapter와 comparator 단위 테스트 통과는 장기간 실제 LumiBot run이 완료됐다는 뜻이 아니다.
실제 실행 가능 여부는 `LIVE_ENABLED`·`TOSS_LIVE_ENABLED` 상태와
[실행과 안전](EXECUTION_AND_SAFETY.md)의 단계 정의가 정한다.

## 평가와 승격 근거

| 평가 | 용도 |
|---|---|
| In-sample | 학습 적합 여부; 단독 승격 금지 |
| Validation | parameter 선택; OOS로 간주 금지 |
| Out-of-sample | 보지 않은 기간 성능; 필수 |
| Walk-forward | 여러 시장 구간 반복; 필수 |
| Regime | 상승·하락·고변동 취약성 |
| Benchmark | SPY 등 명시 benchmark 대비 |
| Paper | 실제 latency·주문·정산; Live 승격 필수 |

평균 하나가 나쁜 window를 가리지 않도록 최저 excess return, 최악 drawdown과 최대 turnover를
보수적으로 집계한다.

## 실행 예

```powershell
# Supabase context만 확인; LLM/provider/broker 호출 없음
python -m investment_agent.trading.decision.portfolio_shadow --ticker AAPL --dry-run

# 현재 주 TradingAgents Shadow 경로
python -m investment_agent.trading.decision.portfolio_shadow --ticker AAPL --limit 1
```

live candidate entry에 오래된 `--as-of`를 억지로 넣어 historical replay처럼 사용하지 않는다.
역사 분석은 versioned feature와 backtest workflow를 사용한다.
