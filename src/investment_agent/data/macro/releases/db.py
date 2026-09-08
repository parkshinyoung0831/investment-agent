"""경제 발표의 v1 ``macro`` 저장소 경계.

발표 일정은 별도 ``econ_calendar`` 스키마가 아니라 macro owner가 소유한다. 이
모듈은 v1 표만 읽고 쓴다. 계산 가능한 release summary는 versioned 원자료에서
fail-closed하게 조립한다.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from investment_agent.config import load_config
from investment_agent.data.macro.domain.releases.identity import event_key, row_event_key, split_event_key
from investment_agent.data.macro.domain.releases.release_catalog import enrich_series, series_config
from investment_agent.data.macro.domain.releases.schedule import schedule_window
from investment_agent.platform.db.postgres import Database

SCHEMA_MACRO = "macro"
T_SERIES = "series"
T_MEASURES = "measures"
T_RELEASE_EVENTS = "release_events"
T_SCHEDULE_VERSIONS = "release_schedule_versions"
T_OBSERVATIONS = "economic_observations"
T_FORECAST_VERSIONS = "forecast_snapshots"
_UTC = timezone.utc
_database: Database | None = None
#: series master(code <-> key)는 seed로만 바뀌는 작은 카탈로그다. 행마다 다시 읽으면
#: 적재가 네트워크 왕복 수천 번이 된다.
_series_map_cache: tuple[dict[int, str], dict[str, int]] | None = None


def configure(database: Database) -> None:
    """진입점이 만든 v1 Database를 주입한다. 라이브러리는 연결을 만들지 않는다."""
    global _database, _series_map_cache
    _database = database
    _series_map_cache = None


def seed_catalog() -> None:
    """ETL 진입점에서만 작은 master를 등록한다. 읽기에는 부작용이 없다."""
    from investment_agent.data.macro.repository import MacroRepository
    from investment_agent.data.macro.domain.releases.release_catalog import (
        measure_definitions,
        series_definitions,
    )
    global _series_map_cache
    repository = MacroRepository(_db())
    catalog = series_definitions()
    repository.upsert_series(catalog)
    repository.upsert_measures(measure_definitions())
    _series_map_cache = None


def _db() -> Database:
    global _database
    if _database is None:
        _database = Database.from_config(load_config())
    return _database


def _table(name: str) -> Any:
    return _db().table(SCHEMA_MACRO, name)


def _select(factory: Any, *, order_by: str) -> list[dict[str, Any]]:
    rows = _db().select_paged(factory, order_by=order_by)
    if not rows:
        return []
    codes_by_key, keys_by_code = _series_maps()
    output = []
    for raw in rows:
        row = dict(raw)
        # series master 자체에는 code가 이미 있다. 여기서 다시 master를 조회하면
        # ``_series_rows -> _select -> _series_maps`` 재귀가 생긴다.
        if "series_key" in row and "series_code" not in row:
            code = codes_by_key.get(int(row["series_key"]))
            if code is None:
                raise ValueError("macro fact references an unknown series_key")
            row["series_id"] = code
        elif "series_code" in row:
            row["series_id"] = str(row["series_code"])
        if "observation_date" in row:
            row["ref_period"] = row["observation_date"]
        if "vintage_at" in row:
            row["effective_at"] = row["vintage_at"]
        if "available_at" in row:
            row["collected_at"] = row["available_at"]
        output.append(row)
    return output


def _series_maps() -> tuple[dict[int, str], dict[str, int]]:
    global _series_map_cache
    if _series_map_cache is None:
        rows = _db().select_paged(
            lambda: _table(T_SERIES).select("series_key,series_code"), order_by="series_code"
        )
        codes_by_key = {int(row["series_key"]): str(row["series_code"]) for row in rows}
        _series_map_cache = (codes_by_key, {code: key for key, code in codes_by_key.items()})
    return _series_map_cache


def _series_key(series_id: str) -> int:
    global _series_map_cache
    _codes, keys = _series_maps()
    if str(series_id) not in keys:
        # 캐시가 이 프로세스가 아닌 곳에서 늘어난 catalog보다 낡았을 수 있다.
        # 없다고 단정하기 전에 한 번만 다시 읽는다.
        _series_map_cache = None
        _codes, keys = _series_maps()
    try:
        return keys[str(series_id)]
    except KeyError as exc:
        raise ValueError(f"macro series is not seeded: {series_id}") from exc


def _utc_iso(value: datetime | str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        raise ValueError("ECON timestamps must be timezone-aware")
    return parsed.astimezone(_UTC).isoformat()


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("ECON value must be finite")
    return number


def _times(raw: dict[str, Any], now: datetime) -> dict[str, Any]:
    collected = _utc_iso(raw.get("collected_at") or now)
    effective = _utc_iso(raw.get("effective_at") or raw.get("as_of") or collected)
    if datetime.fromisoformat(effective) > datetime.fromisoformat(collected) + timedelta(minutes=5):
        raise ValueError("effective_at cannot be later than collected_at")
    return {"effective_at": effective, "collected_at": collected}


def _precision(raw: dict[str, Any]) -> str:
    if raw.get("time_precision"):
        precision = str(raw["time_precision"])
    elif (raw.get("provenance") or {}).get("effective_basis") == "collector_seen_at":
        precision = "collector_seen"
    else:
        precision = {"timestamp": "exact", "date_only": "date_only"}.get(str(raw.get("availability_precision")), "collector_seen")
    if precision not in {"exact", "date_only", "collector_seen"}:
        raise ValueError("invalid ECON time_precision")
    return precision


def _series_rows() -> list[dict[str, Any]]:
    rows = _select(
        lambda: _table(T_SERIES).select(
            "series_key,series_code,domain,name_ko,source_code,provider_series_code,frequency,unit,category,country,series_kind,timezone"
        ).eq("domain", "economic_release"),
        order_by="series_code",
    )
    return [enrich_series({**row, "source": str(row.get("source_code") or "")}) for row in rows]


def enabled_series(*, include_unsupported: bool = True) -> list[dict[str, Any]]:
    rows = _series_rows()
    return rows if include_unsupported else [row for row in rows if row["collection_status"] != "unsupported"]


def collectible_series() -> list[dict[str, Any]]:
    return enabled_series(include_unsupported=False)


def measures_by_series() -> dict[str, list[dict[str, Any]]]:
    frequencies = {row["series_id"]: row["frequency"] for row in enabled_series()}
    rows = _select(lambda: _table(T_MEASURES).select("*"), order_by="measure_id")
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        output[str(row["series_id"])].append({**row, "code": str(row["measure_id"]).split(".", 1)[1], "frequency": frequencies.get(str(row["series_id"]))})
    return dict(output)


def primary_measures() -> dict[str, dict[str, Any]]:
    rows = _select(lambda: _table(T_MEASURES).select("*").eq("is_primary", True), order_by="measure_id")
    return {str(row["series_id"]): row for row in rows}


def _latest_by(rows: list[dict[str, Any]], key: tuple[str, ...], *, as_of: datetime | None = None) -> dict[tuple[Any, ...], dict[str, Any]]:
    output: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        if as_of is not None and row.get("collected_at"):
            if datetime.fromisoformat(str(row["collected_at"]).replace("Z", "+00:00")) > as_of:
                continue
        identity = tuple(row.get(item) for item in key)
        before = output.get(identity)
        marker = (str(row.get("effective_at") or ""), str(row.get("collected_at") or ""))
        old_marker = (str(before.get("effective_at") or ""), str(before.get("collected_at") or "")) if before else ("", "")
        if before is None or marker > old_marker:
            output[identity] = row
    return output


def release_index(series_ids: list[str] | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    allowed = set(series_ids or [])
    rows = _select(lambda: _table(T_SCHEDULE_VERSIONS).select("*"), order_by="series_key,ref_period,collected_at")
    latest = _latest_by(rows, ("series_id", "ref_period"))
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for key, row in latest.items():
        if allowed and str(key[0]) not in allowed:
            continue
        source = str(row.get("source_code") or "")
        output[(str(key[0]), str(key[1]))] = {**row, "source": source, "schedule_source": source, "schedule_confidence": row.get("schedule_precision")}
    return output


def upsert_releases(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    if not rows:
        return {}
    now = datetime.now(_UTC)
    existing = release_index(sorted({str(row["series_id"]) for row in rows}))
    events = []
    for raw in rows:
        sid, period = split_event_key(row_event_key(raw))
        source = str(raw["schedule_source"])
        if not source:
            raise ValueError("macro release has no schedule source")
        events.append({"series_key": _series_key(sid), "ref_period": period, "source_code": source})
    _db().upsert(schema=SCHEMA_MACRO, table=T_RELEASE_EVENTS, rows=events, on_conflict="series_key,ref_period")
    payloads = []
    for raw in rows:
        sid, period = split_event_key(row_event_key(raw))
        before = existing.get((sid, period))
        source = str(raw["schedule_source"])
        if before and datetime.fromisoformat(_utc_iso(before["scheduled_at"])) < now and source != "alfred_first_print" and not raw.get("is_cancelled"):
            continue
        if not source:
            raise ValueError("macro release has no schedule source")
        payloads.append({
            "series_key": _series_key(sid), "ref_period": period, "scheduled_at": _utc_iso(raw["scheduled_at"]),
            "schedule_precision": str(raw.get("schedule_precision") or raw["schedule_confidence"]),
            "source_code": source,
            "is_cancelled": bool(raw.get("is_cancelled") or raw.get("status") == "cancelled"),
            "collected_at": _times(raw, now)["collected_at"],
        })
    _db().upsert(schema=SCHEMA_MACRO, table=T_SCHEDULE_VERSIONS, rows=payloads, on_conflict="series_key,ref_period,collected_at")
    return release_index(sorted({str(row["series_id"]) for row in rows}))


def append_observations(rows: list[dict[str, Any]]) -> int:
    now = datetime.now(_UTC)
    payloads = []
    for raw in rows:
        sid, period = split_event_key(row_event_key(raw))
        expected = (series_config(sid)["source_contract"].get("actual") or {}).get("unit")
        if raw.get("unit") is not None and expected != raw["unit"]:
            raise ValueError(f"{sid}: raw unit does not match configured base unit")
        source = str(raw.get("source") or raw["provider"])
        if not source:
            raise ValueError(f"{sid}: observation has no source")
        times = _times(raw, now)
        payloads.append({"series_key": _series_key(sid), "observation_date": period, "value": _finite(raw["value"]), "source_code": source, "time_precision": _precision(raw), "vintage_at": times["effective_at"], "available_at": times["collected_at"], "revision_no": int(raw.get("revision_no") or 0)})
    payloads.sort(key=lambda row: (row["series_key"], row["observation_date"], row["vintage_at"], row["available_at"]))
    return _db().upsert(schema=SCHEMA_MACRO, table=T_OBSERVATIONS, rows=payloads, on_conflict="series_key,observation_date,vintage_at,available_at")


def append_forecasts(rows: list[dict[str, Any]]) -> int:
    now = datetime.now(_UTC)
    payloads = []
    for raw in rows:
        sid, period = split_event_key(row_event_key(raw))
        measure = str(raw["measure_id"])
        if not measure.startswith(f"{sid}."):
            raise ValueError("forecast measure and event series must match")
        if raw["forecast_kind"] not in {"survey", "nowcast", "own_model"}:
            raise ValueError("invalid forecast_kind")
        source = str(raw["source"])
        if not source:
            raise ValueError("forecast has no source")
        times = _times(raw, now)
        payloads.append({"series_key": _series_key(sid), "ref_period": period, "measure_id": measure, "forecast_kind": raw["forecast_kind"], "source_code": source, "value": None if raw["value"] is None else _finite(raw["value"]), "time_precision": _precision(raw), **times})
    payloads.sort(key=lambda row: (row["series_key"], row["ref_period"], row["measure_id"], row["forecast_kind"], row["source_code"], row["effective_at"], row["collected_at"]))
    return _db().upsert(schema=SCHEMA_MACRO, table=T_FORECAST_VERSIONS, rows=payloads, on_conflict="series_key,ref_period,measure_id,forecast_kind,source_code,effective_at,collected_at")


#: `_summary_rows` 한 행이 담는 것. 소비자(evidence·reporting)가 읽는 키가 실제로
#: 여기 있는지를 검사가 잰다 — 예전에 소비자가 `record_kind`라는, 이 계약에 없는
#: 키로 행을 갈랐고 그 KeyError는 통합 점검에서만 드러났다.
SUMMARY_ROW_KEYS = frozenset({
    "event_key", "series_id", "ref_period", "series_name_ko", "category", "unit",
    "frequency", "scheduled_at", "schedule_confidence", "status",
    "first_actual_at", "first_actual_value", "latest_actual_value",
    "closing_survey_value", "closing_nowcast_value", "closing_own_model_value",
    "market_surprise", "revision", "model_error", "series_kind", "source",
})


def _summary_rows(*, start: datetime, end: datetime, as_of: datetime) -> list[dict[str, Any]]:
    series = {str(row["series_id"]): row for row in _series_rows() if row["domain"] == "economic_release"}
    events = _select(lambda: _table(T_RELEASE_EVENTS).select("series_key,ref_period").gte("ref_period", start.date().isoformat()).lte("ref_period", end.date().isoformat()), order_by="series_key,ref_period")
    schedules = _latest_by(_select(lambda: _table(T_SCHEDULE_VERSIONS).select("*"), order_by="series_key,ref_period,collected_at"), ("series_id", "ref_period"), as_of=as_of)
    observations = _select(lambda: _table(T_OBSERVATIONS).select("*"), order_by="series_key,observation_date,vintage_at,available_at")
    obs_by_event: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        obs_by_event[(str(row["series_id"]), str(row["ref_period"]))].append(row)
    forecasts = _select(lambda: _table(T_FORECAST_VERSIONS).select("*"), order_by="series_key,ref_period,measure_id,forecast_kind,effective_at,collected_at")
    forecast_by_event: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in forecasts:
        forecast_by_event[(str(row["series_id"]), str(row["ref_period"]))].append(row)
    output = []
    for event in events:
        key = (str(event["series_id"]), str(event["ref_period"]))
        setting, schedule_row = series.get(key[0]), schedules.get(key)
        if setting is None or schedule_row is None:
            continue
        actuals = [row for row in obs_by_event[key] if datetime.fromisoformat(str(row["collected_at"]).replace("Z", "+00:00")) <= as_of]
        actuals.sort(key=lambda row: (str(row.get("effective_at")), str(row.get("collected_at"))))
        first, latest = (actuals[0] if actuals else None), (actuals[-1] if actuals else None)
        scheduled_at = _utc_iso(schedule_row["scheduled_at"])
        status = "cancelled" if schedule_row.get("is_cancelled") else ("released" if latest else "not_available_yet" if datetime.fromisoformat(scheduled_at) <= as_of else "scheduled")
        by_kind: dict[str, dict[str, Any]] = {}
        for row in forecast_by_event[key]:
            if datetime.fromisoformat(str(row["collected_at"]).replace("Z", "+00:00")) <= as_of:
                by_kind[str(row["forecast_kind"])] = row
        actual_value = latest.get("value") if latest else None
        survey_value = by_kind.get("survey", {}).get("value") if by_kind.get("survey") else None
        yield_row = {
            "event_key": event_key(key[0], key[1]), "series_id": key[0], "ref_period": key[1], "series_name_ko": setting.get("name_ko"), "category": setting.get("category"), "unit": setting.get("unit"), "frequency": setting.get("frequency"), "scheduled_at": scheduled_at, "schedule_confidence": schedule_row.get("schedule_precision"), "status": status, "first_actual_at": first.get("effective_at") if first else None, "first_actual_value": first.get("value") if first else None, "latest_actual_value": actual_value, "closing_survey_value": survey_value, "closing_nowcast_value": by_kind.get("nowcast", {}).get("value") if by_kind.get("nowcast") else None, "closing_own_model_value": by_kind.get("own_model", {}).get("value") if by_kind.get("own_model") else None, "market_surprise": actual_value - survey_value if actual_value is not None and survey_value is not None else None, "revision": actual_value - first.get("value") if actual_value is not None and first and first.get("value") is not None else None,
        }
        yield_row["model_error"] = (actual_value - yield_row["closing_own_model_value"] if actual_value is not None and yield_row["closing_own_model_value"] is not None else None)
        yield_row["series_kind"] = setting.get("series_kind")
        yield_row["source"] = setting.get("source")
        output.append(yield_row)
    if output and set(output[0]) != SUMMARY_ROW_KEYS:
        raise ValueError("macro release summary row does not match its declared contract")
    return output


def calendar_window(*, start: datetime, end: datetime, as_of: datetime | None = None) -> list[dict[str, Any]]:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("calendar bounds must be timezone-aware")
    return _summary_rows(start=start, end=end, as_of=as_of or datetime.now(_UTC))


def upcoming(days: int = 14, *, include_cancelled: bool = False) -> list[dict[str, Any]]:
    now = datetime.now(_UTC)
    statuses = {"scheduled", "not_available_yet", "cancelled"} if include_cancelled else {"scheduled", "not_available_yet"}
    return [row for row in calendar_window(start=now, end=now + timedelta(days=max(1, min(days, 365)))) if row.get("status") in statuses]


def releases_within(*, start: datetime, end: datetime, statuses: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    rows = calendar_window(start=start, end=end)
    return rows if statuses is None else [row for row in rows if row.get("status") in statuses]


def due_releases(*, now: datetime | None = None, limit: int = 50) -> list[dict[str, Any]]:
    now = now or datetime.now(_UTC)
    rows = calendar_window(start=now - timedelta(days=4), end=now + timedelta(microseconds=1), as_of=now)
    due = []
    for row in rows:
        if row.get("status") != "not_available_yet":
            continue
        extra = (series_config(str(row["series_id"])).get("source_contract", {}).get("watch") or {}).get("additional_window_hours", 0)
        if datetime.fromisoformat(_utc_iso(row["scheduled_at"])) >= now - schedule_window(str(row.get("schedule_confidence") or "exact")) - timedelta(hours=float(extra)):
            due.append(row)
    return due[:max(1, min(int(limit), 200))]


def release_summary(key: str) -> dict[str, Any] | None:
    sid, period = split_event_key(key)
    center = datetime.fromisoformat(f"{period}T00:00:00+00:00")
    return next((row for row in calendar_window(start=center - timedelta(days=1), end=center + timedelta(days=1)) if row_event_key(row) == key), None)


def summaries_for(event_keys: set[str]) -> dict[str, dict[str, Any]]:
    if not event_keys:
        return {}
    periods = [split_event_key(key)[1] for key in event_keys]
    start = datetime.fromisoformat(f"{min(periods)}T00:00:00+00:00") - timedelta(days=1)
    end = datetime.fromisoformat(f"{max(periods)}T00:00:00+00:00") + timedelta(days=1)
    wanted = set(event_keys)
    return {row_event_key(row): row for row in calendar_window(start=start, end=end) if row_event_key(row) in wanted}


def primary_history(series_id: str, limit: int = 60) -> list[float]:
    rows = _select(lambda: _table(T_OBSERVATIONS).select("series_key,observation_date,value,vintage_at,available_at").eq("series_key", _series_key(series_id)), order_by="observation_date,vintage_at,available_at")
    latest = _latest_by(rows, ("ref_period",))
    return [float(row["value"]) for row in sorted(latest.values(), key=lambda row: str(row["ref_period"]))][-max(1, min(limit, 500)):]


def measure_history(series_id: str, measure_id: str, limit: int = 60) -> list[float]:
    if not measure_id.startswith(f"{series_id}."):
        raise ValueError("history measure and series must match")
    rows = [row for row in _select(lambda: _table(T_FORECAST_VERSIONS).select("series_key,ref_period,value,effective_at,collected_at").eq("series_key", _series_key(series_id)).eq("measure_id", measure_id), order_by="ref_period,effective_at,collected_at") if row.get("value") is not None]
    latest = _latest_by(rows, ("ref_period",))
    return [float(row["value"]) for row in sorted(latest.values(), key=lambda row: str(row["ref_period"]))][-max(1, min(limit, 500)):]


def forecast_history(key: str) -> list[dict[str, Any]]:
    sid, period = split_event_key(key)
    return _select(lambda: _table(T_FORECAST_VERSIONS).select("*").eq("series_key", _series_key(sid)).eq("ref_period", period), order_by="measure_id,forecast_kind,source_code,effective_at,collected_at")


def prune_release_snapshots(recent_days: int | None = None) -> dict[str, int]:
    """발표가 끝난 회차의 일정·예상 스냅샷을 계약이 읽는 한 건씩만 남긴다."""
    from investment_agent.data.macro.repository import PRUNE_RECENT_DAYS, MacroRepository

    return MacroRepository(_db()).prune_release_snapshots(
        PRUNE_RECENT_DAYS if recent_days is None else recent_days
    )


def validation_snapshot() -> dict[str, list[dict[str, Any]]]:
    specs = {
        "series": (T_SERIES, "series_code"),
        "measures": (T_MEASURES, "measure_id"),
        "release_events": (T_RELEASE_EVENTS, "series_key,ref_period"),
        "schedule_versions": (T_SCHEDULE_VERSIONS, "series_key,ref_period,collected_at"),
        "observations": (T_OBSERVATIONS, "series_key,observation_date,vintage_at,available_at"),
        "forecast_versions": (T_FORECAST_VERSIONS, "series_key,ref_period,measure_id,forecast_kind,source_code,effective_at,collected_at"),
    }
    return {
        name: _select(lambda table=table: _table(table).select("*"), order_by=order)
        for name, (table, order) in specs.items()
    }


def counts() -> dict[str, int]:
    return {table: len(rows) for table, rows in validation_snapshot().items()}


def select_snapshot_rows(*, as_of_at: datetime, lookback_days: int = 14, lookahead_days: int = 30) -> list[dict[str, Any]]:
    if as_of_at.tzinfo is None:
        raise ValueError("as_of_at must include timezone")
    return calendar_window(start=as_of_at - timedelta(days=lookback_days), end=as_of_at + timedelta(days=lookahead_days), as_of=as_of_at)
