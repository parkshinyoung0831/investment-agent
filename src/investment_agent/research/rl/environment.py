"""종목 수량이 아니라 목표 비중을 학습하는 FinRL용 환경."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from investment_agent.trading.portfolio.contracts import CASH_SYMBOL
from investment_agent.research.rl.contracts import RewardConfig


@dataclass(frozen=True)
class FeatureDataset:
    """t 시점 feature와 t→t+1 실현수익을 분리해 보관한다."""

    symbols: tuple[str, ...]
    feature_names: tuple[str, ...]
    as_of_values: tuple[str, ...]
    features: np.ndarray
    forward_returns: np.ndarray
    benchmark_forward_returns: np.ndarray
    availability: np.ndarray
    feature_version: str

    def __post_init__(self) -> None:
        symbols = tuple(symbol.upper() for symbol in self.symbols)
        if not symbols or CASH_SYMBOL in symbols or len(set(symbols)) != len(symbols):
            raise ValueError("symbols must be unique risky assets and exclude CASH")
        feature_names = tuple(str(name).strip() for name in self.feature_names)
        if not feature_names or any(not name for name in feature_names):
            raise ValueError("feature_names must not be empty")
        if len(feature_names) != len(set(feature_names)):
            raise ValueError("feature_names must be unique")
        as_of_values = tuple(str(value) for value in self.as_of_values)
        if len(as_of_values) != len(set(as_of_values)):
            raise ValueError("as_of_values must be unique")
        feature_array = np.asarray(self.features, dtype=np.float64).copy()
        return_array = np.asarray(self.forward_returns, dtype=np.float64).copy()
        benchmark_array = np.asarray(self.benchmark_forward_returns, dtype=np.float64).copy()
        mask_array = np.asarray(self.availability, dtype=bool).copy()
        expected_features = (len(self.as_of_values), len(symbols), len(self.feature_names))
        expected_assets = (len(self.as_of_values), len(symbols))
        if feature_array.shape != expected_features:
            raise ValueError(f"features shape must be {expected_features}, got {feature_array.shape}")
        if return_array.shape != expected_assets or mask_array.shape != expected_assets:
            raise ValueError("forward_returns and availability must match time x symbols")
        if benchmark_array.shape != (len(self.as_of_values),):
            raise ValueError("benchmark_forward_returns must match time")
        if len(self.as_of_values) < 1:
            raise ValueError("feature dataset requires at least one period")
        if not self.feature_version:
            raise ValueError("feature_version is required")
        if not np.isfinite(feature_array).all() or not np.isfinite(return_array).all() or not np.isfinite(benchmark_array).all():
            raise ValueError("feature dataset values must be finite; encode missingness in availability/features")
        if (return_array < -1.0).any() or (benchmark_array < -1.0).any():
            raise ValueError("forward returns cannot be below -100%")
        feature_array.setflags(write=False)
        return_array.setflags(write=False)
        benchmark_array.setflags(write=False)
        mask_array.setflags(write=False)
        object.__setattr__(self, "symbols", symbols)
        object.__setattr__(self, "feature_names", feature_names)
        object.__setattr__(self, "as_of_values", as_of_values)
        object.__setattr__(self, "features", feature_array)
        object.__setattr__(self, "forward_returns", return_array)
        object.__setattr__(self, "benchmark_forward_returns", benchmark_array)
        object.__setattr__(self, "availability", mask_array)


@dataclass(frozen=True)
class WeightConstraints:
    """RL이 학습 중에 도달할 수 있는 비중 공간을 실제 실행 한도와 맞춘다.

    이 값이 optimizer/RiskGate보다 느슨하면 policy는 실행 불가능한 비중을 최적이라고
    배우고, 실제로는 RiskGate가 그 제안을 거부한다. 기본값은
    `from_policies()`로 실제 정책에서 가져오며, 어긋나면 테스트가 잡는다.
    """

    max_symbol_weight: float = 0.10
    min_cash_weight: float = 0.05
    max_positions: int = 25
    min_position_weight: float = 0.005

    def __post_init__(self) -> None:
        for name in ("max_symbol_weight", "min_cash_weight", "min_position_weight"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.max_positions < 1:
            raise ValueError("max_positions must be positive")
        if self.max_symbol_weight <= 0.0:
            raise ValueError("max_symbol_weight must be positive")
        if self.min_cash_weight >= 1.0:
            raise ValueError("min_cash_weight must leave room for risky assets")

    @classmethod
    def from_policies(cls) -> "WeightConstraints":
        """optimizer와 RiskGate의 현재 한도를 단일 기준으로 읽어온다."""
        from investment_agent.trading.portfolio.optimizer import OptimizerPolicy
        from investment_agent.trading.risk.gate import PortfolioRiskPolicy

        optimizer = OptimizerPolicy()
        risk = PortfolioRiskPolicy()
        return cls(
            max_symbol_weight=min(optimizer.max_symbol_weight, risk.max_symbol_weight),
            min_cash_weight=max(optimizer.min_cash_weight, risk.min_cash_weight),
            max_positions=risk.max_positions,
            min_position_weight=risk.min_position_weight,
        )


def _project_to_constraints(
    risky: np.ndarray,
    availability: np.ndarray,
    constraints: WeightConstraints,
) -> np.ndarray:
    """long-only 비중을 종목 상한·종목 수·dust 규칙 안으로 밀어 넣는다.

    상한을 넘은 몫은 아직 여유가 있는 종목에 비례 배분하고, 전부 상한에 닿으면
    남는 몫은 현금으로 간다(호출자가 잔여를 현금에 넣는다).
    """
    budget = 1.0 - constraints.min_cash_weight
    weights = np.clip(risky, 0.0, None)
    weights[~availability] = 0.0
    total = float(weights.sum())
    if total <= 0.0:
        return np.zeros_like(weights)
    # min_cash_weight는 하한이지 목표가 아니다. 정책이 원한 위험자산 총량을 그대로
    # 두되 현금 하한을 침범할 때만 줄인다. 여기서 budget으로 강제 정규화하면
    # "거의 전부 현금"을 원한 policy까지 위험자산 95%로 뒤집힌다.
    weights = weights / total * min(total, budget)

    # 종목 수 제한: 큰 것부터 남기고 나머지 몫은 남은 종목에 비례 배분한다.
    active = int(min(constraints.max_positions, int(availability.sum())))
    if active < int(np.count_nonzero(weights)):
        retained = float(weights.sum())
        keep = np.argsort(weights)[::-1][:active]
        trimmed = np.zeros_like(weights)
        trimmed[keep] = weights[keep]
        weights = trimmed
        if weights.sum() > 0.0:
            weights = weights / float(weights.sum()) * retained

    # 종목 상한은 잘라내기만 하고 재배분하지 않는다. policy가 담지 않겠다고 한 종목에
    # 초과분을 밀어 넣으면 학습 신호가 뒤집히므로, 넘친 몫은 현금으로 남긴다.
    # 노출을 키우려면 policy가 스스로 분산하는 법을 배워야 한다.
    weights = np.minimum(weights, constraints.max_symbol_weight)

    # dust 제거: RiskGate가 어차피 현금화하는 잔량을 학습 단계에서도 만들지 않는다.
    weights[weights < constraints.min_position_weight] = 0.0
    return weights


def action_to_weights(
    action: Sequence[float],
    availability: np.ndarray,
    *,
    constraints: WeightConstraints | None = None,
) -> np.ndarray:
    """연속 action을 실행 가능한 long-only risky assets + CASH 비중으로 바꾼다."""
    logits = np.asarray(action, dtype=np.float64)
    if logits.shape != (len(availability) + 1,):
        raise ValueError("action must contain every symbol plus CASH")
    if not np.isfinite(logits).all():
        raise ValueError("action must be finite")
    masked = logits.copy()
    masked[:-1][~availability] = -1e9
    shifted = masked - np.max(masked)
    exp = np.exp(np.clip(shifted, -700, 700))
    exp[:-1][~availability] = 0.0
    total = float(exp.sum())
    if total <= 0.0:
        result = np.zeros_like(exp)
        result[-1] = 1.0
        return result
    simplex = exp / total
    limits = constraints or WeightConstraints.from_policies()
    risky = _project_to_constraints(simplex[:-1], availability, limits)
    result = np.zeros_like(simplex)
    result[:-1] = risky
    # 잔여는 전부 현금이다. 이렇게 해야 합이 정확히 1이고 최소 현금도 지켜진다.
    result[-1] = max(0.0, 1.0 - float(risky.sum()))
    return result


@dataclass
class WeightEnvironmentCore:
    """Gym과 분리된 결정적 상태 전이로 reward·비중 계약을 단위 테스트한다."""

    dataset: FeatureDataset
    reward_config: RewardConfig = field(default_factory=RewardConfig)
    constraints: WeightConstraints = field(default_factory=WeightConstraints.from_policies)
    index: int = 0
    nav: float = 1.0
    peak_nav: float = 1.0
    current_weights: np.ndarray = field(init=False)
    realized_returns: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.current_weights = np.zeros(len(self.dataset.symbols) + 1, dtype=np.float64)
        self.current_weights[-1] = 1.0

    @property
    def observation_size(self) -> int:
        n = len(self.dataset.symbols)
        return n * len(self.dataset.feature_names) + n + n + 1

    def observation(self) -> np.ndarray:
        if self.index >= len(self.dataset.as_of_values):
            n = len(self.dataset.symbols)
            features = np.zeros(n * len(self.dataset.feature_names), dtype=np.float64)
            mask = np.zeros(n, dtype=np.float64)
            return np.concatenate((features, mask, self.current_weights))
        features = self.dataset.features[self.index].reshape(-1)
        mask = self.dataset.availability[self.index].astype(np.float64)
        return np.concatenate((features, mask, self.current_weights))

    def reset(self) -> np.ndarray:
        self.index = 0
        self.nav = 1.0
        self.peak_nav = 1.0
        self.realized_returns = []
        self.current_weights = np.zeros(len(self.dataset.symbols) + 1, dtype=np.float64)
        self.current_weights[-1] = 1.0
        return self.observation()

    def step(self, action: Sequence[float]) -> tuple[np.ndarray, float, bool, dict[str, Any]]:
        if self.index >= len(self.dataset.as_of_values):
            raise RuntimeError("environment episode is already complete")
        target = action_to_weights(
            action, self.dataset.availability[self.index], constraints=self.constraints,
        )
        # current_weights는 지난 구간 수익률만큼 이미 흘러간 실제 보유 비중이다.
        turnover = 0.5 * float(np.abs(target - self.current_weights).sum())
        gross_return = float(np.dot(target[:-1], self.dataset.forward_returns[self.index]))
        transaction_cost = turnover * self.reward_config.transaction_cost_rate
        net_return = gross_return - transaction_cost
        if net_return <= -1.0:
            raise RuntimeError("transaction costs and return would make NAV non-positive")
        benchmark = float(self.dataset.benchmark_forward_returns[self.index])
        alpha = net_return - benchmark

        self.nav *= 1.0 + net_return
        self.peak_nav = max(self.peak_nav, self.nav)
        drawdown = max(0.0, 1.0 - self.nav / self.peak_nav)
        self.realized_returns.append(net_return)
        window = self.realized_returns[-self.reward_config.volatility_window:]
        volatility = float(np.std(window, ddof=1)) if len(window) > 1 else 0.0
        concentration = float(np.square(target[:-1]).sum())
        reward = (
            self.reward_config.return_weight * net_return
            + self.reward_config.alpha_weight * alpha
            - self.reward_config.drawdown_penalty * drawdown
            - self.reward_config.volatility_penalty * volatility
            - self.reward_config.turnover_penalty * turnover
            - self.reward_config.concentration_penalty * concentration
        )

        # 다음 구간 시작 비중은 목표가 아니라 **가격 변동을 반영한 실제 비중**이다.
        # target을 그대로 이월하면 리밸런싱이 공짜로 일어난 셈이 되어 회전율과
        # 거래비용이 실제보다 작게 나오고, 백테스트가 낙관적으로 기운다.
        grown = target[:-1] * (1.0 + self.dataset.forward_returns[self.index])
        drifted = np.append(grown, target[-1])
        drifted_total = float(drifted.sum())
        if drifted_total > 0.0:
            self.current_weights = drifted / drifted_total
        else:
            self.current_weights = np.zeros_like(target)
            self.current_weights[-1] = 1.0
        info_drifted = self.current_weights.copy()
        self.index += 1
        done = self.index >= len(self.dataset.as_of_values)
        info = {
            "as_of_at": self.dataset.as_of_values[self.index - 1],
            "gross_return": gross_return,
            "net_return": net_return,
            "benchmark_return": benchmark,
            "alpha": alpha,
            "turnover": turnover,
            "transaction_cost": transaction_cost,
            "drawdown": drawdown,
            "volatility": volatility,
            "concentration": concentration,
            "weights": {
                **{symbol: float(target[i]) for i, symbol in enumerate(self.dataset.symbols)},
                CASH_SYMBOL: float(target[-1]),
            },
            "weights_after_drift": {
                **{symbol: float(info_drifted[i]) for i, symbol in enumerate(self.dataset.symbols)},
                CASH_SYMBOL: float(info_drifted[-1]),
            },
        }
        return self.observation(), float(reward), done, info


def make_gym_environment(dataset: FeatureDataset, reward_config: RewardConfig | None = None):
    """FinRL/Stable-Baselines3가 요구하는 Gymnasium 환경을 지연 생성한다."""
    try:
        import gymnasium as gym
        from gymnasium import spaces
    except ImportError as exc:  # pragma: no cover - 선택 의존성 경계
        raise RuntimeError("gymnasium이 필요하다: uv sync --group rl") from exc

    class PortfolioWeightEnv(gym.Env):
        metadata = {"render_modes": []}

        def __init__(self) -> None:
            super().__init__()
            self.core = WeightEnvironmentCore(dataset, reward_config or RewardConfig())
            self.action_space = spaces.Box(
                low=-10.0, high=10.0, shape=(len(dataset.symbols) + 1,), dtype=np.float32
            )
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf, shape=(self.core.observation_size,), dtype=np.float32
            )

        def reset(self, *, seed: int | None = None, options: dict | None = None):
            super().reset(seed=seed)
            return self.core.reset().astype(np.float32), {}

        def step(self, action):
            observation, reward, done, info = self.core.step(action)
            return observation.astype(np.float32), reward, done, False, info

    return PortfolioWeightEnv()
