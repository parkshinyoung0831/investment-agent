"""학습·검증·OOS 구간이 겹치지 않는 walk-forward 분할."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from investment_agent.research.rl.contracts import RLSafetyError


@dataclass(frozen=True)
class WalkForwardSplit:
    train: tuple[int, int]
    validation: tuple[int, int]
    out_of_sample: tuple[int, int]

    @property
    def test(self) -> tuple[int, int]:
        """out_of_sample을 일반적인 train/validation/test 용어로 노출한다."""
        return self.out_of_sample


def make_walk_forward_splits(
    values: Sequence[object],
    *,
    train_size: int,
    validation_size: int,
    out_of_sample_size: int,
    step_size: int | None = None,
    embargo_size: int = 1,
) -> tuple[WalkForwardSplit, ...]:
    if min(train_size, validation_size, out_of_sample_size) < 1 or embargo_size < 0:
        raise ValueError("window sizes must be positive and embargo non-negative")
    step = out_of_sample_size if step_size is None else step_size
    if step < 1:
        raise ValueError("step_size must be positive")
    result: list[WalkForwardSplit] = []
    start = 0
    while True:
        train_end = start + train_size
        validation_start = train_end + embargo_size
        validation_end = validation_start + validation_size
        oos_start = validation_end + embargo_size
        oos_end = oos_start + out_of_sample_size
        if oos_end > len(values):
            break
        result.append(WalkForwardSplit(
            train=(start, train_end),
            validation=(validation_start, validation_end),
            out_of_sample=(oos_start, oos_end),
        ))
        start += step
    return tuple(result)


def _timestamp(value: object) -> datetime:
    text = str(value)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def make_purged_walk_forward_splits(
    as_of_values: Sequence[object],
    forward_end_values: Sequence[object],
    *,
    train_size: int,
    validation_size: int,
    test_size: int,
    step_size: int | None = None,
    embargo_size: int = 1,
) -> tuple[WalkForwardSplit, ...]:
    """미래 label 구간이 다음 window에 닿는 표본까지 제거한다."""
    if len(as_of_values) != len(forward_end_values):
        raise ValueError("as_of_values and forward_end_values must have equal length")
    as_of = tuple(_timestamp(value) for value in as_of_values)
    forward_end = tuple(_timestamp(value) for value in forward_end_values)
    if any(right <= left for left, right in zip(as_of, as_of[1:])):
        raise RLSafetyError("walk-forward as_of_values must be strictly increasing")
    if any(end <= start for start, end in zip(as_of, forward_end)):
        raise RLSafetyError("every forward label must end after its feature as_of")
    candidates = make_walk_forward_splits(
        as_of_values,
        train_size=train_size,
        validation_size=validation_size,
        out_of_sample_size=test_size,
        step_size=step_size,
        embargo_size=embargo_size,
    )
    result: list[WalkForwardSplit] = []
    for split in candidates:
        train_start, train_end = split.train
        validation_start, validation_end = split.validation
        test_start, test_end = split.test
        leaking_train = [
            sample for sample in range(train_start, train_end)
            if forward_end[sample] >= as_of[validation_start]
        ]
        if leaking_train:
            train_end = min(leaking_train)
        leaking_validation = [
            sample for sample in range(validation_start, validation_end)
            if forward_end[sample] >= as_of[test_start]
        ]
        if leaking_validation:
            validation_end = min(leaking_validation)
        if train_end <= train_start or validation_end <= validation_start:
            continue
        result.append(WalkForwardSplit(
            train=(train_start, train_end),
            validation=(validation_start, validation_end),
            out_of_sample=(test_start, test_end),
        ))
    if candidates and not result:
        raise RLSafetyError("all walk-forward windows were removed by label purging")
    return tuple(result)


__all__ = [
    "WalkForwardSplit",
    "make_purged_walk_forward_splits",
    "make_walk_forward_splits",
]
