"""미래 label 구간을 purge하는 시계열 walk-forward 분할."""
from __future__ import annotations

from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.research.training.splits import (
    WalkForwardSplit,
    make_walk_forward_splits,
    make_purged_walk_forward_splits,
)
from investment_agent.research.datasets import ResearchDataset


def make_purged_splits(*args, **kwargs):
    """feature 시점과 forward label 종료 시점을 함께 검사한다."""
    return make_purged_walk_forward_splits(*args, **kwargs)


def dataset_periods(dataset: ResearchDataset) -> tuple[tuple[str, str, int, int], ...]:
    """as_of 시점마다 (as_of, 최대 forward_end, 시작행, 끝행)을 만든다.

    `build_research_dataset`이 행을 (as_of_at, ticker)로 정렬하므로 한 시점의 행은
    항상 연속 구간이다. forward_end는 그 시점 행 중 가장 늦은 값을 쓴다 — 하나라도
    다음 구간에 닿으면 그 시점 전체가 오염된 것으로 본다.
    """
    periods: list[tuple[str, str, int, int]] = []
    for index, (row, label) in enumerate(zip(dataset.rows, dataset.labels)):
        if periods and periods[-1][0] == row.as_of_at:
            as_of, forward_end, start, _ = periods[-1]
            latest = max(forward_end, label.forward_end_at, key=parse_datetime)
            periods[-1] = (as_of, latest, start, index + 1)
            continue
        if periods and parse_datetime(row.as_of_at) <= parse_datetime(periods[-1][0]):
            raise ContractError("research dataset rows are not ordered by as_of_at")
        periods.append((row.as_of_at, label.forward_end_at, index, index + 1))
    return tuple(periods)


def purged_row_splits(
    dataset: ResearchDataset,
    *,
    train_ratio: float = 0.60,
    validation_ratio: float = 0.20,
    embargo_periods: int = 1,
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """행 번호가 아니라 **시점** 경계로 나누고 label이 겹치는 시점을 잘라낸다.

    단순 60/20/20 행 절단은 두 가지를 동시에 어긴다. 같은 날짜의 종목들이 train과
    validation으로 쪼개지고(cross-section 누수), 5거래일 horizon이면 train 마지막
    시점의 label이 validation 구간 안에서 확정된다(look-ahead 누수). 여기서는 시점
    단위로 나눈 뒤 이미 검증된 `make_purged_walk_forward_splits`가 두 경계를 모두
    검사하게 하고, 그 결과를 다시 행 구간으로 되돌린다.
    """
    if not 0.0 < train_ratio < 1.0 or not 0.0 < validation_ratio < 1.0:
        raise ValueError("train_ratio and validation_ratio must be between 0 and 1")
    if train_ratio + validation_ratio >= 1.0:
        raise ValueError("train_ratio + validation_ratio must leave room for a test split")
    if embargo_periods < 0:
        raise ValueError("embargo_periods must not be negative")
    periods = dataset_periods(dataset)
    total = len(periods)
    train_size = max(1, int(total * train_ratio))
    validation_size = max(1, int(total * validation_ratio))
    test_size = total - train_size - validation_size - 2 * embargo_periods
    if test_size < 1:
        raise ContractError(
            f"dataset has {total} point-in-time periods; not enough for a purged "
            f"{train_ratio:.0%}/{validation_ratio:.0%} split with "
            f"{embargo_periods} embargo period(s)"
        )
    splits = make_purged_walk_forward_splits(
        [period[0] for period in periods],
        [period[1] for period in periods],
        train_size=train_size,
        validation_size=validation_size,
        test_size=test_size,
        step_size=max(1, test_size),
        embargo_size=embargo_periods,
    )
    if not splits:
        raise ContractError("no purged walk-forward window survived label purging")
    split = splits[0]

    def _rows(bounds: tuple[int, int]) -> tuple[int, int]:
        start, end = bounds
        return periods[start][2], periods[end - 1][3]

    return _rows(split.train), _rows(split.validation), _rows(split.test)


__all__ = [
    "WalkForwardSplit",
    "dataset_periods",
    "make_purged_splits",
    "make_walk_forward_splits",
    "purged_row_splits",
]
