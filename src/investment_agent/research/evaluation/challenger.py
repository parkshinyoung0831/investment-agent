"""Champion과 Challenger의 비교 결과를 수동 승격 입력으로 만든다."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ChallengerPolicy:
    minimum_oos_excess_return_delta: float = 0.0
    minimum_oos_sharpe_delta: float = 0.0
    maximum_drawdown_increase: float = 0.02
    maximum_turnover_increase: float = 0.25
    minimum_shadow_days: int = 20
    minimum_paper_days: int = 30

    def __post_init__(self) -> None:
        for name in (
            "minimum_oos_excess_return_delta", "minimum_oos_sharpe_delta",
            "maximum_drawdown_increase", "maximum_turnover_increase",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.minimum_shadow_days < 0 or self.minimum_paper_days < 0:
            raise ValueError("minimum validation days must be non-negative")


@dataclass(frozen=True)
class ChallengerComparison:
    challenger_id: str
    champion_id: str
    eligible_for_manual_review: bool
    auto_promoted: bool
    violations: tuple[str, ...]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "violations": list(self.violations),
        }


def compare_challenger(
    *,
    challenger_id: str,
    champion_id: str,
    challenger: dict[str, float],
    champion: dict[str, float],
    shadow_days: int,
    paper_days: int,
    policy: ChallengerPolicy | None = None,
) -> ChallengerComparison:
    """OOS·shadow·paper 증거를 평가하되 자동 운영 승격은 항상 금지한다."""
    policy = policy or ChallengerPolicy()
    violations: list[str] = []
    if not str(challenger_id).strip() or not str(champion_id).strip():
        raise ValueError("challenger_id and champion_id are required")
    required = ("oos_excess_return", "oos_sharpe", "max_drawdown", "turnover")
    for name in required:
        for label, values in (("challenger", challenger), ("champion", champion)):
            value = values.get(name)
            if value is None or not math.isfinite(float(value)):
                violations.append(f"{label} {name} is missing or non-finite")
    if not violations:
        if challenger["oos_excess_return"] - champion["oos_excess_return"] < policy.minimum_oos_excess_return_delta:
            violations.append("challenger OOS excess return improvement is insufficient")
        if challenger["oos_sharpe"] - champion["oos_sharpe"] < policy.minimum_oos_sharpe_delta:
            violations.append("challenger OOS Sharpe improvement is insufficient")
        if challenger["max_drawdown"] - champion["max_drawdown"] > policy.maximum_drawdown_increase:
            violations.append("challenger drawdown increase exceeds limit")
        if challenger["turnover"] - champion["turnover"] > policy.maximum_turnover_increase:
            violations.append("challenger turnover increase exceeds limit")
    if shadow_days < policy.minimum_shadow_days:
        violations.append("shadow evidence is too short")
    if paper_days < policy.minimum_paper_days:
        violations.append("paper evidence is too short")
    # 이 함수는 promotion API가 아니라 사람 검토용 증거 생성기다.
    return ChallengerComparison(
        challenger_id=str(challenger_id).strip(),
        champion_id=str(champion_id).strip(),
        eligible_for_manual_review=not violations,
        auto_promoted=False,
        violations=tuple(violations),
        evidence={
            "challenger": dict(challenger),
            "champion": dict(champion),
            "shadow_days": shadow_days,
            "paper_days": paper_days,
            "policy": asdict(policy),
        },
    )


__all__ = ["ChallengerComparison", "ChallengerPolicy", "compare_challenger"]
