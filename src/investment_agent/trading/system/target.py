"""PORTFOLIO: ALPHA 결과를 System Portfolio에서 몇 % 보유할지 정한다.

입력은 System 자신의 현재 비중뿐이다. 실계좌·승인 결과를 받는 인자가 없다 — 사람이 무엇을 골랐든
System의 목표비중은 같아야 System 성과가 "프로그램을 100% 따랐다면"을 말한다.

```
현재 System 비중 ┐
factor 횡단면     ├→ ALPHA(기대수익·제약) → 위험예산 → optimizer → no-trade band → RiskGate → 목표비중
최신 논지          ┘
```

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
from investment_agent.trading.contracts import ContractError
from investment_agent.trading.decision.alpha import AlphaPlan, AlphaPolicy, alpha_universe, expected_return_signals
from investment_agent.trading.decision.constants import SIGNAL_HORIZON_DAYS
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL, PortfolioProposal, RiskDecision, validated_weights
from investment_agent.trading.portfolio.market_risk import (
    calculate_market_covariance,
    calculate_market_risk,
    estimate_betas,
    estimate_trading_costs,
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
from investment_agent.trading.risk.stress import STRESS_PROXIES, scenario_sensitivities

log = get_logger(__name__)

SYSTEM_TARGET_VERSION = "system-target-v1"
_PRICE_ROWS = 260
_WEIGHT_EPSILON = 1e-6


@dataclass(frozen=True)
class SystemPortfolioPolicy:
    """숫자는 초기값이고 System 성과·IC 연구로 다시 정한다."""

    version: str = SYSTEM_TARGET_VERSION
    # 비중 차이가 이보다 작으면 거래하지 않는다. 20일 기대수익 크기에서 L1 회전율 벌점은 모든 거래를 막는다.
    no_trade_band: float = 0.01
    rebalance_days: int = 7
    # 보유 비중 가중평균 category 점수(0~1, 중립 0.5)의 범위. 품질은 평균보다 나빠지지 않게 하고,
    # 모멘텀·가치는 한쪽으로 쏠린 단일 factor 베팅이 되지 않게 묶는다.
    min_quality_exposure: float = 0.55
    max_momentum_exposure: float = 0.80
    max_value_exposure: float = 0.80
    # 시장충격·ADV 참여 한도를 계산할 기준 규모(USD). 따라가는 실계좌 규모에 맞춘다.
    reference_portfolio_value: float = 5_000.0

    def __post_init__(self) -> None:
        if not 0 <= self.no_trade_band < 0.2 or self.rebalance_days < 1:
            raise ValueError("no_trade_band must be in [0, 0.2) and rebalance_days positive")
        if not math.isfinite(self.reference_portfolio_value) or self.reference_portfolio_value <= 0:
            raise ValueError("reference_portfolio_value must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

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


def _price_rows(repository: Any, symbols: Sequence[str], as_of_at: datetime) -> dict[str, list[dict]]:
    return {symbol: repository.market_prices(symbol, as_of_at, limit=_PRICE_ROWS) for symbol in symbols}


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
    rows = _price_rows(repository, (*target_symbols, BENCHMARK_SYMBOL, *STRESS_PROXIES), decided_at)
    market_risk = calculate_market_risk(
        {symbol: rows[symbol] for symbol in (*target_symbols, BENCHMARK_SYMBOL)} if target_symbols else {},
        target_weights=proposal.weights,
    )
    stress = scenario_sensitivities(rows, symbols=tuple(target_symbols))
    held = {symbol for symbol, weight in current_weights.items() if symbol != CASH_SYMBOL and weight > 0}
    return DeterministicRiskGate(risk_policy).evaluate(
        proposal,
        current_weights=current_weights,
        # 추적에서 빠진 보유도 팔 수는 있어야 한다.
        tradable_symbols=set(repository.current_tracked_tickers()) | held,
        decided_at=decided_at,
        sector_by_symbol=repository.sp500_sector_map(target_symbols),
        portfolio_volatility=market_risk.portfolio_volatility,
        portfolio_beta=market_risk.portfolio_beta,
        max_pairwise_correlation=market_risk.max_pairwise_correlation,
        drawdown_fraction=market_risk.drawdown_fraction,
        historical_cvar_95_5d=market_risk.historical_cvar_95_5d,
        stress_sensitivities=stress,
        market_risk_metadata={**market_risk.to_metadata(), **dict(regime_metadata)},
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
) -> SystemTarget:
    """System 현재 비중 하나에 대해 목표비중과 RiskDecision을 만든다. 아무것도 저장하지 않는다."""
    alpha = alpha_policy or AlphaPolicy()
    selected = policy or SystemPortfolioPolicy()
    current = validated_weights(current_weights)
    held = tuple(sorted(symbol for symbol, weight in current.items() if symbol != CASH_SYMBOL and weight > 0))
    universe = alpha_universe(scores, held_symbols=held, policy=alpha)
    rows = _price_rows(repository, (*universe, BENCHMARK_SYMBOL), as_of_at)
    covariance = calculate_market_covariance(
        {symbol: rows[symbol] for symbol in universe}, symbols=universe, horizon_days=SIGNAL_HORIZON_DAYS,
    )
    sigma = {symbol: math.sqrt(max(0.0, covariance.matrix[index][index]))
             for index, symbol in enumerate(covariance.symbols)}
    plan = expected_return_signals(scores, sigma_by_symbol=sigma, held_symbols=held, views=views,
                                   as_of_at=as_of_at, policy=alpha)
    if not plan.signals:
        raise ContractError("system target has no alpha signals")
    signal_symbols = tuple(signal.symbol for signal in plan.signals)
    index = {symbol: position for position, symbol in enumerate(covariance.symbols)}
    matrix = [[covariance.matrix[index[row]][index[column]] for column in signal_symbols] for row in signal_symbols]
    trading_costs = estimate_trading_costs({symbol: rows[symbol] for symbol in signal_symbols}, symbols=signal_symbols)
    risk_policy, regime_metadata = risk_budget(repository, as_of_at=as_of_at)
    fixed = {symbol: current[symbol] for symbol in plan.fixed_symbols}
    optimizer_policy = _optimizer_policy_for(risk_policy, fixed_weight=math.fsum(fixed.values()))
    betas = estimate_betas({symbol: rows[symbol] for symbol in (*signal_symbols, *fixed, BENCHMARK_SYMBOL)},
                           symbols=tuple(sorted({*signal_symbols, *fixed})))
    optimizer_inputs = dict(
        current_weights=current, covariance=matrix, sector_by_symbol=repository.sp500_sector_map(list(universe)),
        fixed_weights=fixed, trading_costs=trading_costs, portfolio_value=selected.reference_portfolio_value,
        betas=betas,
    )
    exposure_limits_relaxed = None
    try:
        result = RiskAwareOptimizer(optimizer_policy).optimize(
            plan.signals, **optimizer_inputs, factor_exposures=selected.exposure_limits(scores),
        )
    except ContractError as exc:
        # 품질이 낮은 기존 보유가 많고 회전율 한도가 작으면 노출 범위를 한 번에 맞출 수 없다. 노출 제약 없이
        # 풀어 위험 한도 안에서 방향을 옮기고, 그 사실을 목표에 남긴다(다음 재조정에서 다시 시도한다).
        log.warning("factor exposure limits infeasible; solving without them: %s", exc)
        exposure_limits_relaxed = str(exc)
        result = RiskAwareOptimizer(optimizer_policy).optimize(plan.signals, **optimizer_inputs)
    weights, banded = apply_no_trade_band(result.weights, current, band=selected.no_trade_band)
    proposal = PortfolioProposal.create(
        run_id=run_id, source_type="optimizer", source_version=selected.version, stage="shadow",
        as_of_at=as_of_at.isoformat(), weights=weights, confidence=1.0,
        reasoning=(
            "factor 종합 점수로 기대수익(IC×σ×z)을 만들고 TradingAgents 논지는 거부권·소폭 조정으로만 반영",
            "cvxpy optimizer가 비중을 정하고 no-trade band 안의 조정은 생략",
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
            "trade_reasons": trade_reasons(
                plan.signals, current_weights=current, target_weights=weights,
                max_symbol_weight=optimizer_policy.max_symbol_weight, min_cash_weight=optimizer_policy.min_cash_weight,
                capped_expected_returns=result.capped_expected_returns or {},
            ),
            "no_trade_band_kept": banded,
            "exposure_limits_relaxed": exposure_limits_relaxed,
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
                          view_artifact_ids: Sequence[str]) -> dict[str, Any]:
    """System 목표를 만든 조합의 정체성. 모델·규칙이 바뀌면 새 artifact가 되고, 실계좌 추종은 그 승격을 요구한다."""
    params = {
        "system_version": policy.version,
        "alpha_policy": alpha_policy.to_dict(),
        "system_policy": policy.to_dict(),
        "thesis_model_artifact_ids": sorted(set(view_artifact_ids)),
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
    "gate_target",
    "system_model_artifact",
    "trade_reasons",
]
