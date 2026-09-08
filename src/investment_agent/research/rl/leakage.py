"""walk-forward 입력에서 미래 label 누수를 독립적으로 감사한다."""
from __future__ import annotations

from dataclasses import dataclass

from investment_agent.trading.contracts import parse_datetime
from investment_agent.research.rl.contracts import RLSafetyError
from investment_agent.research.rl.features import HistoricalTrainingSet
from investment_agent.research.training.splits import WalkForwardSplit


@dataclass(frozen=True)
class LeakageAuditReport:
    """검사한 window 수와 발견한 시간 경계 위반."""

    checked_windows: int
    issues: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.issues

    def assert_clean(self) -> None:
        if self.issues:
            raise RLSafetyError("future leakage audit failed: " + "; ".join(self.issues))


def audit_walk_forward_leakage(
    training_set: HistoricalTrainingSet,
    splits: tuple[WalkForwardSplit, ...],
) -> LeakageAuditReport:
    """train label이 validation에, validation label이 test에 걸치지 않는지 검사한다."""
    as_of = tuple(parse_datetime(value) for value in training_set.dataset.as_of_values)
    forward_end = tuple(parse_datetime(value) for value in training_set.forward_end_values)
    issues: list[str] = []
    for index, split in enumerate(splits):
        train_start, train_end = split.train
        validation_start, validation_end = split.validation
        test_start, test_end = split.test
        if not (
            0 <= train_start < train_end <= validation_start < validation_end
            <= test_start < test_end <= len(as_of)
        ):
            issues.append(f"window {index} has overlapping or out-of-range indices")
            continue
        leaking_train = [
            sample for sample in range(train_start, train_end)
            if forward_end[sample] >= as_of[validation_start]
        ]
        if leaking_train:
            issues.append(f"window {index} train labels cross validation: {leaking_train}")
        leaking_validation = [
            sample for sample in range(validation_start, validation_end)
            if forward_end[sample] >= as_of[test_start]
        ]
        if leaking_validation:
            issues.append(f"window {index} validation labels cross test: {leaking_validation}")
    return LeakageAuditReport(checked_windows=len(splits), issues=tuple(issues))


__all__ = ["LeakageAuditReport", "audit_walk_forward_leakage"]
