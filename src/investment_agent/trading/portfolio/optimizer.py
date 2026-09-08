"""LLM·ML·RL signal을 결정적 convex portfolio 비중으로 변환한다."""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL, SecurityProposal, validated_weights


@dataclass(frozen=True)
class ExpectedReturnSignal:
    symbol: str
    expected_return: float
    confidence: float
    risk_score: float
    horizon_days: int
    source: str
    timestamp: str
    version: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        symbol = str(self.symbol).upper().strip()
        if not symbol or symbol == CASH_SYMBOL:
            raise ValueError("signal symbol must be a risky asset")
        if self.horizon_days not in {1, 5, 20}:
            raise ValueError("signal horizon must be 1, 5, or 20 trading days")
        for name in ("expected_return", "confidence", "risk_score"):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if not 0 <= self.confidence <= 1 or not 0 <= self.risk_score <= 1:
            raise ValueError("confidence and risk_score must be between 0 and 1")
        parse_datetime(self.timestamp)
        if not self.source or not self.version:
            raise ValueError("signal source and version are required")
        object.__setattr__(self, "symbol", symbol)

    @classmethod
    def from_security_proposal(
        cls,
        proposal: SecurityProposal,
        *,
        source: str,
        version: str,
        horizon_days: int = 5,
    ) -> "ExpectedReturnSignal":
        # LLM target_weight는 의도적으로 읽지 않는다.
        risk_score = 1.0 - proposal.confidence
        expected = proposal.expected_excess_return
        if proposal.signal in {"avoid", "watch", "exit"}:
            expected = min(0.0, expected)
        return cls(
            symbol=proposal.ticker,
            expected_return=float(expected),
            confidence=proposal.confidence,
            risk_score=risk_score,
            horizon_days=horizon_days,
            source=source,
            timestamp=proposal.as_of_at,
            version=version,
            evidence_ids=proposal.evidence_ids,
        )


@dataclass(frozen=True)
class OptimizerPolicy:
    key: str = "mean-variance-turnover"
    version: int = 1
    risk_aversion: float = 5.0
    turnover_penalty: float = 0.01
    max_symbol_weight: float = 0.10
    max_sector_weight: float = 0.30
    max_turnover: float = 0.25
    min_cash_weight: float = 0.05

    def __post_init__(self) -> None:
        if self.version < 1 or self.risk_aversion <= 0 or self.turnover_penalty < 0:
            raise ValueError("invalid optimizer objective configuration")
        for name in ("max_symbol_weight", "max_sector_weight", "max_turnover", "min_cash_weight"):
            if not 0 <= float(getattr(self, name)) <= 1:
                raise ValueError(f"{name} must be between 0 and 1")

    @property
    def hash(self) -> str:
        return hashlib.sha256(canonical_json(asdict(self)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OptimizationResult:
    weights: dict[str, float]
    expected_return: float
    estimated_variance: float
    turnover: float
    expected_return_component: float
    risk_penalty: float
    turnover_penalty: float
    objective_value: float
    solver: str
    policy_hash: str
    input_hash: str


class RiskAwareOptimizer:
    """cvxpy가 infeasible/미설치면 주문 가능한 비중을 만들지 않고 실패한다."""

    def __init__(self, policy: OptimizerPolicy | None = None):
        self.policy = policy or OptimizerPolicy()

    def optimize(
        self,
        signals: Sequence[ExpectedReturnSignal],
        *,
        current_weights: Mapping[str, float],
        covariance: Sequence[Sequence[float]] | None = None,
        sector_by_symbol: Mapping[str, str] | None = None,
        fixed_weights: Mapping[str, float] | None = None,
    ) -> OptimizationResult:
        if not signals:
            raise ContractError("optimizer requires at least one signal")
        symbols = tuple(sorted(signal.symbol for signal in signals))
        if len(symbols) != len(set(symbols)):
            raise ContractError("optimizer signals contain duplicate symbols")
        by_symbol = {signal.symbol: signal for signal in signals}
        current = validated_weights(current_weights)
        fixed: dict[str, float] = {}
        for symbol, raw_weight in (fixed_weights or {}).items():
            normalized = str(symbol).upper()
            if normalized == CASH_SYMBOL:
                continue
            weight = float(raw_weight)
            if not math.isfinite(weight) or weight < 0.0:
                raise ContractError("fixed weights must be finite non-negative values")
            if weight > 0.0:
                fixed[normalized] = weight
        overlap = sorted(set(fixed) & set(symbols))
        if overlap:
            raise ContractError("fixed weights must not overlap optimizer signals: " + ", ".join(overlap))
        changed_fixed = sorted(
            symbol for symbol, weight in fixed.items()
            if abs(weight - float(current.get(symbol, 0.0))) > 1e-8
        )
        if changed_fixed:
            raise ContractError(
                "fixed weights must match the account snapshot: " + ", ".join(changed_fixed)
            )
        fixed_risky = math.fsum(fixed.values())
        available_risky = 1.0 - self.policy.min_cash_weight - fixed_risky
        if available_risky < -1e-8:
            raise ContractError("fixed holdings leave no room for the minimum cash weight")
        available_risky = max(0.0, available_risky)
        expected = np.array([
            by_symbol[symbol].expected_return * by_symbol[symbol].confidence
            for symbol in symbols
        ], dtype=float)
        if covariance is None:
            diagonal = np.array([
                max(1e-6, by_symbol[symbol].risk_score ** 2)
                for symbol in symbols
            ], dtype=float)
            cov = np.diag(diagonal)
        else:
            cov = np.asarray(covariance, dtype=float)
        if cov.shape != (len(symbols), len(symbols)) or not np.isfinite(cov).all():
            raise ContractError("covariance must be a finite square matrix matching signals")
        cov = (cov + cov.T) / 2.0
        minimum_eigenvalue = float(np.min(np.linalg.eigvalsh(cov)))
        if minimum_eigenvalue < -1e-8:
            raise ContractError("covariance must be positive semidefinite")
        if minimum_eigenvalue < 0:
            cov += np.eye(len(symbols)) * (-minimum_eigenvalue + 1e-9)
        current_risky = np.array([float(current.get(symbol, 0.0)) for symbol in symbols])
        try:
            import cvxpy as cp
        except ImportError as exc:  # pragma: no cover - 설치 경계
            raise RuntimeError("cvxpy가 필요하다: uv sync --group portfolio") from exc

        weights = cp.Variable(len(symbols), nonneg=True)
        objective = cp.Maximize(
            expected @ weights
            - self.policy.risk_aversion * cp.quad_form(weights, cov)
            - self.policy.turnover_penalty * cp.norm1(weights - current_risky)
        )
        constraints: list[Any] = [
            weights <= self.policy.max_symbol_weight,
            cp.sum(weights) <= available_risky,
            0.5 * (
                cp.norm1(weights - current_risky)
                + cp.abs(
                    float(current.get(CASH_SYMBOL, 0.0))
                    - (1.0 - fixed_risky - cp.sum(weights))
                )
            ) <= self.policy.max_turnover,
        ]
        sectors = {str(key).upper(): str(value) for key, value in (sector_by_symbol or {}).items()}
        for sector in sorted(set(sectors.values())):
            indexes = [index for index, symbol in enumerate(symbols) if sectors.get(symbol) == sector]
            if indexes:
                fixed_sector = math.fsum(
                    weight for symbol, weight in fixed.items() if sectors.get(symbol) == sector
                )
                constraints.append(
                    cp.sum(weights[indexes]) + fixed_sector <= self.policy.max_sector_weight
                )
        problem = cp.Problem(objective, constraints)
        try:
            problem.solve(solver="CLARABEL")
        except Exception as exc:  # noqa: BLE001 - solver 경계
            raise ContractError(f"portfolio optimization failed: {type(exc).__name__}: {exc}") from exc
        if problem.status not in {cp.OPTIMAL, cp.OPTIMAL_INACCURATE} or weights.value is None:
            raise ContractError(f"portfolio optimization is not usable: {problem.status}")
        raw = np.maximum(np.asarray(weights.value, dtype=float).reshape(-1), 0.0)
        result_weights = {
            **fixed,
            **{symbol: float(raw[index]) for index, symbol in enumerate(symbols)},
        }
        result_weights[CASH_SYMBOL] = max(0.0, 1.0 - math.fsum(result_weights.values()))
        result_weights = validated_weights(result_weights)
        turnover = 0.5 * math.fsum(
            abs(result_weights.get(symbol, 0.0) - current.get(symbol, 0.0))
            for symbol in set(result_weights) | set(current)
        )
        expected_return_component = float(expected @ raw)
        estimated_variance = float(raw @ cov @ raw)
        optimizer_turnover = float(np.sum(np.abs(raw - current_risky)))
        risk_penalty = self.policy.risk_aversion * estimated_variance
        turnover_penalty = self.policy.turnover_penalty * optimizer_turnover
        inputs = {
            "signals": [asdict(by_symbol[symbol]) for symbol in symbols],
            "current_weights": current,
            "fixed_weights": fixed,
            "covariance": cov.tolist(),
            "sectors": sectors,
            "policy": asdict(self.policy),
        }
        return OptimizationResult(
            weights=result_weights,
            expected_return=expected_return_component,
            estimated_variance=estimated_variance,
            turnover=turnover,
            expected_return_component=expected_return_component,
            risk_penalty=risk_penalty,
            turnover_penalty=turnover_penalty,
            objective_value=expected_return_component - risk_penalty - turnover_penalty,
            solver="cvxpy:CLARABEL",
            policy_hash=self.policy.hash,
            input_hash=hashlib.sha256(canonical_json(inputs).encode("utf-8")).hexdigest(),
        )


__all__ = ["ExpectedReturnSignal", "OptimizationResult", "OptimizerPolicy", "RiskAwareOptimizer"]
