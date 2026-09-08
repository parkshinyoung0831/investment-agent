"""실제 매매 결과 기반 경험 수집 및 보상 누적 엔진.

일일 장 마감 후 시점의 시장 상태 Feature, 시스템이 결정한 Action 비중,
익일 실현 수익률, 턴오버, 슬리피지 비용을 결합하여 순 보상(Reward)을 산출하고,
이를 강화학습(PPO/FinRL) 정책 재학습용 FeatureDataset으로 변환한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from investment_agent.platform.serialization import ContractError, parse_datetime
from investment_agent.research.rl.contracts import RewardConfig
from investment_agent.research.rl.environment import FeatureDataset


@dataclass(frozen=True)
class ExperienceRecord:
    """단일 시점의 (상태, 행동, 보상, 다음 상태 수익률) 경험 단위."""

    as_of_at: str
    symbols: tuple[str, ...]
    features: tuple[tuple[float, ...], ...]
    action_weights: tuple[float, ...]
    realized_returns: tuple[float, ...]
    benchmark_return: float
    turnover: float
    slippage_cost: float
    reward: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_at": self.as_of_at,
            "symbols": list(self.symbols),
            "features": [list(row) for row in self.features],
            "action_weights": list(self.action_weights),
            "realized_returns": list(self.realized_returns),
            "benchmark_return": self.benchmark_return,
            "turnover": self.turnover,
            "slippage_cost": self.slippage_cost,
            "reward": self.reward,
        }


class ExperienceCollector:
    """경험 수집 및 보상 산출기."""

    def __init__(self, reward_config: RewardConfig | None = None) -> None:
        self.reward_config = reward_config or RewardConfig()

    def calculate_reward(
        self,
        *,
        action_weights: Sequence[float],
        realized_returns: Sequence[float],
        benchmark_return: float,
        turnover: float = 0.0,
        slippage_cost: float = 0.0,
    ) -> float:
        """RewardConfig 공식에 따라 단일 거래일의 순 보상을 결정론적으로 계산한다."""
        if len(action_weights) != len(realized_returns):
            raise ContractError("weights and returns length mismatch")

        port_return = sum(float(w) * float(r) for w, r in zip(action_weights, realized_returns))
        alpha = port_return - float(benchmark_return)

        # R = w_ret * r_port + w_alpha * alpha - w_to * turnover - costs
        reward = (
            self.reward_config.return_weight * port_return
            + self.reward_config.alpha_weight * alpha
            - self.reward_config.turnover_penalty * float(turnover)
            - (self.reward_config.transaction_cost_rate * float(turnover) + float(slippage_cost))
        )
        return round(float(reward), 6)

    def create_record(
        self,
        *,
        as_of_at: str,
        symbols: Sequence[str],
        features_matrix: Sequence[Sequence[float]],
        action_weights: Sequence[float],
        realized_returns: Sequence[float],
        benchmark_return: float,
        turnover: float = 0.0,
        slippage_cost: float = 0.0,
    ) -> ExperienceRecord:
        """수집된 당일 데이터를 단일 ExperienceRecord로 묶고 보상을 계산한다."""
        iso_as_of = parse_datetime(as_of_at).isoformat()
        norm_syms = tuple(str(s).upper().strip() for s in symbols)
        if len(norm_syms) != len(features_matrix) or len(norm_syms) != len(action_weights):
            raise ContractError("dimensions of symbols, features, and weights must match")

        reward = self.calculate_reward(
            action_weights=action_weights,
            realized_returns=realized_returns,
            benchmark_return=benchmark_return,
            turnover=turnover,
            slippage_cost=slippage_cost,
        )

        return ExperienceRecord(
            as_of_at=iso_as_of,
            symbols=norm_syms,
            features=tuple(tuple(float(v) for v in row) for row in features_matrix),
            action_weights=tuple(float(w) for w in action_weights),
            realized_returns=tuple(float(r) for r in realized_returns),
            benchmark_return=float(benchmark_return),
            turnover=float(turnover),
            slippage_cost=float(slippage_cost),
            reward=reward,
        )

    def to_feature_dataset(
        self,
        records: Sequence[ExperienceRecord],
        feature_names: Sequence[str],
        feature_version: str = "v1-experience",
    ) -> FeatureDataset:
        """누적된 ExperienceRecord들을 PPO 트레이너가 즉시 학습 가능한 FeatureDataset으로 변환한다."""
        if not records:
            raise ContractError("records must not be empty")

        common_symbols = records[0].symbols
        as_of_values = tuple(r.as_of_at for r in records)
        f_names = tuple(str(n).strip() for n in feature_names)

        n_periods = len(records)
        n_assets = len(common_symbols)
        n_features = len(f_names)

        features = np.zeros((n_periods, n_assets, n_features), dtype=np.float32)
        forward_returns = np.zeros((n_periods, n_assets), dtype=np.float32)
        benchmark_returns = np.zeros(n_periods, dtype=np.float32)
        availability = np.ones((n_periods, n_assets), dtype=bool)

        for t, rec in enumerate(records):
            if rec.symbols != common_symbols:
                raise ContractError(f"symbol universe mismatch at period {t}")
            features[t] = np.array(rec.features, dtype=np.float32)
            forward_returns[t] = np.array(rec.realized_returns, dtype=np.float32)
            benchmark_returns[t] = float(rec.benchmark_return)

        return FeatureDataset(
            symbols=common_symbols,
            feature_names=f_names,
            as_of_values=as_of_values,
            features=features,
            forward_returns=forward_returns,
            benchmark_forward_returns=benchmark_returns,
            availability=availability,
            feature_version=feature_version,
        )


__all__ = [
    "ExperienceCollector",
    "ExperienceRecord",
]
