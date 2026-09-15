"""종목 기대수익을 결정적 convex portfolio 비중으로 변환한다.

## 비중은 여기서만 정해진다

ALPHA는 종목마다 기대수익과, 필요할 때만 강제 제약 하나를 넘긴다. 사고팔기(신규·확대·유지·축소)는
결과 비중과 직전 비중의 차이일 뿐 입력이 아니다 — 입력으로 받으면 판단자가 둘이 된다.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL, validated_weights
from investment_agent.trading.portfolio.market_risk import TradingCostInputs

# 기대수익 크기로는 표현할 수 없는 예외만 제약으로 받는다.
# force_exit는 논지가 깨진 보유의 전량 청산이다 — 기대수익을 0 이하로 낮추는 것만으로는 turnover
# 한도가 잔여 비중을 남길 수 있다. block_increase는 비중을 늘리지 못하게만 막고 얼마나 줄일지는
# optimizer에 맡긴다(검증 전 신규·품질 붕괴·하락 논지).
CONSTRAINT_FORCE_EXIT = "force_exit"
CONSTRAINT_BLOCK_INCREASE = "block_increase"
CONSTRAINTS = frozenset({CONSTRAINT_FORCE_EXIT, CONSTRAINT_BLOCK_INCREASE})


def mandatory_base_weights(
    current: Mapping[str, float],
    *,
    exit_symbols: set[str] | frozenset[str],
    max_symbol_weight: float,
    min_cash_weight: float = 0.0,
) -> dict[str, float]:
    """한도 준수에 **반드시** 필요한 매도만 먼저 반영한 출발 비중이다.

    turnover 한도는 재량 매매의 비용을 묶는 장치다. 청산 명령과 종목 상한 초과분까지
    그 예산에서 깎으면, 한꺼번에 여러 종목을 빼야 하는 날 위험 축소가 막히거나 이미
    잘라 둔 상한 초과분이 도로 살아난다. 그래서 turnover는 이 출발점에서부터 잰다.
    출발점으로 가는 이동은 전부 현금화라 위험을 늘리지 않는다.
    """
    base: dict[str, float] = {}
    for symbol, weight in current.items():
        if symbol == CASH_SYMBOL:
            continue
        value = float(weight)
        if symbol in exit_symbols:
            value = 0.0
        else:
            value = min(value, max_symbol_weight)
        if value > 0.0:
            base[symbol] = value
    risky = math.fsum(base.values())
    ceiling = max(0.0, 1.0 - float(min_cash_weight))
    if risky > ceiling and risky > 0.0:
        # 최소 현금도 한도 준수다. 비례로 현금화한 지점을 출발점으로 둬야 turnover 축소가
        # 채워 둔 현금을 다시 주식으로 되돌리지 않는다.
        scale = ceiling / risky
        base = {symbol: value * scale for symbol, value in base.items()}
    base[CASH_SYMBOL] = max(0.0, 1.0 - math.fsum(base.values()))
    return base


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
    # 기대수익으로 표현할 수 없는 강제 제약(`CONSTRAINT_*`). 없으면 optimizer가 자유롭게 정한다.
    constraint: str | None = None

    def __post_init__(self) -> None:
        symbol = str(self.symbol).upper().strip()
        if not symbol or symbol == CASH_SYMBOL:
            raise ValueError("signal symbol must be a risky asset")
        if self.constraint is not None and self.constraint not in CONSTRAINTS:
            raise ValueError(f"unsupported signal constraint: {self.constraint}")
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


@dataclass(frozen=True)
class OptimizerPolicy:
    key: str = "mean-variance-turnover"
    version: int = 3
    risk_aversion: float = 5.0
    turnover_penalty: float = 0.01
    max_symbol_weight: float = 0.10
    max_sector_weight: float = 0.30
    max_turnover: float = 0.25
    min_cash_weight: float = 0.05
    # False면 어떤 종목도 현재 비중보다 늘릴 수 없다(위기 regime의 신규 위험 금지).
    allow_increases: bool = True
    # 포트폴리오 시장 베타 상한. None이면 제약하지 않는다(베타 재료가 없을 때).
    max_portfolio_beta: float | None = None
    # 기대초과수익 크기 상한을 그 종목의 신호 기간 수익률 표준편차의 배수로 둔다.
    # 1σ를 넘는 초과수익 예측은 사실상 확실한 초과성과를 주장하는 것인데, 실제 신호의 순위
    # 상관(IC)은 그보다 훨씬 작다. 상한이 없으면 +25% 같은 과대 예측 하나가 비중을 독점한다.
    # 공분산이 없는 관찰용 fallback에서는 종목 변동성을 모르므로 적용하지 않는다.
    max_expected_return_sigma: float | None = 1.0

    def __post_init__(self) -> None:
        if self.version < 1 or self.risk_aversion <= 0 or self.turnover_penalty < 0:
            raise ValueError("invalid optimizer objective configuration")
        for name in ("max_symbol_weight", "max_sector_weight", "max_turnover", "min_cash_weight"):
            if not 0 <= float(getattr(self, name)) <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.max_expected_return_sigma is not None and (
            not math.isfinite(self.max_expected_return_sigma) or self.max_expected_return_sigma <= 0
        ):
            raise ValueError("max_expected_return_sigma must be finite and positive")

    @property
    def hash(self) -> str:
        return hashlib.sha256(canonical_json(asdict(self)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FactorExposureLimit:
    """신호 종목 비중으로 가중평균한 factor 노출의 범위.

    종합 점수만 최대화하면 점수에 가장 크게 기여하는 한 factor(보통 모멘텀)에 포트폴리오가 쏠린다. 그 factor가
    꺾이는 날 전 종목이 같이 빠진다. 노출값이 없는 종목은 중립값을 쓴다 — 모른다고 극단으로 두지 않는다.
    고정 보유는 optimizer가 움직일 수 없어 이 제약에서 뺀다.
    """

    loadings: Mapping[str, float]
    minimum: float | None = None
    maximum: float | None = None
    neutral: float = 0.5

    def __post_init__(self) -> None:
        if self.minimum is None and self.maximum is None:
            raise ValueError("factor exposure limit needs a minimum or a maximum")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("factor exposure minimum must not exceed maximum")
        for value in (self.minimum, self.maximum, self.neutral, *self.loadings.values()):
            if value is not None and not math.isfinite(float(value)):
                raise ValueError("factor exposure values must be finite")

    def loading(self, symbol: str) -> float:
        return float(self.loadings.get(symbol, self.neutral))


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
    transaction_cost: float = 0.0
    # 상한에 걸려 줄어든 기대수익: {종목: {"raw": 원래 값, "capped": 적용 값}}
    capped_expected_returns: dict[str, dict[str, float]] | None = None


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
        trading_costs: Mapping[str, TradingCostInputs] | None = None,
        betas: Mapping[str, float] | None = None,
        factor_exposures: Mapping[str, "FactorExposureLimit"] | None = None,
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
                "fixed weights must match the current weights: " + ", ".join(changed_fixed)
            )
        fixed_risky = math.fsum(fixed.values())
        available_risky = 1.0 - self.policy.min_cash_weight - fixed_risky
        if available_risky < -1e-8:
            raise ContractError("fixed holdings leave no room for the minimum cash weight")
        available_risky = max(0.0, available_risky)
        raw_expected = np.array([by_symbol[symbol].expected_return for symbol in symbols], dtype=float)
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
        capped: dict[str, dict[str, float]] = {}
        bounded_expected = raw_expected.copy()
        if covariance is not None and self.policy.max_expected_return_sigma is not None:
            limits = self.policy.max_expected_return_sigma * np.sqrt(np.maximum(np.diag(cov), 0.0))
            bounded_expected = np.clip(raw_expected, -limits, limits)
            for index, symbol in enumerate(symbols):
                if abs(bounded_expected[index] - raw_expected[index]) > 1e-12:
                    capped[symbol] = {"raw": float(raw_expected[index]), "capped": float(bounded_expected[index])}
        expected = bounded_expected * np.array([by_symbol[symbol].confidence for symbol in symbols], dtype=float)
        current_risky = np.array([float(current.get(symbol, 0.0)) for symbol in symbols])
        exit_symbols = frozenset(
            symbol for symbol in symbols if by_symbol[symbol].constraint == CONSTRAINT_FORCE_EXIT
        )
        base = mandatory_base_weights(
            {symbol: current.get(symbol, 0.0) for symbol in symbols} | fixed,
            exit_symbols=exit_symbols,
            max_symbol_weight=self.policy.max_symbol_weight,
        )
        base_risky = np.array([float(base.get(symbol, 0.0)) for symbol in symbols])
        if float(base_risky.sum()) > available_risky + 1e-12 and float(base_risky.sum()) > 0.0:
            # 고정 보유는 못 움직이므로 최소 현금을 채우는 매도는 신호 종목에서만 비례로 한다.
            base_risky = base_risky * (available_risky / float(base_risky.sum()))
        # 고정 보유는 움직이지 않으므로 출발 현금은 신호 종목의 강제 매도분만 더한다.
        base_cash = 1.0 - fixed_risky - float(base_risky.sum())
        try:
            import cvxpy as cp
        except ImportError as exc:  # pragma: no cover - 설치 경계
            raise RuntimeError("cvxpy가 필요하다: uv sync --group portfolio") from exc

        half_spread = self._half_spreads(symbols, trading_costs)
        weights = cp.Variable(len(symbols), nonneg=True)
        trade = weights - current_risky
        cost_expression: Any = 0.0
        if half_spread is not None:
            # 비용은 거래 비중에 선형인 반스프레드뿐이다(개인 계좌 규모에서는 시장충격이 무시할 만하다).
            cost_expression = half_spread @ cp.abs(trade)
        objective = cp.Maximize(
            expected @ weights
            - self.policy.risk_aversion * cp.quad_form(weights, cov)
            - self.policy.turnover_penalty * cp.norm1(trade)
            - cost_expression
        )
        constraints: list[Any] = [
            weights <= self.policy.max_symbol_weight,
            cp.sum(weights) <= available_risky,
            0.5 * (
                cp.norm1(weights - base_risky)
                + cp.abs(base_cash - (1.0 - fixed_risky - cp.sum(weights)))
            ) <= self.policy.max_turnover,
        ]
        beta_budget = self._beta_budget(symbols, fixed, current, betas)
        if beta_budget is not None:
            signal_betas, budget = beta_budget
            constraints.append(signal_betas @ weights <= budget)
        if not self.policy.allow_increases:
            constraints.append(weights <= current_risky)
        for name, limit in sorted((factor_exposures or {}).items()):
            loadings = np.array([limit.loading(symbol) for symbol in symbols], dtype=float)
            # 가중평균 노출 = Σw·x / Σw. 분모를 곱해 선형으로 둔다(Σw=0이면 자명하게 만족한다).
            if limit.maximum is not None:
                constraints.append((loadings - limit.maximum) @ weights <= 0.0)
            if limit.minimum is not None:
                constraints.append((loadings - limit.minimum) @ weights >= 0.0)
        for index, symbol in enumerate(symbols):
            constraint = by_symbol[symbol].constraint
            if constraint == CONSTRAINT_FORCE_EXIT:
                constraints.append(weights[index] == 0.0)
            elif constraint == CONSTRAINT_BLOCK_INCREASE:
                constraints.append(weights[index] <= float(current_risky[index]))
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
        for index, symbol in enumerate(symbols):
            # solver 허용오차가 남긴 1e-9 수준의 잔량이 1주 매도 누락으로 이어지지 않게 한다.
            if symbol in exit_symbols:
                raw[index] = 0.0
            elif by_symbol[symbol].constraint == CONSTRAINT_BLOCK_INCREASE or not self.policy.allow_increases:
                raw[index] = min(raw[index], float(current_risky[index]))
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
        transaction_cost = 0.0
        if half_spread is not None:
            transaction_cost = float(half_spread @ np.abs(raw - current_risky))
        inputs = {
            "signals": [asdict(by_symbol[symbol]) for symbol in symbols],
            "current_weights": current,
            "fixed_weights": fixed,
            "covariance": cov.tolist(),
            "sectors": sectors,
            "policy": asdict(self.policy),
            "trading_costs": (
                {symbol: trading_costs[symbol].to_metadata() for symbol in symbols}
                if half_spread is not None and trading_costs is not None else None
            ),
            "capped_expected_returns": capped,
        }
        if factor_exposures:
            # 노출 제약이 없는 판단의 입력 hash는 제약이 생기기 전과 같게 둔다.
            inputs["factor_exposures"] = {
                name: {"min": limit.minimum, "max": limit.maximum,
                       "loadings": {symbol: limit.loading(symbol) for symbol in symbols}}
                for name, limit in sorted(factor_exposures.items())
            }
        return OptimizationResult(
            weights=result_weights,
            expected_return=expected_return_component,
            estimated_variance=estimated_variance,
            turnover=turnover,
            expected_return_component=expected_return_component,
            risk_penalty=risk_penalty,
            turnover_penalty=turnover_penalty,
            objective_value=expected_return_component - risk_penalty - turnover_penalty - transaction_cost,
            solver="cvxpy:CLARABEL",
            policy_hash=self.policy.hash,
            input_hash=hashlib.sha256(canonical_json(inputs).encode("utf-8")).hexdigest(),
            transaction_cost=transaction_cost,
            capped_expected_returns=capped,
        )

    def _beta_budget(
        self,
        symbols: tuple[str, ...],
        fixed: Mapping[str, float],
        current: Mapping[str, float],
        betas: Mapping[str, float] | None,
    ) -> tuple[np.ndarray, float] | None:
        """신호 종목이 쓸 수 있는 베타 여유. 고정 보유가 이미 상한을 넘으면 지금보다 늘리지만 않게 한다.

        베타 상한을 사후 검사(RiskGate)로만 두면 optimizer는 한도를 모른 채 고베타 종목에 몰고,
        게이트는 제안 전체를 거부한다. 처음부터 한도 안에서 풀어야 거래가 살아남는다.
        """
        if self.policy.max_portfolio_beta is None or betas is None:
            return None
        normalized = {str(key).upper(): float(value) for key, value in betas.items()}
        missing = sorted((set(symbols) | set(fixed)) - set(normalized))
        if missing:
            raise ContractError("beta inputs are missing: " + ", ".join(missing))
        if not all(math.isfinite(value) for value in normalized.values()):
            raise ContractError("beta inputs must be finite")
        signal_betas = np.array([normalized[symbol] for symbol in symbols], dtype=float)
        fixed_beta = math.fsum(weight * normalized[symbol] for symbol, weight in fixed.items())
        current_signal_beta = float(signal_betas @ np.array([float(current.get(s, 0.0)) for s in symbols]))
        budget = max(float(self.policy.max_portfolio_beta) - fixed_beta, current_signal_beta)
        return signal_betas, budget

    @staticmethod
    def _half_spreads(
        symbols: tuple[str, ...],
        trading_costs: Mapping[str, TradingCostInputs] | None,
    ) -> np.ndarray | None:
        """비중 단위 편도 비용 계수. 일부 종목만 비용을 모르면 거부한다."""
        if trading_costs is None:
            return None
        normalized = {str(key).upper(): value for key, value in trading_costs.items()}
        missing = sorted(set(symbols) - set(normalized))
        if missing:
            raise ContractError("trading cost inputs are missing: " + ", ".join(missing))
        half_spread = np.array([normalized[symbol].half_spread for symbol in symbols], dtype=float)
        if not np.isfinite(half_spread).all() or (half_spread < 0).any():
            raise ContractError("trading cost inputs are out of range")
        return half_spread


__all__ = [
    "CONSTRAINTS", "CONSTRAINT_BLOCK_INCREASE", "CONSTRAINT_FORCE_EXIT", "ExpectedReturnSignal",
    "FactorExposureLimit", "OptimizationResult",
    "OptimizerPolicy", "RiskAwareOptimizer", "mandatory_base_weights",
]
