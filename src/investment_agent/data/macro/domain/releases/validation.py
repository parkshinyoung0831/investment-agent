"""자연키·시간축·변경 이력의 데이터 품질 규칙. DB 쓰기나 외부 호출은 하지 않는다."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _event(row: dict[str, Any]) -> tuple[str, str]:
    return str(row["series_id"]), str(row["ref_period"])


def _duplicates(values: Any) -> int:
    return sum(count-1 for count in Counter(values).values() if count>1)


def _timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return parsed.astimezone(timezone.utc)


def _temporal_errors(rows: list[dict[str, Any]], *, source_time: bool) -> int:
    invalid = 0
    for row in rows:
        try:
            collected = _timestamp(row["collected_at"])
            if source_time:
                invalid += int(_timestamp(row["effective_at"]) > collected + timedelta(minutes=5))
        except (KeyError, TypeError, ValueError):
            invalid += 1
    return invalid


def _same(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    try:
        return math.isclose(float(left),float(right),rel_tol=1e-12,abs_tol=1e-12)
    except (TypeError, ValueError):
        return False


def _unchanged(rows: list[dict[str, Any]], *, forecast: bool = False) -> int:
    streams: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key: tuple[Any, ...] = _event(row)
        if forecast:
            key += (row["measure_id"],row["forecast_kind"],row["source_code"])
        streams[key].append(row)
    duplicates = 0
    for stream in streams.values():
        valid = []
        for row in stream:
            try:
                valid.append((_timestamp(row["effective_at"]), _timestamp(row["collected_at"]), row))
            except (KeyError, TypeError, ValueError):
                continue  # 시각 오류는 temporal_order에서 별도로 센다.
        ordered = [item[2] for item in sorted(valid, key=lambda item: item[:2])]
        for before, after in zip(ordered,ordered[1:]):
            # 나중에 백필한 과거 상태 때문에 기존 최신 상태를 지우면 시스템 PIT가 손실된다.
            if _timestamp(before["collected_at"]) > _timestamp(after["collected_at"]):
                continue
            if (_same(before.get("value"), after.get("value"))
                    and before.get("time_precision") == after.get("time_precision")):
                duplicates += 1
    return duplicates


def validate_snapshot(snapshot: dict[str,list[dict[str,Any]]]) -> dict[str,Any]:
    """여섯 사실표의 관계와 값만 검사하고 actual 복제표를 요구하지 않는다."""
    series, measures = snapshot["series"], snapshot["measures"]
    events, schedules = snapshot["release_events"], snapshot["schedule_versions"]
    observations, forecasts = snapshot["observations"], snapshot["forecast_versions"]
    series_map = {str(row["series_id"]):row for row in series}
    measure_map = {str(row["measure_id"]):row for row in measures}
    event_keys = {_event(row) for row in events}
    primary = Counter(str(row["series_id"]) for row in measures if row.get("is_primary"))
    all_facts = [*schedules,*observations,*forecasts]
    errors = {
        "series_not_30": abs(len(series)-30), "measures_not_46": abs(len(measures)-46),
        "duplicate_series_identity": _duplicates(row["series_id"] for row in series),
        "duplicate_measure_identity": _duplicates(row["measure_id"] for row in measures),
        "duplicate_event": _duplicates(_event(row) for row in events),
        "duplicate_schedule_identity": _duplicates((*_event(row),row.get("collected_at")) for row in schedules),
        "duplicate_observation_identity": _duplicates((*_event(row),row.get("effective_at"),row.get("collected_at"))
                                                     for row in observations),
        "duplicate_forecast_identity": _duplicates((*_event(row),row.get("measure_id"),row.get("forecast_kind"),
                                                      row.get("source_code"),row.get("effective_at"),row.get("collected_at"))
                                                   for row in forecasts),
        "primary_measure_count": sum(primary[sid] != 1 for sid in series_map),
        "orphan_series": sum(str(row["series_id"]) not in series_map for row in [*events,*measures,*observations]),
        "orphan_event": sum(_event(row) not in event_keys for row in [*schedules,*forecasts]),
        "missing_source": sum(not str(row.get("source_code") or "").strip() for row in all_facts),
        "measure_mismatch": sum(str(row["measure_id"]).split(".")[0] != str(row["series_id"]) for row in [*measures,*forecasts])
                            + sum(row["measure_id"] not in measure_map for row in forecasts),
        "invalid_forecast_kind": sum(row["forecast_kind"] not in {"survey","nowcast","own_model"} for row in forecasts),
        "non_finite": 0,
        "temporal_order": _temporal_errors(schedules,source_time=False)
                          + _temporal_errors([*observations,*forecasts],source_time=True),
        "invalid_period": 0, "timezone_anomaly": 0,
        "invalid_time_precision": sum(row.get("time_precision") not in {"exact","date_only","collector_seen"} for row in [*observations,*forecasts]),
        "invalid_schedule_precision": sum(row.get("schedule_precision") not in {"exact","estimated","rule","date_only"} for row in schedules),
        "unchanged_observation_duplicate": _unchanged(observations),
        "unchanged_forecast_duplicate": _unchanged(forecasts,forecast=True),
    }
    for row, nullable in [*((row, False) for row in observations), *((row, True) for row in forecasts)]:
        try:
            if row.get("value") is None and nullable:
                continue
            errors["non_finite"] += int(not math.isfinite(float(row["value"])))
        except (KeyError,TypeError,ValueError):
            errors["non_finite"] += 1
    for row in [*events,*observations]:
        try:
            period = date.fromisoformat(str(row["ref_period"]))
            frequency = series_map.get(str(row["series_id"]),{}).get("frequency")
            errors["invalid_period"] += int((frequency in {"monthly","quarterly"} and period.day != 1)
                                           or (frequency == "quarterly" and period.month not in {1,4,7,10}))
        except (KeyError,TypeError,ValueError):
            errors["invalid_period"] += 1
    for row in schedules:
        try:
            zone = ZoneInfo(str(series_map[str(row["series_id"])]["timezone"]))
            local = _timestamp(row["scheduled_at"]).astimezone(zone)
            errors["timezone_anomaly"] += int(row["schedule_precision"] == "date_only" and local.strftime("%H:%M") != "12:00")
        except (KeyError,TypeError,ValueError,ZoneInfoNotFoundError):
            errors["timezone_anomaly"] += 1
    return {"ok":not any(errors.values()),"counts":{name:len(rows) for name,rows in snapshot.items()},"errors":errors}
