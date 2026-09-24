"""PORTFOLIO: ALPHA 결과를 System Portfolio에서 몇 % 보유할지 정한다.

입력은 System 자신의 현재 비중뿐이다. 실계좌·승인 결과를 받는 인자가 없다 — 사람이 무엇을 골랐든
System의 목표비중은 같아야 System 성과가 "프로그램을 100% 따랐다면"을 말한다.

```
현재 System 비중 ┐
factor 횡단면     │
champion ML 예측  ├→ ALPHA(기대초과수익·confidence·제약) → 위험예산 → optimizer → no-trade band
최신 논지          ┘                                        → 꼬리위험 축소 → RiskGate → 목표비중
```

- 꼬리위험(5일 CVaR95)·변동성이 한도를 넘으면 목표를 버리지 않고 위험자산 전체를 같은 비율로 줄여 현금을
  늘린다. 어떤 종목을 담을지는 바꾸지 않는다.

- 공분산·비용·베타·스트레스 재료가 없으면 `ContractError`다. 모르는 채 기본값으로 목표를 만들면 실계좌가
  할 수 없는 판단이 System 성과에 섞인다. 엔진은 그날 목표를 갱신하지 않고 이전 목표를 유지한다.
- 거래비용 추정은 가격 이력만 쓴다. 실계좌 체결 비용으로 보정하면 사람의 주문이 System 판단에 들어온다.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any, Mapping, Sequence

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import stable_id
from investment_agent.research.adapters.trading import NO_FORECAST, ChampionForecast
from investment_agent.trading.contracts import ContractError
from investment_agent.trading.decision.alpha import AlphaPlan, AlphaPolicy, alpha_universe, expected_return_signals
from investment_agent.forecasting import SIGNAL_HORIZON_DAYS
from investment_agent.trading.portfolio.contracts import PortfolioProposal, RiskDecision
from investment_agent.portfolio_weights import CASH_SYMBOL, validated_weights
from investment_agent.trading.portfolio.market_risk import (
    calculate_market_covariance,
    calculate_market_risk,
    estimate_betas,
    estimate_trading_costs,
    redundant_symbols,
)
from investment_agent.trading.portfolio.optimizer import (
    CONSTRAINT_BLOCK_INCREASE,
    CONSTRAINT_FORCE_EXIT,
    ExpectedReturnSignal,
    FactorExposureLimit,
    OptimizerPolicy,
    RiskAwareOptimizer,
    mandatory_base_weights,
)
from investment_agent.trading.risk.budget import BENCHMARK_SYMBOL, risk_budget
from investment_agent.trading.risk.gate import DeterministicRiskGate, PortfolioRiskPolicy
from investment_agent.trading.risk.regime_budget import DEFAULT_MARKET_RISK_POLICY, MarketRiskPolicy
from investment_agent.trading.risk.stress import STRESS_PROXIES, scenario_sensitivities

log = get_logger(__name__)

SYSTEM_TARGET_VERSION = "system-target-v6"
_PRICE_ROWS = 260
# 보유하지 않은 후보는 벤치마크와 같은 창을 거의 다 채워야 한다(연휴·정지 며칠만 허용).
_HISTORY_SLACK_ROWS = 5
_WEIGHT_EPSILON = 1e-6


@dataclass(frozen=True)
class SystemPortfolioPolicy:
    """숫자는 초기값이고 System 성과·IC 연구로 다시 정한다."""

    version: str = SYSTEM_TARGET_VERSION
    # 비중 차이가 이보다 작으면 거래하지 않는다. 20일 기대수익 크기에서 L1 회전율 벌점은 모든 거래를 막는다.
    no_trade_band: float = 0.01
    rebalance_days: int = 7
    # 현금이 위험 예산(최소 현금)보다 이만큼 넘게 남으면 재조정 주기를 기다리지 않는다. 전액 현금에서 출발하면
    # turnover 한도(재조정당 0.25) 때문에 한 번에 약 25%씩만 채우는데, 주 1회면 채우는 데 한 달이 걸린다.
    # 한도는 그대로 두고 채우는 간격만 줄인다. 위기 구간의 현금은 예산 자체가 높아 걸리지 않는다.
    deploy_cash_gap: float = 0.20
    # 보유 비중 가중평균 category 점수(0~1, 중립 0.5)의 범위. 품질은 평균보다 나빠지지 않게 하고,
    # 모멘텀·가치는 한쪽으로 쏠린 단일 factor 베팅이 되지 않게 묶는다.
    min_quality_exposure: float = 0.55
    max_momentum_exposure: float = 0.80
    max_value_exposure: float = 0.80
    # 5거래일 역사적 CVaR95 상한. 넘으면 위험자산 전체를 줄인다. 연구에서 0.05~0.12를 비교할 정책값이다.
    max_cvar_95_5d: float = 0.08
    market_risk_policy: MarketRiskPolicy = DEFAULT_MARKET_RISK_POLICY
    # Ablation 스위치. 운영 기본값은 둘 다 켜짐이다.
    use_tail_risk: bool = True
    use_market_risk: bool = True
    # 위험을 SPY 대비(active)로 잰다. 끄면 절대 분산 — 기대수익이 SPY 대비 초과수익인데 대안이 현금이라
    # 주식 위험 프리미엄이 목적함수에 없고 현금으로 치우친다(설계 §9.2, Master P0-8). 5년 재현에서 채택
    # 기준을 모두 통과해 운영 기본값이다(끄면 평균 현금 60%, 켜면 15%).
    benchmark_relative_risk: bool = True
    # optimizer가 최대 종목 수를 알게 한다(상위 종목만으로 다시 푼다). 끄면 게이트가 사후에 가장 작은 비중을
    # 현금으로 돌린다 — 재현 비교용 스위치다.
    cardinality_aware: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.no_trade_band < 0.2 or self.rebalance_days < 1:
            raise ValueError("no_trade_band must be in [0, 0.2) and rebalance_days positive")
        if not 0 < self.max_cvar_95_5d <= 1:
            raise ValueError("max_cvar_95_5d must be in (0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "market_risk_policy": self.market_risk_policy.to_dict()}

    def exposure_limits(self, scores: Mapping[str, Any]) -> dict[str, FactorExposureLimit]:
        def loadings(category: str) -> dict[str, float]:
            return {ticker: float(score.category_scores[category]) for ticker, score in scores.items()
                    if category in score.category_scores}

        return {
            "quality": FactorExposureLimit(loadings("quality"), minimum=self.min_quality_exposure),
            "momentum": FactorExposureLimit(loadings("momentum"), maximum=self.max_momentum_exposure),
            "value": FactorExposureLimit(loadings("value"), maximum=self.max_value_exposure),
        }


@dataclass(frozen=True)
class SystemTarget:
    """저장하지 않은 목표 한 건. 엔진이 원장에 기록한다."""

    proposal: PortfolioProposal
    risk: RiskDecision
    risk_policy: PortfolioRiskPolicy
    plan: AlphaPlan


def apply_no_trade_band(
    targets: Mapping[str, float], current: Mapping[str, float], *, band: float,
) -> tuple[dict[str, float], list[str]]:
    """비중 차이가 band보다 작은 종목은 현재 비중을 유지한다. 전량 청산은 크기와 무관하게 따른다.

    유지로 늘어난 위험 비중이 1을 넘으면 band를 적용하지 않은 원래 목표로 돌아간다 — 거래를 아끼려고
    현금 음수를 만들 수는 없다.
    """
    symbols = (set(targets) | set(current)) - {CASH_SYMBOL}
    output: dict[str, float] = {}
    kept: list[str] = []
    for symbol in sorted(symbols):
        target = float(targets.get(symbol, 0.0))
        now = float(current.get(symbol, 0.0))
        if target > 0 and abs(target - now) < band:
            output[symbol] = now
            if abs(target - now) > 1e-12:
                kept.append(symbol)
        else:
            output[symbol] = target
    output = {symbol: weight for symbol, weight in output.items() if weight > 0}
    risky = math.fsum(output.values())
    if risky > 1.0 + 1e-9:
        restored = {symbol: float(weight) for symbol, weight in targets.items() if symbol != CASH_SYMBOL and weight > 0}
        restored[CASH_SYMBOL] = max(0.0, 1.0 - math.fsum(restored.values()))
        return restored, []
    output[CASH_SYMBOL] = max(0.0, 1.0 - risky)
    return output, kept


# 비중이 바뀐 이유. 카드·화면이 "왜 샀나·왜 팔았나"를 설명하고, 성과 귀속이 논지 판단과 위험 규칙과
# 자금 경쟁을 나눠 볼 수 있게 한다.
REASON_HARD_RISK_LIMIT = "HARD_RISK_LIMIT"
REASON_THESIS_EXIT = "THESIS_EXIT"
REASON_ALPHA_DECAY = "ALPHA_DECAY"
REASON_REBALANCE = "REBALANCE"
REASON_ALPHA_OPPORTUNITY = "ALPHA_OPPORTUNITY"


def trade_reasons(
    signals: Sequence[ExpectedReturnSignal],
    *,
    current_weights: Mapping[str, float],
    target_weights: Mapping[str, float],
    max_symbol_weight: float,
    min_cash_weight: float,
    capped_expected_returns: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """비중이 변한 종목마다 한 가지 주 사유를 정한다. 판단은 결정적 규칙만 쓴다."""
    by_symbol = {signal.symbol: signal for signal in signals}
    current = {str(key).upper(): float(value) for key, value in current_weights.items()}
    target = {str(key).upper(): float(value) for key, value in target_weights.items()}
    base = mandatory_base_weights(
        current,
        exit_symbols=frozenset(symbol for symbol, signal in by_symbol.items() if signal.constraint == CONSTRAINT_FORCE_EXIT),
        max_symbol_weight=max_symbol_weight,
        min_cash_weight=min_cash_weight,
    )
    output: dict[str, dict[str, Any]] = {}
    for symbol in sorted((set(current) | set(target)) - {CASH_SYMBOL}):
        before, after = current.get(symbol, 0.0), target.get(symbol, 0.0)
        if abs(after - before) <= _WEIGHT_EPSILON:
            continue
        signal = by_symbol.get(symbol)
        constraint = signal.constraint if signal else None
        if after > before:
            code = REASON_ALPHA_OPPORTUNITY
        elif constraint == CONSTRAINT_FORCE_EXIT:
            code = REASON_THESIS_EXIT
        elif base.get(symbol, 0.0) < before - _WEIGHT_EPSILON and after >= base.get(symbol, 0.0) - _WEIGHT_EPSILON:
            # 종목 상한·최소 현금처럼 전망과 무관하게 줄여야 하는 몫까지만 줄였다.
            code = REASON_HARD_RISK_LIMIT
        elif constraint == CONSTRAINT_BLOCK_INCREASE:
            code = REASON_ALPHA_DECAY
        else:
            # 전망은 나쁘지 않지만 위험·비용 대비 더 나은 후보에 자리를 내줬다.
            code = REASON_REBALANCE
        output[symbol] = {
            "code": code,
            "current_weight": round(before, 6),
            "target_weight": round(after, 6),
            "constraint": constraint,
            "expected_return_capped": symbol in capped_expected_returns,
        }
    return output


def drop_short_history(
    universe: Sequence[str], rows: Mapping[str, Sequence[Mapping[str, Any]]], *, held: Sequence[str],
) -> tuple[tuple[str, ...], list[str]]:
    """벤치마크만큼의 가격 창이 없는 신규 후보를 뺀다. 보유 종목은 빼지 않는다(판단 근거 없이 팔 수 없다).

    공분산은 모든 종목이 겹치는 구간만 쓴다. 이력이 며칠뿐인 후보 하나가 목표 전체를 막았고(겹침 6일 < 60),
    막지 않을 만큼 길어도(분사 69일) 모든 종목의 추정 창을 그만큼 줄인다.
    """
    required = len(rows.get(BENCHMARK_SYMBOL) or ()) - _HISTORY_SLACK_ROWS
    held_set = set(held)
    short = sorted(symbol for symbol in universe
                   if symbol not in held_set and len(rows.get(symbol) or ()) < required)
    return tuple(symbol for symbol in universe if symbol not in short), short


def _price_rows(repository: Any, symbols: Sequence[str], as_of_at: datetime) -> dict[str, list[dict]]:
    return {symbol: repository.market_prices(symbol, as_of_at, limit=_PRICE_ROWS) for symbol in symbols}


# 한도에 딱 맞추면 부동소수 오차로 게이트가 다시 거절한다. 조금 더 줄인다.
_TAIL_SCALE_MARGIN = 0.99
_TAIL_FIT_ITERATIONS = 3


def scale_risky_weights(weights: Mapping[str, float], scale: float) -> dict[str, float]:
    """위험자산 비중을 같은 비율로 줄이고 나머지를 현금으로 둔다."""
    scaled = {symbol: float(weight) * scale for symbol, weight in weights.items() if symbol != CASH_SYMBOL and weight > 0}
    scaled[CASH_SYMBOL] = max(0.0, 1.0 - math.fsum(scaled.values()))
    return scaled


def fit_tail_risk(
    weights: Mapping[str, float],
    rows: Mapping[str, list[dict]],
    *,
    max_volatility: float,
    max_cvar_95_5d: float,
) -> tuple[dict[str, float], dict[str, Any]]:
    """변동성·5일 CVaR95가 한도 안에 들 때까지 위험자산 전체 비중을 줄인다.

    종목 선택과 종목 사이 비율은 그대로 두고 현금만 늘린다. 두 지표 모두 위험자산 비중에 거의 비례하므로
    몇 번이면 수렴한다. 한도를 넘는 판단을 통째로 버리면 위험을 줄여야 할 날 목표가 갱신되지 않는다.
    """
    current = dict(weights)
    symbols = sorted(symbol for symbol, weight in current.items() if symbol != CASH_SYMBOL and weight > 0)
    if not symbols:
        return current, {"scale": 1.0}
    subset = {symbol: rows[symbol] for symbol in (*symbols, BENCHMARK_SYMBOL)}
    before = calculate_market_risk(subset, target_weights=current)
    total_scale = 1.0
    metrics = before
    for _ in range(_TAIL_FIT_ITERATIONS):
        ratios = [1.0]
        if metrics.portfolio_volatility > max_volatility > 0:
            ratios.append(max_volatility / metrics.portfolio_volatility)
        if metrics.historical_cvar_95_5d is not None and metrics.historical_cvar_95_5d > max_cvar_95_5d:
            ratios.append(max_cvar_95_5d / metrics.historical_cvar_95_5d)
        scale = min(ratios)
        if scale >= 1.0:
            break
        scale *= _TAIL_SCALE_MARGIN
        current = scale_risky_weights(current, scale)
        total_scale *= scale
        metrics = calculate_market_risk(subset, target_weights=current)
    return current, {
        "scale": round(total_scale, 6),
        "volatility_before": before.portfolio_volatility,
        "cvar_95_5d_before": before.historical_cvar_95_5d,
        "volatility_after": metrics.portfolio_volatility,
        "cvar_95_5d_after": metrics.historical_cvar_95_5d,
        "max_volatility": max_volatility,
        "max_cvar_95_5d": max_cvar_95_5d,
    }


def _optimizer_policy_for(risk_policy: PortfolioRiskPolicy, *, fixed_weight: float) -> OptimizerPolicy:
    """optimizer에 같은 한도를 넘긴다. 최소 현금은 고정된 보유가 허용하는 만큼만 요구한다.

    고정 보유는 optimizer가 움직일 수 없어, 위험예산이 올린 최소 현금이 그보다 크면 문제가 풀리지 않는다.
    그 나머지는 RiskGate가 보유 전체를 비례로 현금화해 채운다(위험 축소 방향).
    """
    return OptimizerPolicy(
        max_symbol_weight=risk_policy.max_symbol_weight,
        max_sector_weight=risk_policy.max_sector_weight,
        max_turnover=risk_policy.max_turnover,
        min_cash_weight=min(risk_policy.min_cash_weight, max(0.0, 1.0 - fixed_weight)),
        allow_increases=risk_policy.allow_risk_increase,
        max_portfolio_beta=risk_policy.max_abs_beta,
        # 스프레드·시장충격 비용이 목적함수에 있고, 작은 조정은 no-trade band가 거른다.
        turnover_penalty=0.0,
    )


def gate_target(
    repository: Any,
    *,
    proposal: PortfolioProposal,
    current_weights: Mapping[str, float],
    decided_at: datetime,
    risk_policy: PortfolioRiskPolicy,
    regime_metadata: Mapping[str, Any],
) -> RiskDecision:
    """절대 한도 검사. 시장위험·스트레스 재료는 모두 필요하다(없으면 `ContractError`)."""
    target_symbols = sorted(symbol for symbol, weight in proposal.weights.items() if symbol != CASH_SYMBOL and weight > 0)
    held_symbols = {symbol for symbol, weight in current_weights.items() if symbol != CASH_SYMBOL and weight > 0}
    final_symbols = tuple(sorted(set(target_symbols) | held_symbols))
    rows = _price_rows(repository, (*final_symbols, BENCHMARK_SYMBOL, *STRESS_PROXIES), decided_at)
    market_risk = calculate_market_risk(
        {symbol: rows[symbol] for symbol in (*target_symbols, BENCHMARK_SYMBOL)} if target_symbols else {},
        target_weights=proposal.weights,
    )
    stress = scenario_sensitivities(rows, symbols=final_symbols)
    held = held_symbols
    def final_market_risk(weights: Mapping[str, float]):
        symbols = tuple(sorted(symbol for symbol, weight in weights.items()
                               if symbol != CASH_SYMBOL and weight > 0))
        subset = {symbol: rows[symbol] for symbol in (*symbols, BENCHMARK_SYMBOL)} if symbols else {}
        return calculate_market_risk(subset, target_weights=weights)

    return DeterministicRiskGate(risk_policy).evaluate(
        proposal,
        current_weights=current_weights,
        # 추적에서 빠진 보유도 팔 수는 있어야 한다.
        tradable_symbols=set(repository.current_tracked_tickers()) | held,
        decided_at=decided_at,
        sector_by_symbol=repository.sp500_sector_map(final_symbols),
        portfolio_volatility=market_risk.portfolio_volatility,
        portfolio_beta=market_risk.portfolio_beta,
        max_pairwise_correlation=market_risk.max_pairwise_correlation,
        drawdown_fraction=market_risk.drawdown_fraction,
        historical_cvar_95_5d=market_risk.historical_cvar_95_5d,
        stress_sensitivities=stress,
        market_risk_metadata={**market_risk.to_metadata(), **dict(regime_metadata)},
        market_risk_for_weights=final_market_risk,
    )


def build_system_target(
    repository: Any,
    *,
    current_weights: Mapping[str, float],
    as_of_at: datetime,
    scores: Mapping[str, Any],
    snapshot_as_of: str,
    run_id: str,
    model_artifact_id: str | None,
    views: Mapping[str, Any],
    alpha_policy: AlphaPolicy | None = None,
    policy: SystemPortfolioPolicy | None = None,
    ml_forecast: ChampionForecast = NO_FORECAST,
) -> SystemTarget:
    """System 현재 비중 하나에 대해 목표비중과 RiskDecision을 만든다. 아무것도 저장하지 않는다."""
    alpha = alpha_policy or AlphaPolicy()
    selected = policy or SystemPortfolioPolicy()
    current = validated_weights(current_weights)
    held = tuple(sorted(symbol for symbol, weight in current.items() if symbol != CASH_SYMBOL and weight > 0))
    universe = alpha_universe(scores, held_symbols=held, policy=alpha)
    rows = _price_rows(repository, (*universe, BENCHMARK_SYMBOL), as_of_at)
    universe, short_history = drop_short_history(universe, rows, held=held)
    if short_history:
        log.info("candidates without a full price window excluded: %s", short_history)
    # 벤치마크 대비 위험을 쓰면 SPY와의 공분산이 필요하다. 같은 수축 추정 안에서 함께 구해 두 값이 서로 맞게 한다.
    with_benchmark = selected.benchmark_relative_risk and BENCHMARK_SYMBOL not in universe
    covariance_symbols = (*universe, BENCHMARK_SYMBOL) if with_benchmark else universe
    covariance = calculate_market_covariance(
        {symbol: rows[symbol] for symbol in covariance_symbols}, symbols=covariance_symbols,
        horizon_days=SIGNAL_HORIZON_DAYS,
    )
    sigma = {symbol: math.sqrt(max(0.0, covariance.matrix[index][index]))
             for index, symbol in enumerate(covariance.symbols)}
    plan = expected_return_signals(scores, sigma_by_symbol=sigma, held_symbols=held, views=views,
                                   as_of_at=as_of_at, policy=alpha,
                                   ml_expected_returns=ml_forecast.expected_excess_returns,
                                   ml_confidence=ml_forecast.confidence if ml_forecast.is_available else 0.0)
    if not plan.signals:
        raise ContractError("system target has no alpha signals")
    signal_symbols = tuple(signal.symbol for signal in plan.signals)
    index = {symbol: position for position, symbol in enumerate(covariance.symbols)}
    matrix = [[covariance.matrix[index[row]][index[column]] for column in signal_symbols] for row in signal_symbols]
    trading_costs = estimate_trading_costs({symbol: rows[symbol] for symbol in signal_symbols}, symbols=signal_symbols)
    # 꼬리위험 스위치가 꺼진 연구 재현에서는 CVaR 한도를 사실상 두지 않는다.
    base_risk_policy = replace(PortfolioRiskPolicy(), max_cvar_95_5d=selected.max_cvar_95_5d if selected.use_tail_risk else 1.0)
    risk_policy, regime_metadata = risk_budget(
        repository, as_of_at=as_of_at, base_policy=base_risk_policy,
        market_policy=selected.market_risk_policy, use_market_risk=selected.use_market_risk,
    )
    redundant = redundant_symbols(
        rows, signal_symbols, max_correlation=risk_policy.max_pairwise_correlation,
        priority={symbol: float(scores[symbol].composite) for symbol in signal_symbols
                  if symbol in scores and scores[symbol].composite is not None},
        keep=frozenset(held),
    )
    if redundant:
        # 게이트가 목표 전체를 거절할 쌍이다. 점수가 낮은 쪽을 새로 담지 않는다(보유 중이면 그대로 둔다).
        plan = replace(plan, signals=tuple(
            replace(signal, constraint=CONSTRAINT_BLOCK_INCREASE)
            if signal.symbol in redundant and signal.constraint is None else signal
            for signal in plan.signals
        ))
    fixed = {symbol: current[symbol] for symbol in plan.fixed_symbols}
    optimizer_policy = _optimizer_policy_for(risk_policy, fixed_weight=math.fsum(fixed.values()))
    betas = estimate_betas({symbol: rows[symbol] for symbol in (*signal_symbols, *fixed, BENCHMARK_SYMBOL)},
                           symbols=tuple(sorted({*signal_symbols, *fixed})))
    benchmark_covariance = (
        {symbol: covariance.matrix[index[symbol]][index[BENCHMARK_SYMBOL]] for symbol in signal_symbols}
        if with_benchmark else None
    )
    # 움직일 수 없는 보유와 신호 종목의 공분산. 없으면 같은 방향의 종목을 더 담는 위험이 보이지 않는다.
    fixed_covariance = {
        symbol: math.fsum(covariance.matrix[index[symbol]][index[held_symbol]] * weight
                          for held_symbol, weight in fixed.items() if held_symbol in index)
        for symbol in signal_symbols
    } if fixed else None
    optimizer_inputs = dict(
        current_weights=current, covariance=matrix, sector_by_symbol=repository.sp500_sector_map(list(universe)),
        fixed_weights=fixed, trading_costs=trading_costs, betas=betas, benchmark_covariance=benchmark_covariance,
        fixed_covariance=fixed_covariance,
    )
    exposure_limits_relaxed = None

    def solve(signals: Sequence[ExpectedReturnSignal]):
        nonlocal exposure_limits_relaxed
        # optimizer는 종목을 정렬해 공분산 행과 맞춘다. 부분 행렬도 같은 순서로 만든다.
        signals = tuple(sorted(signals, key=lambda signal: signal.symbol))
        positions = [signal_symbols.index(signal.symbol) for signal in signals]
        inputs = {**optimizer_inputs, "covariance": [[matrix[row][column] for column in positions] for row in positions]}
        try:
            return RiskAwareOptimizer(optimizer_policy).optimize(
                signals, **inputs, factor_exposures=selected.exposure_limits(scores),
            )
        except ContractError as exc:
            # 품질이 낮은 기존 보유가 많고 회전율 한도가 작으면 노출 범위를 한 번에 맞출 수 없다. 노출 제약 없이
            # 풀어 위험 한도 안에서 방향을 옮기고, 그 사실을 목표에 남긴다(다음 재조정에서 다시 시도한다).
            log.warning("factor exposure limits infeasible; solving without them: %s", exc)
            exposure_limits_relaxed = str(exc)
            return RiskAwareOptimizer(optimizer_policy).optimize(signals, **inputs)

    result = solve(plan.signals)
    signals_used = plan.signals
    # 최대 종목 수는 게이트의 하드 한도다. optimizer가 그보다 많이 담으면 게이트가 가장 작은 비중을 현금으로
    # 돌린다(5년 재현 목표의 62%) — 노출이 줄고 남은 종목은 다시 배분되지 않는다. 첫 풀이의 상위 종목만으로
    # 한 번 더 풀어 같은 노출을 한도 안에서 다시 나눈다. 밀려난 보유 종목은 게이트가 어차피 팔았을 종목이다.
    slots = risk_policy.max_positions - sum(1 for weight in fixed.values() if weight > 0)
    holding = [symbol for symbol in signal_symbols if result.weights.get(symbol, 0.0) > _WEIGHT_EPSILON]
    max_positions_trimmed: list[str] = []
    if selected.cardinality_aware and 0 < slots < len(holding):
        keep = set(sorted(holding, key=lambda symbol: (-result.weights[symbol], symbol))[:slots])
        max_positions_trimmed = sorted(set(holding) - keep)
        signals_used = tuple(
            signal if signal.symbol in keep else replace(signal, constraint=CONSTRAINT_FORCE_EXIT)
            for signal in plan.signals
            if signal.symbol in keep or current.get(signal.symbol, 0.0) > 0
        )
        result = solve(signals_used)
    weights, banded = apply_no_trade_band(result.weights, current, band=selected.no_trade_band)
    tail_risk: dict[str, Any] = {"scale": 1.0, "enabled": selected.use_tail_risk}
    if selected.use_tail_risk:
        missing = sorted(symbol for symbol, weight in weights.items()
                         if symbol != CASH_SYMBOL and weight > 0 and symbol not in rows)
        weights, fitted = fit_tail_risk(weights, {**rows, **_price_rows(repository, missing, as_of_at)},
                                        max_volatility=risk_policy.max_portfolio_volatility,
                                        max_cvar_95_5d=risk_policy.cvar_95_5d_limit)
        tail_risk.update(fitted)
    proposal = PortfolioProposal.create(
        run_id=run_id, source_type="optimizer", source_version=selected.version, stage="shadow",
        as_of_at=as_of_at.isoformat(), weights=weights, confidence=1.0,
        reasoning=(
            "factor 사전값(IC×σ×z)과 champion ML 예측으로 기대초과수익을 만들고 TradingAgents 논지는 거부권·소폭 조정으로만 반영",
            "cvxpy optimizer가 비중을 정하고 no-trade band 안의 조정은 생략, 꼬리위험 초과분은 현금으로",
        ),
        model_artifact_id=model_artifact_id,
        metadata={
            "coverage": "full_portfolio",
            "factor_snapshot_as_of": snapshot_as_of,
            "alpha_policy": alpha.to_dict(),
            "system_policy": selected.to_dict(),
            "alpha_signals": dict(plan.detail),
            "alpha_reasons": dict(plan.reasons),
            "forced_exits": list(plan.forced_exits),
            "trade_reasons": {
                symbol: ({**reason, "code": REASON_HARD_RISK_LIMIT} if symbol in max_positions_trimmed else reason)
                for symbol, reason in trade_reasons(
                    signals_used, current_weights=current, target_weights=weights,
                    max_symbol_weight=optimizer_policy.max_symbol_weight,
                    min_cash_weight=optimizer_policy.min_cash_weight,
                    capped_expected_returns=result.capped_expected_returns or {},
                ).items()
            },
            "max_positions_trimmed": max_positions_trimmed,
            "no_trade_band_kept": banded,
            "tail_risk": tail_risk,
            "ml_forecast": ml_forecast.to_metadata(),
            "exposure_limits_relaxed": exposure_limits_relaxed,
            "redundant_exposure_blocked": redundant,
            "short_history_excluded": short_history,
            "optimizer": {
                "policy_hash": optimizer_policy.hash, "input_hash": result.input_hash,
                "expected_return": result.expected_return, "estimated_variance": result.estimated_variance,
                "transaction_cost": result.transaction_cost,
                "capped_expected_returns": result.capped_expected_returns or {},
                "covariance": covariance.to_metadata(),
            },
            **regime_metadata,
        },
    )
    risk = gate_target(repository, proposal=proposal, current_weights=current, decided_at=as_of_at,
                       risk_policy=risk_policy, regime_metadata=regime_metadata)
    return SystemTarget(proposal=proposal, risk=risk, risk_policy=risk_policy, plan=plan)


def system_model_artifact(*, alpha_policy: AlphaPolicy, policy: SystemPortfolioPolicy,
                          view_artifact_ids: Sequence[str], ml_artifact_id: str | None = None) -> dict[str, Any]:
    """System 목표를 만든 조합의 정체성. 모델·규칙이 바뀌면 새 artifact가 되고, 실계좌 추종은 그 승격을 요구한다."""
    params = {
        "system_version": policy.version,
        "alpha_policy": alpha_policy.to_dict(),
        "system_policy": policy.to_dict(),
        "thesis_model_artifact_ids": sorted(set(view_artifact_ids)),
        "champion_ml_artifact_id": ml_artifact_id,
    }
    return {"artifact_id": stable_id("artifact", params), "params": params}


__all__ = [
    "REASON_ALPHA_DECAY",
    "REASON_ALPHA_OPPORTUNITY",
    "REASON_HARD_RISK_LIMIT",
    "REASON_REBALANCE",
    "REASON_THESIS_EXIT",
    "SYSTEM_TARGET_VERSION",
    "SystemPortfolioPolicy",
    "SystemTarget",
    "apply_no_trade_band",
    "build_system_target",
    "fit_tail_risk",
    "gate_target",
    "scale_risky_weights",
    "system_model_artifact",
    "trade_reasons",
]
