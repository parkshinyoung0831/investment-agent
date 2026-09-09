# Trading — 근거에서 포트폴리오까지의 판단 계층

`investment_agent.trading`는 구조화된 투자 근거를 분석 신호로 바꾸고, 그 신호를 포트폴리오와 검증 가능한
위험 결정으로 변환하는 계층입니다. 증권사 credential을 갖거나 주문 API를 호출하지 않습니다.

상위 불변 규칙은 [CONSTITUTION.md](CONSTITUTION.md)가 갖습니다.

## 이 package의 책임

```text
tracked universe
  ↓
candidate_ranker                 분석 순서를 정함. 매수 순위가 아님
  ↓
ContextBuilder
  ↓
EvidenceBundle                  cutoff 시점에 볼 수 있었던 구조화 근거
  ↓
FeatureLayer / TradingAgents / ML / RL
  ↓
ExpectedReturnSignal            expected return, confidence, risk, horizon
  ↓
RiskAwareOptimizer              CVXPY가 전체 목표 비중 계산
  ↓
PortfolioProposal              CASH 포함 합계 1
  ↓
DeterministicRiskGate
  ↓
RiskDecision
  ↓
ExecutionIntent                이 지점부터 `investment_agent.execution`이 소유
```

## 하지 않는 일

- broker key, 계좌 비밀번호, OAuth token 저장
- 주문 제출·취소·체결 조회
- LLM이 지정한 비중을 그대로 최종 목표 비중으로 채택
- current macro/fundamentals를 과거 시점 데이터로 위장
- historical replay에서 현재 뉴스 API나 DuckDB live cache 사용
- 자동 모델 승격 또는 kill switch 해제

## 핵심 계약

| 계약 | 정의 | 의미 |
|---|---|---|
| `EvidenceItem` | `contracts.py` | domain별 payload와 observed/available time, source, stable ID |
| `EvidenceBundle` | `contracts.py` | 하나의 ticker·cutoff·source kind에 대한 근거와 결측 목록 |
| `FeatureBundle` | `feature_layer.py` | 학습과 inference가 공유하는 feature version/hash |
| `FeatureSnapshot` | `rl/contracts.py` | 저장 가능한 종목×시점 feature row |
| `SecurityProposal` | `portfolio/contracts.py` | LLM의 종목별 정성 판단. 주문 권한 없음 |
| `ExpectedReturnSignal` | `portfolio/optimizer.py` | ML/RL/LLM 공통 수익·신뢰·위험 신호 |
| `SignalBatch` | `portfolio/signal_book.py` | 요청·성공·실패 종목과 artifact가 고정된 분석 batch |
| `PortfolioProposal` | `portfolio/contracts.py` | optimizer 또는 전략이 만든 CASH 포함 목표 비중 |
| `RiskDecision` | 같은 파일 | policy/input hash와 승인 또는 위반 결과 |
| `ExecutionIntent` | `src/investment_agent/execution/intents.py` | paper/live 실행 계층으로 넘길 수 있는 유일한 의도 |

모든 저장 ID는 가능한 범위에서 canonical JSON의 SHA-256으로 안정적으로 만듭니다. 같은 입력을
재시도할 때 다른 주문 의도나 평가 대상으로 보이지 않게 하기 위해서입니다.

## 1. Universe와 후보 선정

현재 live/Shadow 신규 위험 universe는 `universe.securities.is_tracked=true`입니다. CLI에서 ticker를
직접 입력해도 이 조건을 우회하지 못합니다.

`candidate_ranker.py`는 다음 순서로 LLM 분석 후보를 고릅니다.

```text
tracked universe
→ 아직 분석하지 않았거나 가장 오래 분석한 종목 우선
→ 같은 coverage cohort에서 구조화 데이터 변화 점수
→ ticker 오름차순 tie-break
→ 실행 limit
```

시장·기술·재무·세그먼트·13F 값은 단위가 다르므로 cross-sectional percentile로 변환합니다. 결측
도메인은 0점으로 꾸미지 않고 가중치 분모에서 제외합니다. 현재 segment pipeline이 unavailable이면
segment 기여가 없는 채로 coverage multiplier가 낮아집니다.

이 점수는 “살 종목 순위”가 아니라 “Bull/Bear 분석을 먼저 받을 종목 순서”입니다. 상세 계산은
[CANDIDATE_SELECTION.md](CANDIDATE_SELECTION.md)를 봅니다.

## 2. Context와 PIT 경계

`ContextBuilder.build(ticker, as_of_at, source_kind=...)`는 각 domain repository를 호출해 bundle을
만듭니다.

| Domain | live Shadow | historical replay |
|---|---|---|
| Market | cutoff 이전 ingested bar | cutoff 이전 ingested bar와 당시 universe |
| Technical | 저장된 RSI/MACD row | 저장 row만; 현재 가격 재계산 view 제외 |
| Fundamentals | `financials` 최신 원장 | `filed_at`·`available_at`·`ingested_at` cutoff를 적용한 version |
| Estimates | 실제 관측 snapshot | reconstructed row 제외 |
| Macro | 완료된 최신 market-state collection run | point-in-time 이력이 없어 historical replay에서는 제외 |
| Segment | trusted filing/metric이 있을 때만 | 현재 unavailable이면 명시적 결측 |
| Gurus | SEC accepted time 기준 | accepted/ingested cutoff 기준 |
| Economic calendar | collected/as-of 기준 | actual revision과 forecast cutoff 기준 |
| News/social | Agent의 live provider 단계 | 항상 OFF |

근거가 없으면 빈 객체나 0을 넣지 않고 `missing_data`에 사람이 읽을 수 있는 이유를 기록합니다.
`available_at > as_of_at`인 `EvidenceItem`은 계약 생성 자체가 실패합니다.

## 3. Feature layer

`FeatureLayer.build()`는 가격 수익률, technical, fundamentals, macro, 13F를 동일 정의로
`FeatureBundle`로 변환합니다. **컬럼 집합은 도메인 결측과 무관하게 항상 같습니다**
(`FEATURE_COLUMNS`) — 행마다 컬럼이 달라지면 dataset 결합 자체가 실패하기 때문입니다.
거시는 `MACRO_SERIES` allowlist 밖 series를 컬럼으로 만들지 않고, 결측은 0으로 채우지 않고
`None`으로 남긴 뒤 `<name>__is_missing` 지표를 함께 저장합니다. 학습 행렬을 만들 때만
`impute_cross_section()`이 같은 시점 종목들의 중앙값으로 대체합니다.

bundle은 다음을 함께 보존합니다.

- ticker와 `as_of_at`
- feature definition version
- 정렬된 numeric features
- 각 domain의 source/version/available time
- 결측 목록
- canonical snapshot hash

미래 return label은 feature와 별도 계약입니다. 1D·5D·20D horizon을 지원하며 label 종료 가격이
확정되기 전에는 학습에 사용할 수 없습니다. 이 분리는 같은 feature 정의를 training과 live inference가
공유하면서도 미래 수익률이 inference payload에 섞이지 않게 합니다.

## 4. TradingAgents

`agents/tradingagents_adapter.py`는 upstream TradingAgents의 도구를 이 저장소의 데이터 경계로
교체합니다.

```mermaid
flowchart TD
    subgraph ANALYSTS["Analysts (병렬 실행)"]
        MA["Market<br/>market_report"]
        FA["Fundamentals<br/>fundamentals_report"]
        NA["News<br/>news_report"]
        SA["Social<br/>sentiment_report"]
    end

    SUPA[("Supabase EvidenceBundle<br/>시장·기술·재무·거시")] --> MA
    SUPA --> FA
    EXT[("live external provider<br/>sanitize·dedupe·quota·<br/>DuckDB cache 통과")] --> NA
    EXT --> SA

    MA --> DEBATE
    FA --> DEBATE
    NA --> DEBATE
    SA --> DEBATE
    DEBATE["Bull ↔ Bear research<br/>investment_debate_state"] --> RM["Research Manager<br/>investment_plan"]
    RM --> TR["Trader<br/>trader_investment_plan"]
    TR --> RISK["risk reasoning agents<br/>risk_debate_state"]
    RISK --> FINAL["final_trade_decision"]
    FINAL --> STRUCT["TradingAgentsDecisionEngine.run()<br/>evidence_ids ∪ external manifest ID로 구조화"]
    STRUCT --> SP["structured SecurityProposal"]
```

구조화 시장·재무·거시는 Supabase bundle만 사용합니다. News/Social은 live source kind에서만 별도
provider를 호출하고 sanitize·dedupe·quota·DuckDB cache 경계를 통과합니다.

`SecurityProposal.target_weight`는 입력 계약에 남아 있지만 활성 Shadow 경로에서는 사용하지 않습니다.
`from_optimized_security_proposals()`는 `expected_excess_return`,
`confidence`, signal에서 `ExpectedReturnSignal`을 만듭니다.

`from_security_proposals()`는 독립 종목 제안을 단순 합산하는 보조 변환기입니다. active Shadow의
최종 비중은 `from_optimized_security_proposals()`가 계산하므로 두 경로를 혼동하지 않습니다.

## 5. SignalBook과 full portfolio

하루에 일부 종목만 분석한 결과는 `partial_universe`입니다. 분석하지 않은 기존 보유를 자동으로
0으로 만들 수 없으므로 그 자체로 실행 가능한 전체 포트폴리오가 아닙니다.

`SignalBook`은 batch와 종목별 TTL을 보관합니다.

- 요청한 종목, 성공 종목, 실패 종목을 분리
- signal 만료시각 기록
- batch와 model artifact 결박
- partial/failed 종목을 완료 coverage로 계산하지 않음

`src/investment_agent/trading/portfolio/construct.py`는 완료 batch와 fresh Toss
`src/investment_agent/execution/snapshots.py`의 `AccountSnapshot`을 결합합니다.
LLM의 `target_weight`는 이 경로에서 읽지 않습니다. TradingAgents의 expected return·confidence만
optimizer에 전달하고, 미분석 기존 보유는 snapshot 비중으로 고정합니다. 따라서 tracked universe
밖 기존 보유는 추가 매수하지 않으면서도 목표 포트폴리오에서 사라지지 않습니다. Paper/Live
stage에서는 해당 artifact의 수동 승격이 먼저 존재해야 합니다.

## 6. Optimizer와 RiskGate

`RiskAwareOptimizer`의 기본 목적함수는 다음 개념입니다.

```text
confidence-adjusted expected return
 - risk_aversion × portfolio variance
 - turnover_penalty × target/current difference
```

long-only, 종목 최대 10%, 섹터 최대 30%, turnover 최대 25%, 현금 최소 5%를 기본 제약으로 사용합니다.
해가 없거나 CVXPY solver가 실패하면 임의 fallback 비중을 만들지 않습니다.

`DeterministicRiskGate`는 optimizer와 별도 방어선입니다. 작은 포지션, 종목/섹터 비중, 최대 종목
수는 결정적으로 현금화할 수 있지만 다음과 같은 실행 안전 위반은 proposal 전체를 거부합니다.

- 미래 또는 오래된 proposal
- tradable universe 밖 symbol
- Paper/Live에 필요한 volatility·beta·correlation 입력 누락
- volatility, beta, correlation, concentration 절대 한도 초과
- turnover 또는 필수 sector mapping 위반

`portfolio.market_risk`는 같은 point-in-time `market.prices_daily` 이력에서 공통 거래일 수익률을
맞춘 뒤, 연율 변동성·SPY beta·최대 쌍별 상관·최대 낙폭을 계산해 Paper/Live RiskGate에 전달합니다.
가격 이력·정렬이 모자라면 수치를 추정하지 않고 RiskGate가 실행을 거부합니다.

정확한 판단·optimizer·RiskGate 흐름은
[투자 시스템](../../../docs/INVESTMENT_SYSTEM.md)을 봅니다.

## 7. Backtest, ML, RL, Qlib

- `src/investment_agent/research/backtest/`: 완전한 `BacktestRequest`만 받는 Native engine과 append-only ledger
- `src/investment_agent/research/backtest/validation.py`: LumiBot PandasData adapter와 metric comparator
- `ml/baselines.py`: Naive, Ridge, LightGBM, XGBoost 공통 train/evaluate contract
- `rl/baseline.py`: 해석 가능한 deterministic ridge policy
- `rl/trainer.py`: `FinRLTrainer`가 SB3 algorithm class를 감싼다
- `rl/experiment.py`: PPO OOS 평가가 ML baseline을 이겼는지 판정
- `qlib_adapter.py`: ResearchStore feature snapshot을 Qlib `DatasetH`와 recorder로 연결

Qlib, LumiBot, LightGBM/XGBoost, SB3는 선택 dependency입니다. import 가능한 것과 실제 장기간
성과가 검증된 것은 구분합니다.

## 8. 평가와 승격

모델 artifact에는 feature version, dataset hash, train/validation/OOS 기간, seed, parameter, code
version과 artifact hash를 저장합니다. `ManualPromotionGate`는 현재 model artifact stage의
`shadow → paper → live` 한 단계 이동을 담당합니다.

execution의 5단계 lifecycle과 model artifact의 3단계 저장 stage는 서로 다른 축입니다.

| 축 | 값 | 의미 |
|---|---|---|
| Model artifact stage | shadow → paper → live | 어떤 실행 범위에서 이 artifact를 사용할 수 있는가 |
| Operational lifecycle | backtest → shadow → paper → live_manual → live_autonomous | 시스템이 사람 승인 없이 어디까지 행동할 수 있는가 |
| Source kind | live_shadow / historical_replay | 데이터가 실제 시각인지 역사 replay인지 |

`mode` 한 필드로 이 세 개를 섞지 않습니다.

## 주요 파일

```text
src/investment_agent/trading/
  contracts.py                 Evidence와 판단 계약
  context.py                   PIT EvidenceBundle 조립
  feature_layer.py             학습/서빙 공통 feature (컬럼 고정 + 결측 지표)
  valuation.py                 PIT 밸류에이션 비율 계산 계약
  valuation_inputs.py          원천 행 -> PIT 입력 조립 (TTM 재구성)
  src/investment_agent/trading/evidence/dossier/
                              InvestmentDossier 계약·Builder·LLM renderer
  candidate_ranker.py          coverage-first 분석 후보 선정
  universe.py                  tracked universe 검증
  llm.py                       OpenAI-compatible provider
  memory.py / evaluator.py     과거 case와 성숙 결과 평가
  agents/                      TradingAgents와 vendor 경계
  research/ml_inference.py     ML baseline live 추론
  rl/                          feature/label, walk-forward, SB3 실험
  research/backtest/           Native engine와 LumiBot validation
  portfolio/                   signal book, optimizer, risk, promotion
    ensemble.py                LLM·ML·RL 제안을 한 RiskGate로 모으는 경계
  research/commands/           수동/하네스 CLI
    build_features.py          tracked universe -> FeatureSnapshot 적재
    build_labels.py            구간 종료 뒤 ForwardReturnLabel 적재
    build_valuations.py        PIT 밸류에이션 관측값 적재
    build_training_samples.py  비용 반영 학습 표본 적재
    export_dataset.py          원장 -> 학습 dataset JSON
  repository.py                trading 원장 repository
  supabase_repository.py       trading Supabase reader/writer
```

## 주요 CLI

```powershell
# PIT 밸류에이션 관측값 적재 (PER/PBR/PSR/FCF yield). feature보다 먼저 돈다
python -m investment_agent.research.commands.build_valuations --limit 5 --dry-run

# PIT feature snapshot 적재 (ML/RL 학습 dataset의 원천, LLM 미호출)
python -m investment_agent.research.commands.build_features --limit 5 --dry-run

# 미래 구간이 끝난 snapshot에만 forward return label 부착
python -m investment_agent.research.commands.build_labels --horizon 5 --dry-run

# 확정 label을 비용 반영 학습 표본으로 (왕복 수수료·슬리피지 적용)
python -m investment_agent.research.commands.build_training_samples --dry-run

# 원장을 학습용 dataset JSON으로 내보냄 (label 확정분만, 시점 내 결측 대체)
python -m investment_agent.research.commands.export_dataset --output artifacts/datasets/v2.json

# Evidence만 검증하고 LLM을 호출하지 않음
python -m investment_agent.trading.decision.portfolio_shadow --ticker AAPL --dry-run

# 현재 tracked universe에서 coverage-first Shadow 분석
python -m investment_agent.trading.decision.shadow_daily --limit 5

# 성숙한 case 평가
python -m investment_agent.research.commands.evaluate --limit 200

# SignalBook + 계좌 snapshot으로 full portfolio 구성
python -m investment_agent.trading.portfolio.construct --batch-id <BATCH_ID> --stage shadow --dry-run

# 완전한 JSON manifest로 Native backtest
python -m investment_agent.research.backtest.cli --input <INPUT.json> --output <OUTPUT.json>

# cache retention
python -m investment_agent.trading.evidence.cleanup --retention-days 90
```

승격과 intent 명령은 실제 ID와 저장된 평가 근거가 필요합니다.

```powershell
python -m investment_agent.research.promotion.cli --artifact-id <ARTIFACT_ID> --to-stage paper --approved-by owner --confirm "PROMOTE <ARTIFACT_ID> shadow->paper"

python -m investment_agent.operations.commands.create_execution_intent --risk-decision-id <RISK_DECISION_ID> --execution-mode paper --confirm <RISK_DECISION_ID>
```

## 테스트

```powershell
python -m unittest discover -s tests -t .
python -m unittest tests.investment_agent.research.features.test_layer
python -m unittest tests.investment_agent.trading.portfolio.test_optimizer
python -m unittest tests.investment_agent.research.backtest.test_validation
```

단위 테스트는 외부 provider, 실제 Supabase 쓰기, broker 계정을 호출하지 않습니다. 실제 연동은
[운영](../../../docs/OPERATIONS.md)의 절차를 따라 단계별로 진행합니다.
