"""수익률 예측의 단일 구간 및 OOS stability metric."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class EvaluationScore:
    rmse: float
    mae: float
    direction_accuracy: float
    rank_correlation: float
    sample_count: int
    excess_return: float | None = None
    max_drawdown: float | None = None
    sharpe: float | None = None
    turnover: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_predictions(actual: Sequence[float], predicted: Sequence[float]) -> EvaluationScore:
    if len(actual) != len(predicted) or not actual:
        raise ValueError("actual and predicted must have the same non-empty length")
    pairs = [(float(left), float(right)) for left, right in zip(actual, predicted, strict=True)]
    if any(not math.isfinite(left) or not math.isfinite(right) for left, right in pairs):
        raise ValueError("evaluation values must be finite")
    residuals = [right - left for left, right in pairs]
    actual_rank = {value: index for index, value in enumerate(sorted({left for left, _ in pairs}))}
    predicted_rank = {value: index for index, value in enumerate(sorted({right for _, right in pairs}))}
    actual_ranks = [actual_rank[left] for left, _ in pairs]
    predicted_ranks = [predicted_rank[right] for _, right in pairs]
    rank_corr = 0.0
    if len(set(actual_ranks)) > 1 and len(set(predicted_ranks)) > 1:
        actual_mean = sum(actual_ranks) / len(actual_ranks)
        predicted_mean = sum(predicted_ranks) / len(predicted_ranks)
        numerator = sum((left - actual_mean) * (right - predicted_mean) for left, right in zip(actual_ranks, predicted_ranks, strict=True))
        denominator = math.sqrt(
            sum((left - actual_mean) ** 2 for left in actual_ranks)
            * sum((right - predicted_mean) ** 2 for right in predicted_ranks)
        )
        rank_corr = numerator / denominator if denominator else 0.0
    return EvaluationScore(
        rmse=math.sqrt(sum(value * value for value in residuals) / len(residuals)),
        mae=sum(abs(value) for value in residuals) / len(residuals),
        direction_accuracy=sum((left >= 0) == (right >= 0) for left, right in pairs) / len(pairs),
        rank_correlation=rank_corr,
        sample_count=len(pairs),
    )


def is_stable_oos(scores: Sequence[EvaluationScore], *, min_direction_accuracy: float = 0.50) -> bool:
    """모든 window가 Naive 수준의 방향성과 finite metric을 유지하는지 확인한다."""
    if not scores or not 0.0 <= min_direction_accuracy <= 1.0:
        return False
    return all(
        score.sample_count > 0
        and score.direction_accuracy >= min_direction_accuracy
        and all(math.isfinite(float(value)) for value in (score.rmse, score.mae, score.rank_correlation))
        for score in scores
    )


__all__ = ["EvaluationScore", "evaluate_predictions", "is_stable_oos"]
