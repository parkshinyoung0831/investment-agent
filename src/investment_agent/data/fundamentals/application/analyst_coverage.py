"""애널리스트 커버리지 관측값의 변경 여부를 판정한다."""
from __future__ import annotations

_VALUE_COLUMNS = (
    "target_mean",
    "target_median",
    "target_high",
    "target_low",
    "strong_buy",
    "buy",
    "hold",
    "sell",
    "strong_sell",
)


def changed_analyst_snapshots(
    snapshots: list[dict],
    latest_snapshots: list[dict],
) -> list[dict]:
    """직전 값과 다른 관측만 남긴다.

    날짜는 자연키에 포함되지만 값 비교에서는 제외한다. 같은 값의 일별 행을
    만들면 이력이 아니라 중복이므로, 목표·의견 중 하나라도 달라진 날만 보존한다.
    """
    latest_by_key = {
        _snapshot_key(snapshot): snapshot
        for snapshot in latest_snapshots
    }
    return [
        snapshot
        for snapshot in snapshots
        if _is_changed(snapshot, latest_by_key.get(_snapshot_key(snapshot)))
    ]


def _snapshot_key(snapshot: dict) -> tuple[str, str]:
    return (
        str(snapshot.get("ticker") or "").upper(),
        str(snapshot.get("source") or "yfinance"),
    )


def _is_changed(candidate: dict, previous: dict | None) -> bool:
    if previous is None:
        return True
    return any(
        candidate.get(column) != previous.get(column)
        for column in _VALUE_COLUMNS
    )
