"""AI가 바꿀 수 없는 결정적 포트폴리오 위험 게이트."""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.trading.portfolio.contracts import (
    CASH_SYMBOL,
    PortfolioProposal,
    RiskDecision,
    validated_weights,
)
from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.platform.serialization import canonical_json, stable_id


@dataclass(frozen=True)
class PortfolioRiskPolicy:
    """코드 리뷰 없이 모델이 변경할 수 없는 long-only 위험 한도."""

    key: str = "portfolio-risk"
    version: int = 1
    max_symbol_weight: float = 0.10
    max_sector_weight: float = 0.30
    max_turnover: float = 0.25
    max_positions: int = 25
    min_position_weight: float = 0.005
    min_cash_weight: float = 0.05
    max_proposal_age_hours: float = 36.0
    max_portfolio_volatility: float = 0.30
    max_abs_beta: float = 1.50
    max_pairwise_correlation: float = 0.95
    max_concentration_hhi: float = 0.15
    require_market_risk_for_execution: bool = True
    allow_short: bool = False
    require_sector_map: bool = False

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("risk policy version must be positive")
        for name in (
            "max_symbol_weight", "max_sector_weight", "max_turnover",
            "min_position_weight", "min_cash_weight",
            "max_portfolio_volatility", "max_pairwise_correlation", "max_concentration_hhi",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.max_positions < 1:
            raise ValueError("max_positions must be positive")
        if not math.isfinite(self.max_proposal_age_hours) or self.max_proposal_age_hours <= 0:
            raise ValueError("max_proposal_age_hours must be positive")
        if not math.isfinite(self.max_abs_beta) or self.max_abs_beta <= 0:
            raise ValueError("max_abs_beta must be positive")
        if self.allow_short:
            raise ValueError("version 1 risk gate is long-only")

    def to_config(self) -> dict:
        return asdict(self)

    @property
    def hash(self) -> str:
        return hashlib.sha256(canonical_json(self.to_config()).encode("utf-8")).hexdigest()


def portfolio_turnover(current: Mapping[str, float], target: Mapping[str, float]) -> float:
    symbols = set(current) | set(target)
    return 0.5 * math.fsum(abs(float(target.get(s, 0.0)) - float(current.get(s, 0.0))) for s in symbols)


class DeterministicRiskGate:
    def __init__(self, policy: PortfolioRiskPolicy | None = None):
        self.policy = policy or PortfolioRiskPolicy()

    @staticmethod
    def _move_to_cash(weights: dict[str, float], symbol: str, amount: float) -> None:
        weights[symbol] -= amount
        weights[CASH_SYMBOL] = weights.get(CASH_SYMBOL, 0.0) + amount

    def evaluate(
        self,
        proposal: PortfolioProposal,
        *,
        current_weights: Mapping[str, float],
        tradable_symbols: set[str],
        decided_at: datetime | None = None,
        sector_by_symbol: Mapping[str, str] | None = None,
        portfolio_volatility: float | None = None,
        portfolio_beta: float | None = None,
        max_pairwise_correlation: float | None = None,
        drawdown_fraction: float | None = None,
        market_risk_metadata: Mapping[str, object] | None = None,
    ) -> RiskDecision:
        """잘못된 입력은 거부하고, 한도 초과 비중만 결정적으로 현금화한다."""
        now = (decided_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        current = validated_weights(current_weights)
        weights = dict(proposal.weights)
        violations: list[str] = []
        adjustments: list[str] = []

        proposal_time = parse_datetime(proposal.as_of_at)
        if proposal_time > now:
            violations.append("proposal as_of_at is in the future")
        age_hours = (now - proposal_time).total_seconds() / 3600.0
        if age_hours > self.policy.max_proposal_age_hours:
            violations.append(
                f"proposal is stale: {age_hours:.2f}h > {self.policy.max_proposal_age_hours:.2f}h"
            )

        unknown = sorted(set(weights) - {CASH_SYMBOL} - {s.upper() for s in tradable_symbols})
        if unknown:
            violations.append("untradable target symbols: " + ", ".join(unknown))

        risk_inputs = {
            "portfolio_volatility": portfolio_volatility,
            "portfolio_beta": portfolio_beta,
            "max_pairwise_correlation": max_pairwise_correlation,
            "drawdown_fraction": drawdown_fraction,
        }
        if self.policy.require_market_risk_for_execution and proposal.stage in {"paper", "live"}:
            missing_risk = sorted(
                key for key in ("portfolio_volatility", "portfolio_beta", "max_pairwise_correlation")
                if risk_inputs[key] is None
            )
            if missing_risk:
                violations.append("missing execution market-risk inputs: " + ", ".join(missing_risk))
        for name, value in risk_inputs.items():
            if value is not None and (isinstance(value, bool) or not math.isfinite(float(value))):
                violations.append(f"{name} must be finite")
        if portfolio_volatility is not None and portfolio_volatility > self.policy.max_portfolio_volatility:
            violations.append("portfolio volatility exceeds the absolute limit")
        if portfolio_beta is not None and abs(portfolio_beta) > self.policy.max_abs_beta:
            violations.append("portfolio beta exceeds the absolute limit")
        if (
            max_pairwise_correlation is not None
            and max_pairwise_correlation > self.policy.max_pairwise_correlation
        ):
            violations.append("pairwise correlation exceeds the absolute limit")
        if drawdown_fraction is not None and not 0.0 <= drawdown_fraction <= 1.0:
            violations.append("drawdown_fraction must be between 0 and 1")

        for symbol in sorted(set(weights) - {CASH_SYMBOL}):
            weight = weights[symbol]
            if 0.0 < weight < self.policy.min_position_weight:
                self._move_to_cash(weights, symbol, weight)
                adjustments.append(f"{symbol} below minimum position moved to CASH")
            elif weight > self.policy.max_symbol_weight:
                excess = weight - self.policy.max_symbol_weight
                self._move_to_cash(weights, symbol, excess)
                adjustments.append(f"{symbol} capped at {self.policy.max_symbol_weight:.6f}")

        active = sorted(
            (symbol for symbol in weights if symbol != CASH_SYMBOL and weights[symbol] > 0.0),
            key=lambda symbol: (-weights[symbol], symbol),
        )
        for symbol in active[self.policy.max_positions:]:
            amount = weights[symbol]
            self._move_to_cash(weights, symbol, amount)
            adjustments.append(f"{symbol} removed by max_positions")

        sectors = {str(k).upper(): str(v) for k, v in (sector_by_symbol or {}).items()}
        invested_symbols = [s for s in weights if s != CASH_SYMBOL and weights[s] > 0.0]
        missing_sectors = sorted(s for s in invested_symbols if not sectors.get(s))
        if self.policy.require_sector_map and missing_sectors:
            violations.append("missing sector mapping: " + ", ".join(missing_sectors))
        if sectors:
            by_sector: dict[str, list[str]] = {}
            for symbol in invested_symbols:
                if sectors.get(symbol):
                    by_sector.setdefault(sectors[symbol], []).append(symbol)
            for sector in sorted(by_sector):
                symbols = sorted(by_sector[sector])
                total = math.fsum(weights[s] for s in symbols)
                if total <= self.policy.max_sector_weight:
                    continue
                scale = self.policy.max_sector_weight / total
                removed = 0.0
                for symbol in symbols:
                    before = weights[symbol]
                    weights[symbol] = before * scale
                    removed += before - weights[symbol]
                weights[CASH_SYMBOL] += removed
                adjustments.append(f"sector {sector} capped at {self.policy.max_sector_weight:.6f}")

        if weights[CASH_SYMBOL] < self.policy.min_cash_weight:
            risky_total = 1.0 - weights[CASH_SYMBOL]
            target_risky = 1.0 - self.policy.min_cash_weight
            if risky_total <= 0.0:
                violations.append("cannot create minimum cash from an empty risky book")
            else:
                scale = target_risky / risky_total
                for symbol in list(weights):
                    if symbol != CASH_SYMBOL:
                        weights[symbol] *= scale
                weights[CASH_SYMBOL] = self.policy.min_cash_weight
                adjustments.append(f"CASH raised to {self.policy.min_cash_weight:.6f}")

        if not violations:
            turnover = portfolio_turnover(current, weights)
            if turnover > self.policy.max_turnover:
                scale = self.policy.max_turnover / turnover
                symbols = set(current) | set(weights)
                weights = {
                    symbol: float(current.get(symbol, 0.0))
                    + scale * (float(weights.get(symbol, 0.0)) - float(current.get(symbol, 0.0)))
                    for symbol in symbols
                }
                weights = {s: max(0.0, w) for s, w in weights.items()}
                residual = 1.0 - math.fsum(weights.values())
                weights[CASH_SYMBOL] = weights.get(CASH_SYMBOL, 0.0) + residual
                adjustments.append(f"turnover scaled from {turnover:.6f} to {self.policy.max_turnover:.6f}")

        concentration_hhi = math.fsum(
            weight * weight for symbol, weight in weights.items() if symbol != CASH_SYMBOL
        )
        if concentration_hhi > self.policy.max_concentration_hhi:
            violations.append(
                f"portfolio concentration HHI exceeds limit: "
                f"{concentration_hhi:.6f} > {self.policy.max_concentration_hhi:.6f}"
            )

        input_payload = {
            "proposal": proposal.to_dict(),
            "current_weights": current,
            "tradable_symbols": sorted(s.upper() for s in tradable_symbols),
            "sector_by_symbol": sectors,
            "market_risk": risk_inputs,
            "market_risk_metadata": dict(market_risk_metadata or {}),
            "policy": self.policy.to_config(),
        }
        input_hash = hashlib.sha256(canonical_json(input_payload).encode("utf-8")).hexdigest()
        is_approved = not violations
        approved_weights = validated_weights(weights) if is_approved else None
        identity = {
            "proposal_id": proposal.proposal_id,
            "policy_hash": self.policy.hash,
            "input_hash": input_hash,
        }
        return RiskDecision(
            risk_decision_id=stable_id("risk", identity),
            proposal_id=proposal.proposal_id,
            policy_key=self.policy.key,
            policy_version=self.policy.version,
            policy_hash=self.policy.hash,
            input_hash=input_hash,
            is_approved=is_approved,
            approved_weights=approved_weights,
            violations=tuple(violations),
            adjustments=tuple(adjustments),
            metrics={
                **risk_inputs,
                "drawdown_fraction": drawdown_fraction,
                "concentration_hhi": concentration_hhi,
                "turnover": portfolio_turnover(current, weights),
                "market_risk": dict(market_risk_metadata or {}),
                "policy_limits": self.policy.to_config(),
            },
            decided_at=now.isoformat(),
        )

    def create_execution_intent(
        self,
        decision: RiskDecision,
        *,
        execution_mode: str,
        not_before: datetime,
        ttl_minutes: int = 30,
    ) -> ExecutionIntent:
        if not decision.is_approved or decision.approved_weights is None:
            raise ContractError("only an approved risk decision can create an execution intent")
        if ttl_minutes < 1 or ttl_minutes > 240:
            raise ContractError("ttl_minutes must be between 1 and 240")
        start = not_before.astimezone(timezone.utc)
        payload = {
            "risk_decision_id": decision.risk_decision_id,
            "proposal_id": decision.proposal_id,
            "execution_mode": execution_mode,
            "target_weights": decision.approved_weights,
            "input_hash": decision.input_hash,
            "not_before": start.isoformat(),
        }
        return ExecutionIntent(
            intent_id=stable_id("intent", payload),
            risk_decision_id=decision.risk_decision_id,
            proposal_id=decision.proposal_id,
            execution_mode=execution_mode,
            target_weights=decision.approved_weights,
            input_hash=decision.input_hash,
            not_before=start,
            expires_at=start + timedelta(minutes=ttl_minutes),
        )
