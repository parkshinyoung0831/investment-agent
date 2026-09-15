"""factor 점수를 기대수익의 기반으로 두고, LLM 판단은 검증·소폭 조정으로만 쓰는 목표 포트폴리오.

## 기대수익은 factor가 만든다

LLM이 종목마다 적어 내는 기대초과수익은 크기가 제각각이고 과대하다. 여기서는 Grinold의 규칙
`기대수익 = IC × 변동성 × z`를 쓴다. z는 종합 factor 점수의 유니버스 내 순위를 표준정규 점수로 바꾼
값이고, IC는 factor 점수가 실제로 앞으로의 수익률 순위를 맞힌 정도(`research.commands.factor_research`)다.
IC가 작으면 기대수익도 작게 나와 과신이 구조적으로 막힌다.

## LLM은 논리 검증자다

- **거부권**: 유효한 LLM 판단이 하락을 말하면 비중을 늘리지 못하고(청산 판단이면 청산), 기대수익은
  factor와 LLM 중 낮은 쪽이다.
- **소폭 조정**: 둘 다 상승을 말할 때만 LLM 쪽으로 `llm_tilt_weight × 신뢰도`만큼 옮긴다. factor가 나쁘다고
  하는 종목을 LLM이 좋다고 해서 사게 되지는 않는다.
- **신규 편입은 검증 뒤**: 보유하지 않은 종목은 유효한 LLM 판단이 있어야 새로 담는다.

최종 비중은 optimizer가, 한도는 RiskGate가 정한다. LLM에게 넘기는 것은 없다.

## 짧게 사고팔지 않는다

L1 turnover 벌점을 두지 않는다 — 스프레드·시장충격 비용이 이미 목적함수에 있고, 20일 기대수익 크기에서
1% 벌점은 모든 거래를 막는다. 대신 비중 차이가 `no_trade_band`보다 작으면 거래하지 않는다.

이 목표는 가상계좌 비교용이다. 실계좌 판단 경로(`construct.evaluate_portfolio`)를 바꾸지 않는다.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from statistics import NormalDist
from typing import Any, Mapping, Sequence

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import finite_float, parse_datetime
from investment_agent.research.features.factors import percentile_ranks
from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL
from investment_agent.trading.portfolio.optimizer import (
    ACTION_EXIT,
    BUY_ACTIONS,
    ExpectedReturnSignal,
    FactorExposureLimit,
    coherent_action,
)

log = get_logger(__name__)

FACTOR_BOOK_VERSION = "factor-book-v1"
_SIGNAL_HORIZON_DAYS = 20
# 순위 끝단의 z가 무한대로 가지 않게 백분위를 자른다(±2.05σ).
_PERCENTILE_CLIP = 0.02


@dataclass(frozen=True)
class FactorBookPolicy:
    """factor 가상계좌 규칙. 숫자는 초기값이고 IC 연구·가상계좌 성과로 다시 정한다."""

    version: str = FACTOR_BOOK_VERSION
    # 월간 횡단면 IC의 보수적 초기값. 문헌의 복합 factor IC는 0.03~0.06이다.
    information_coefficient: float = 0.04
    shortlist_size: int = 40
    view_valid_days: int = 28
    llm_tilt_weight: float = 0.25
    require_verified_entry: bool = True
    no_trade_band: float = 0.01
    rebalance_days: int = 7
    # 보유 비중 가중평균 category 점수(0~1, 중립 0.5)의 범위. 품질은 평균보다 나빠지지 않게 하고,
    # 모멘텀·가치는 한쪽으로 쏠린 단일 factor 베팅이 되지 않게 묶는다.
    min_quality_exposure: float = 0.55
    max_momentum_exposure: float = 0.80
    max_value_exposure: float = 0.80

    def __post_init__(self) -> None:
        if not 0 < self.information_coefficient < 0.5:
            raise ValueError("information_coefficient must be in (0, 0.5)")
        if self.shortlist_size < 1 or self.view_valid_days < 1 or self.rebalance_days < 1:
            raise ValueError("factor book windows must be positive")
        if not 0 <= self.llm_tilt_weight <= 1 or not 0 <= self.no_trade_band < 0.2:
            raise ValueError("llm_tilt_weight must be in [0, 1] and no_trade_band in [0, 0.2)")

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
class LlmView:
    ticker: str
    as_of_at: datetime
    action: str
    expected_excess_return: float
    probability_up: float
    confidence: float

    @classmethod
    def from_decision_row(cls, ticker: str, row: Mapping[str, Any] | None) -> "LlmView | None":
        """저장된 직전 판단 한 행. 필요한 값이 하나라도 없으면 판단이 없는 것으로 본다."""
        if not row:
            return None
        decision = row.get("final_decision") or {}
        values = [finite_float(decision.get(name)) for name in ("expected_excess_return", "probability_up", "confidence")]
        if not row.get("as_of_at") or not decision.get("signal") or any(value is None for value in values):
            return None
        return cls(str(ticker).upper(), parse_datetime(str(row["as_of_at"])).astimezone(timezone.utc),
                   str(decision["signal"]), float(values[0]), float(values[1]), float(values[2]))


@dataclass(frozen=True)
class FactorSignalPlan:
    signals: tuple[ExpectedReturnSignal, ...]
    # 점수가 없어 판단 근거가 없는 보유 종목. optimizer가 움직이지 않게 고정한다.
    fixed_symbols: tuple[str, ...]
    reasons: Mapping[str, str]
    detail: Mapping[str, Mapping[str, Any]]


def _z_scores(scores: Mapping[str, Any]) -> dict[str, float]:
    ranks = percentile_ranks({ticker: score.composite for ticker, score in scores.items()})
    normal = NormalDist()
    return {
        ticker: normal.inv_cdf(min(1 - _PERCENTILE_CLIP, max(_PERCENTILE_CLIP, rank)))
        for ticker, rank in ranks.items()
    }


def factor_signals(
    scores: Mapping[str, Any],
    *,
    sigma_by_symbol: Mapping[str, float],
    held_symbols: Sequence[str],
    views: Mapping[str, LlmView | None],
    as_of_at: datetime,
    policy: FactorBookPolicy,
) -> FactorSignalPlan:
    """보유 후보 명단과 보유 종목의 optimizer 신호를 만든다. 변동성을 모르는 종목은 신호를 만들지 않는다."""
    held = {str(symbol).upper() for symbol in held_symbols}
    z_by_symbol = _z_scores(scores)
    eligible = sorted(
        (score for score in scores.values() if score.passes_quality_gate and score.composite is not None),
        key=lambda score: (-float(score.composite), score.ticker),
    )
    universe = {score.ticker for score in eligible[:policy.shortlist_size]} | held
    signals: list[ExpectedReturnSignal] = []
    fixed: list[str] = []
    reasons: dict[str, str] = {}
    detail: dict[str, dict[str, Any]] = {}
    timestamp = as_of_at.isoformat()
    for symbol in sorted(universe):
        score = scores.get(symbol)
        sigma = finite_float(sigma_by_symbol.get(symbol))
        if score is None or score.composite is None or symbol not in z_by_symbol or sigma is None or sigma <= 0:
            if symbol in held:
                fixed.append(symbol)
                reasons[symbol] = "NO_FACTOR_INPUT_HELD_FIXED"
            continue
        z = z_by_symbol[symbol]
        expected = policy.information_coefficient * sigma * z
        action = "hold" if symbol in held else "open"
        reason = "FACTOR_BASE"
        if not score.passes_quality_gate:
            expected = min(0.0, expected)
            action = "reduce"
            reason = "FACTOR_BREAKDOWN"
        view = views.get(symbol)
        is_valid_view = view is not None and timedelta(0) <= as_of_at - view.as_of_at <= timedelta(days=policy.view_valid_days)
        if is_valid_view:
            view_action, _ = coherent_action(view.action, expected_excess_return=view.expected_excess_return,
                                             probability_up=view.probability_up)
            view_return = max(-sigma, min(sigma, view.expected_excess_return))
            bearish = view.expected_excess_return < 0 and view.probability_up < 0.5
            if bearish or view_action in {ACTION_EXIT, "reduce", "avoid"}:
                expected = min(expected, view_return, 0.0) if bearish else min(expected, 0.0)
                action = ACTION_EXIT if view_action == ACTION_EXIT and symbol in held else ("reduce" if symbol in held else "avoid")
                reason = "LLM_VETO"
            elif view_action in BUY_ACTIONS | {"hold"} and expected > 0 and view.expected_excess_return > 0:
                weight = policy.llm_tilt_weight * view.confidence
                expected = expected + weight * (view_return - expected)
                reason = "LLM_CONFIRMED_TILT" if reason == "FACTOR_BASE" else reason
        elif symbol not in held and policy.require_verified_entry:
            action = "watch"
            expected = min(expected, 0.0)
            reason = "UNVERIFIED_ENTRY_BLOCKED"
        signals.append(ExpectedReturnSignal(
            symbol=symbol, expected_return=float(expected), confidence=1.0, risk_score=0.5,
            horizon_days=_SIGNAL_HORIZON_DAYS, source="factor", timestamp=timestamp,
            version=policy.version, action=action,
        ))
        reasons[symbol] = reason
        detail[symbol] = {
            "composite": round(float(score.composite), 6), "z": round(z, 4), "sigma": round(sigma, 6),
            "expected_return": round(float(expected), 6), "action": action, "reason": reason,
            "llm_view_at": view.as_of_at.isoformat() if is_valid_view else None,
        }
    return FactorSignalPlan(tuple(signals), tuple(fixed), reasons, detail)


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


def evaluate_factor_portfolio(
    repository: Any,
    *,
    snapshot: Any,
    stage: str,
    scores: Mapping[str, Any],
    snapshot_as_of: str,
    policy: FactorBookPolicy | None = None,
):
    """가상계좌 상태 하나에 대해 factor 목표 비중과 RiskDecision을 만든다. 아무것도 저장하지 않는다."""
    from investment_agent.platform.serialization import stable_id
    from investment_agent.trading.portfolio import construct
    from investment_agent.trading.portfolio.contracts import PortfolioProposal
    from investment_agent.trading.portfolio.optimizer import RiskAwareOptimizer

    if stage != "shadow":
        raise ContractError("factor portfolio is a shadow comparison book only")
    selected = policy or FactorBookPolicy()
    decision_at = parse_datetime(snapshot.captured_at)
    held = tuple(sorted(symbol for symbol in snapshot.weights if symbol != CASH_SYMBOL))
    eligible = sorted(
        (score for score in scores.values() if score.passes_quality_gate and score.composite is not None),
        key=lambda score: (-float(score.composite), score.ticker),
    )
    universe = tuple(sorted({score.ticker for score in eligible[:selected.shortlist_size]} | set(held)))
    covariance, trading_costs = construct._optimizer_market_inputs(repository, symbols=universe, as_of_at=decision_at)
    if covariance is None:
        raise ContractError("factor portfolio requires a market covariance")
    sigma = {symbol: math.sqrt(max(0.0, covariance.matrix[index][index]))
             for index, symbol in enumerate(covariance.symbols)}
    views = {symbol: LlmView.from_decision_row(symbol, repository.previous_decision(symbol, as_of_at=decision_at))
             for symbol in universe}
    plan = factor_signals(scores, sigma_by_symbol=sigma, held_symbols=held, views=views,
                          as_of_at=decision_at, policy=selected)
    if not plan.signals:
        raise ContractError("factor portfolio has no signals")
    signal_symbols = tuple(signal.symbol for signal in plan.signals)
    index = {symbol: position for position, symbol in enumerate(covariance.symbols)}
    matrix = [[covariance.matrix[index[row]][index[column]] for column in signal_symbols] for row in signal_symbols]
    risk_policy, regime_metadata = construct.risk_policy_for(repository, as_of_at=decision_at, stage=stage)
    fixed ={symbol: snapshot.weights[symbol] for symbol in plan.fixed_symbols}
    optimizer_policy = replace(
        construct._optimizer_policy_for(risk_policy, unanalyzed_weight=math.fsum(fixed.values())),
        turnover_penalty=0.0,
    )
    try:
        betas = construct._optimizer_betas(repository, symbols=signal_symbols, held_symbols=plan.fixed_symbols,
                                           as_of_at=decision_at)
    except ContractError as exc:
        log.warning("factor portfolio betas unavailable: %s", exc)
        betas = None
    sectors = repository.sp500_sector_map(list(universe))
    optimizer_inputs = dict(
        current_weights=snapshot.weights, covariance=matrix, sector_by_symbol=sectors, fixed_weights=fixed,
        trading_costs={symbol: trading_costs[symbol] for symbol in signal_symbols} if trading_costs else None,
        portfolio_value=snapshot.total_value if trading_costs else None, betas=betas,
    )
    exposure_limits_relaxed = None
    try:
        result = RiskAwareOptimizer(optimizer_policy).optimize(
            plan.signals, **optimizer_inputs, factor_exposures=selected.exposure_limits(scores),
        )
    except ContractError as exc:
        # 품질이 낮은 기존 보유가 많고 회전율 한도가 작으면 노출 범위를 한 번에 맞출 수 없다. 노출 제약 없이
        # 풀어 위험 한도 안에서 방향을 옮기고, 그 사실을 판단에 남긴다(다음 재조정에서 다시 시도한다).
        log.warning("factor exposure limits infeasible; solving without them: %s", exc)
        exposure_limits_relaxed = str(exc)
        result = RiskAwareOptimizer(optimizer_policy).optimize(plan.signals, **optimizer_inputs)
    weights, banded = apply_no_trade_band(result.weights, snapshot.weights, band=selected.no_trade_band)
    run_id = stable_id("portfolio_run", {
        "snapshot_id": snapshot.snapshot_id, "decision_at": decision_at.isoformat(),
        "source_version": selected.version, "factor_snapshot": snapshot_as_of, "stage": stage,
    })
    proposal = PortfolioProposal.create(
        run_id=run_id, source_type="optimizer", source_version=selected.version, stage=stage,
        as_of_at=decision_at.isoformat(), weights=weights, confidence=1.0,
        reasoning=(
            "factor 종합 점수로 기대수익(IC×σ×z)을 만들고 LLM 판단은 거부권·소폭 조정으로만 반영",
            "cvxpy optimizer가 비중을 정하고 no-trade band 안의 조정은 생략",
        ),
        metadata={
            "coverage": "full_portfolio",
            "factor_snapshot_as_of": snapshot_as_of,
            "factor_book_policy": selected.to_dict(),
            "factor_signals": dict(plan.detail),
            "trade_reasons": dict(plan.reasons),
            "no_trade_band_kept": banded,
            "exposure_limits_relaxed": exposure_limits_relaxed,
            "optimizer_policy_hash": optimizer_policy.hash,
            "capped_expected_returns": result.capped_expected_returns or {},
            **regime_metadata,
        },
    )
    risk = construct._gate_proposal(
        repository, proposal=proposal, snapshot=snapshot, stage=stage, decision_at=decision_at,
        risk_policy=risk_policy, tracked=repository.current_tracked_tickers(), regime_metadata=regime_metadata,
    )
    return construct.PortfolioEvaluation(
        run_id=run_id, decision_at=decision_at, active_batch_id=f"factor:{snapshot_as_of}",
        requested_symbols=universe, proposal=proposal, risk=risk, risk_policy=risk_policy,
    ), plan


def rebalance_due(*, last_decided_at: str | None, last_batch_id: str | None, snapshot_as_of: str,
                  now: datetime, policy: FactorBookPolicy) -> str | None:
    """재판단하지 않을 사유. None이면 판단한다."""
    if last_batch_id == f"factor:{snapshot_as_of}":
        return "factor_snapshot_already_decided"
    if last_decided_at and now - parse_datetime(last_decided_at) < timedelta(days=policy.rebalance_days):
        return "rebalance_not_due"
    return None


__all__ = [
    "FACTOR_BOOK_VERSION",
    "FactorBookPolicy",
    "FactorSignalPlan",
    "LlmView",
    "apply_no_trade_band",
    "evaluate_factor_portfolio",
    "factor_signals",
    "rebalance_due",
]
