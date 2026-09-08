"""PPO의 초기 범위를 allocation·timing으로 제한한다."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from investment_agent.research.rl.contracts import RewardConfig
from investment_agent.research.rl.experiment import run_ppo_experiment


@dataclass(frozen=True)
class PPOAllocationTimingSpec:
    """PPO가 broker나 종목 수량을 직접 만들지 않는 연구 명세."""

    role: str = "allocation_timing"
    action: str = "target_weights"
    reward: str = "return-alpha-drawdown-volatility-turnover-cost-concentration"
    reward_config: RewardConfig = RewardConfig()
    research_only_until_promotion: bool = True

    def __post_init__(self) -> None:
        if self.role != "allocation_timing" or self.action not in {"target_weights", "weight_adjustments"}:
            raise ValueError("PPO role must remain allocation_timing with weight actions")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "reward_config": asdict(self.reward_config)}


__all__ = ["PPOAllocationTimingSpec", "RewardConfig", "run_ppo_experiment"]
