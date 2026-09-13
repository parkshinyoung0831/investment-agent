"""상태가 바뀔 때만 새 버전을 남기는 판정. 예상치·발표 일정·애널리스트 커버리지가 쓴다.

같은 논리 키(종목·대상 기간·원천 등)의 **직전 저장 상태**와 비교한다. 전체 DISTINCT가
아니라 인접 비교라서 값이 A→B→A로 돌아온 사건이 세 버전으로 남는다. 같은 상태를 다시
보면 새 행 대신 그 버전의 `last_seen_at`만 옮겨 "값이 안 바뀜"과 "수집 실패"를 구별한다.

원천이 말하는 날짜가 저장된 최신 버전보다 앞선 행(늦게 도착한 과거 자료)은 압축하지 않고
그 날짜의 행으로만 넣는다. 순서를 뒤섞어 비교하면 이미 저장된 이력을 잘못 합친다.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class VersionPlan:
    new_rows: list[dict] = field(default_factory=list)
    confirmations: list[dict] = field(default_factory=list)


def _normalized(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 10) if math.isfinite(float(value)) else None
    text = str(value)
    try:
        return round(float(text), 10)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return text


def same_state(left: dict, right: dict, value_fields: Sequence[str]) -> bool:
    return all(_normalized(left.get(f)) == _normalized(right.get(f)) for f in value_fields)


def plan_versions(
    candidates: Iterable[dict],
    stored: Iterable[dict],
    *,
    key_fields: Sequence[str],
    value_fields: Sequence[str],
    date_field: str = "snapshot_date",
    now: datetime,
) -> VersionPlan:
    """새로 넣을 버전과 last_seen_at만 옮길 기존 버전을 가른다."""
    def key(row: dict) -> tuple:
        return tuple(str(row.get(f)) for f in key_fields)

    latest: dict[tuple, dict] = {}
    for row in stored:
        current = latest.get(key(row))
        if current is None or (str(row[date_field]), str(row.get("collected_at") or "")) > (
            str(current[date_field]), str(current.get("collected_at") or "")
        ):
            latest[key(row)] = row

    plan = VersionPlan()
    confirmed: dict[tuple, dict] = {}
    for candidate in sorted(candidates, key=lambda row: (key(row), str(row[date_field]))):
        previous = latest.get(key(candidate))
        if previous is not None and str(candidate[date_field]) < str(previous[date_field]):
            plan.new_rows.append(candidate)  # 늦게 도착한 과거 자료 — 그 날짜의 행으로만 둔다
            continue
        if previous is not None and same_state(candidate, previous, value_fields):
            if "collected_at" in previous and previous.get(date_field) is not None:
                seen = max(now, _as_datetime(previous.get("collected_at")) or now)
                confirmed[key(candidate)] = {**previous, "last_seen_at": seen.isoformat()}
            continue
        plan.new_rows.append(candidate)
        latest[key(candidate)] = candidate
        confirmed.pop(key(candidate), None)
    plan.confirmations.extend(confirmed.values())
    return plan


def _as_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


__all__ = ["VersionPlan", "plan_versions", "same_state"]
