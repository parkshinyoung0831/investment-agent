"""경제발표 일정·예상값·원자료 변경을 수집하는 ETL. actual은 DB 조회 계층이 계산한다."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from investment_agent.platform.logging import get_logger
from investment_agent.operations.runtime import notify_ops
from investment_agent.operations.monitoring.incidents import (
    build_incident_embed,
    build_runtime_incident,
    current_github_run_url,
)
from investment_agent.data.macro.domain.releases import baseline, normalize, schedule
from investment_agent.data.macro.domain.releases.identity import row_event_key
from investment_agent.data.macro.releases import BASELINE_WINDOW, EXPECTATION_HORIZON_DAYS, db
from investment_agent.data.macro.infrastructure.releases.sources import actuals, fomc_calendar, fred_calendar, nowcast

log = get_logger(__name__)
RECENT_OVERLAP_DAYS = 45
# 발표 일정과 관측 시각이 크게 어긋나면 데이터를 버리지 않고 별도 품질 이슈로 보고한다.
FIRST_ACTUAL_SCHEDULE_TOLERANCE = timedelta(days=7)


def sync_schedules(*, today: date, horizon_days: int, series_ids: set[str] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """future schedule만 source별로 동기화한다. actual fetch와 섞지 않는다."""
    settings = db.enabled_series()
    if series_ids is not None:
        settings = [row for row in settings if row["series_id"] in series_ids]
    end = today + timedelta(days=horizon_days)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    fred_groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    fomc_settings: list[dict[str, Any]] = []

    for setting in settings:
        if setting["collection_status"] == "unsupported":
            continue
        contract = setting.get("source_contract") or {}
        schedule_contract = contract.get("schedule") or {}
        source = str(setting.get("schedule_provider") or "")
        if source == "unsupported":
            # 원자료를 읽을 수 있어도 허용된 일정 출처가 없으면 발표 이벤트를 만들지 않는다.
            continue
        if source == "fred_release_calendar":
            release_id = schedule_contract.get("release_id")
            if release_id is None:
                failures.append(_failure(setting, "schedule", "missing FRED release id", "ScheduleContractError"))
            else:
                fred_groups[int(release_id)].append(setting)
            continue
        if source == "fomc_official_calendar":
            fomc_settings.append(setting)
            continue
        try:
            if source == "official_rule":
                dates = schedule.rule_dates(str(schedule_contract["rule"]), start=today, end=end)
            elif source == "official_calendar":
                dates = schedule.official_calendar_dates(str(setting["series_id"]), start=today, end=end)
            else:
                raise schedule.ScheduleContractError(f"unsupported schedule provider {source}")
            rows.extend(schedule.release_row(setting, day, schedule_source=source) for day in dates)
        except Exception as exc:  # noqa: BLE001 - family schedule source isolation.
            failures.append(_failure(setting, "schedule", str(exc), type(exc).__name__))

    if fred_groups:
        fetched, fred_failures = fred_calendar.fetch_batch(
            list(fred_groups), start=today, end=end
        )
        failed_ids = {int(item["release_id"]) for item in fred_failures}
        for release_id, grouped in fred_groups.items():
            if release_id in failed_ids:
                for setting in grouped:
                    failures.append(_failure(
                        setting, "schedule", "FRED release calendar unavailable", "FredCalendarError"
                    ))
                continue
            for setting in grouped:
                try:
                    rows.extend(
                        schedule.release_row(
                            setting, day, schedule_source="fred_release_calendar"
                        )
                        for day in fetched.get(release_id, [])
                    )
                except Exception as exc:  # noqa: BLE001
                    failures.append(_failure(setting, "schedule", str(exc), type(exc).__name__))

    if fomc_settings:
        try:
            dates = fomc_calendar.fetch_dates(start=today, end=end)
            for setting in fomc_settings:
                rows.extend(
                    schedule.release_row(setting, day, schedule_source="fomc_official_calendar")
                    for day in dates
                )
        except Exception as exc:  # noqa: BLE001 - official source failure is isolated by family.
            failures.extend(
                _failure(setting, "schedule", str(exc), type(exc).__name__)
                for setting in fomc_settings
            )

    # 한 reference period에 공식 calendar가 여러 release date를 주는 경우가
    # 있다. 이것은 같은 event의 advance/second/third print일 수 있으므로
    # 경제 발표 identity는 가장 이른 candidate(첫 발표)로 정규화한다. 이후
    # revision은 ALFRED/observations가 append-only로 추적한다. 서로 다른
    # schedule source가 충돌하면 의미를 추측하지 않고 fail-closed한다.
    candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        candidates[(str(row["series_id"]), str(row["ref_period"]))].append(row)
    unique_rows: dict[tuple[str, str], dict[str, Any]] = {}
    conflicting_keys: set[tuple[str, str]] = set()
    for key, grouped in candidates.items():
        source_set = {str(row.get("schedule_source") or "") for row in grouped}
        if len(source_set) > 1:
            conflicting_keys.add(key)
            continue
        chosen = min(grouped, key=lambda row: _schedule_sort_key(row["scheduled_at"]))
        if len({str(row["scheduled_at"]) for row in grouped}) > 1:
            schedule_provenance = dict((chosen.get("provenance") or {}).get("schedule") or {})
            schedule_provenance["alternate_candidates"] = sorted(
                str(row["scheduled_at"]) for row in grouped
            )
            schedule_provenance["selection"] = "earliest_official_release_for_reference_period"
            chosen = {
                **chosen,
                "provenance": {
                    **(chosen.get("provenance") or {}),
                    "schedule": schedule_provenance,
                },
            }
        unique_rows[key] = chosen

    for series_id, ref_period in sorted(conflicting_keys):
        failures.append({
            "series_id": series_id,
            "step": "schedule",
            "error": f"conflicting schedule sources for {ref_period}",
            "type": "ScheduleConflictError",
        })

    deduplicated_rows = list(unique_rows.values())
    before = db.release_index()
    db.upsert_releases(deduplicated_rows)
    return {
        "series_tracked": len(settings),
        "series_scheduled": len({row["series_id"] for row in deduplicated_rows}),
        "source_candidate_rows": len(rows),
        "candidate_releases": len(deduplicated_rows),
        "new_release_candidates": sum(
            (row["series_id"], row["ref_period"]) not in before for row in deduplicated_rows
        ),
    }, failures


def _schedule_sort_key(value: Any) -> datetime:
    """ISO UTC/aware datetime와 datetime 객체를 동일하게 비교한다."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise schedule.ScheduleContractError("scheduled_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def snapshot_forecasts(*, now: datetime) -> tuple[int, list[dict[str, Any]]]:
    """미래 발표의 예상값을 매번 확인하고, 달라진 상태만 DB가 원자적으로 저장한다."""
    upcoming = db.releases_within(start=now, end=now + timedelta(days=EXPECTATION_HORIZON_DAYS),
                                 statuses=("scheduled", "not_available_yet"))
    measures = db.measures_by_series()
    settings = {str(row["series_id"]): row for row in db.enabled_series(include_unsupported=False)}
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    history_cache: dict[str, list[float]] = {}
    gdpnow_values: dict[str, dict[str, float]] = {}
    gdpnow_seen: datetime | None = None
    if any(row["series_id"] == "US_GDP" for row in upcoming):
        try:
            gdpnow_values = nowcast.fetch_gdpnow(observation_start=now.date() - timedelta(days=365))
            gdpnow_seen = datetime.now(timezone.utc)
        except Exception as exc:
            failures.append({"series_id": "US_GDP", "step": "nowcast", "error": type(exc).__name__, "type": type(exc).__name__})
    for release in upcoming:
        sid, period = str(release["series_id"]), str(release["ref_period"])
        setting = settings.get(sid)
        target = str((setting or {}).get("forecast_measure_id") or "")
        measure = next((row for row in measures.get(sid, []) if row["measure_id"] == target), None)
        if setting is None or measure is None:
            failures.append({"series_id": sid, "step": "forecast",
                             "error": "configured forecast measure is missing",
                             "type": "ForecastConfigurationError"})
            continue
        common = {"series_id": sid, "ref_period": period, "measure_id": measure["measure_id"],
                  "time_precision": "collector_seen"}
        nowcast_value = (gdpnow_values.get(sid) or {}).get(period)
        if nowcast_value is not None:
            rows.append({**common, "forecast_kind": "nowcast", "source": "atlanta_fed_gdpnow", "value": nowcast_value,
                         "effective_at": gdpnow_seen, "collected_at": gdpnow_seen})
        if sid not in history_cache:
            history_cache[sid] = (db.primary_history(sid) if measure["is_primary"]
                                  else db.measure_history(sid, measure["measure_id"]))
        forecast = baseline.drift_forecast(history_cache[sid], window=BASELINE_WINDOW.get(str(setting["frequency"]), 12))
        if forecast is not None:
            model_seen = datetime.now(timezone.utc)
            rows.append({**common, "forecast_kind": "own_model",
                         "source": f"econ_baseline_v1_{forecast['method']}", "value": forecast["value"],
                         "effective_at": model_seen, "collected_at": model_seen})
    return db.append_forecasts(rows), failures


def ingest_raw(
    raw_values: dict[str, list[dict[str, Any]]], *,
    eligible_event_keys: set[str] | None = None, notify_first: bool = True,
) -> dict[str, Any]:
    """원자료를 한 번만 저장한다. 최초 관측 판정은 계산 결과의 전후 차이로 얻는다."""
    flattened = [{**row, "series_id": sid} for sid, rows in raw_values.items() for row in rows]
    keys = {row_event_key(row) for row in flattened}
    if eligible_event_keys is not None:
        keys &= eligible_event_keys
    before = db.summaries_for(keys) if notify_first and keys else {}
    inserted = db.append_observations(flattened)
    after = db.summaries_for(keys) if notify_first and keys else {}
    first_keys: list[str] = []
    conflicts: list[dict[str, Any]] = []
    actualized: list[str] = []
    for key, row in after.items():
        if row.get("latest_actual_value") is not None:
            actualized.append(key)
        if row.get("first_actual_value") is None or before.get(key, {}).get("first_actual_value") is not None:
            continue
        effective = _as_datetime(row["first_actual_at"])
        scheduled = _as_datetime(row["scheduled_at"])
        if abs(effective - scheduled) > FIRST_ACTUAL_SCHEDULE_TOLERANCE:
            conflicts.append({"series_id": row["series_id"], "ref_period": row["ref_period"],
                              "scheduled_at": scheduled.isoformat(), "observed_at": effective.isoformat()})
        else:
            first_keys.append(key)
    _report_schedule_conflicts(conflicts)
    return {"observations_inserted": inserted, "first_actuals": len(first_keys),
            "first_actual_event_keys": sorted(first_keys), "actualized_event_keys": sorted(actualized),
            "unmatched_observations": sorted(keys - set(after)) if notify_first else [], "schedule_conflicts": conflicts}


def _report_schedule_conflicts(conflicts: list[dict[str, Any]]) -> None:
    """수집 값은 보존하고 일정 충돌은 로그와 Discord 경고로 알린다."""
    if not conflicts:
        return
    counts: dict[str, int] = {}
    for row in conflicts:
        sid = str(row["series_id"])
        counts[sid] = counts.get(sid, 0) + 1
    summary = ", ".join(f"{sid} {count}건" for sid, count in sorted(counts.items()))
    log.warning("ECON schedule conflicts: total=%d series=%s rows=%s", len(conflicts), summary, conflicts[:20])
    incident = build_runtime_incident(
        workflow="econ_calendar_daily",
        step="발표 일정과 최초 관측 시각 대조",
        summary=f"7일 이상 어긋난 일정 {len(conflicts)}건 · {summary}",
        conclusion="warning",
        impact="원자료는 저장됐지만 해당 발표의 일정 기준 알림이 부정확할 수 있어요.",
        action="GitHub Actions 로그의 schedule_conflicts 원문을 보고 발표 일정 원천을 확인해 주세요.",
        url=current_github_run_url(),
    )
    notify_ops("", logger=log, embeds=[build_incident_embed(incident)])


def run_daily(*, now: datetime, horizon_days: int) -> dict[str, Any]:
    """미래 일정 → 예상값 변화 → 최근 원자료 변화만 확인한다."""
    now = now.astimezone(timezone.utc)
    schedule_summary, failures = sync_schedules(today=now.date(), horizon_days=horizon_days)
    forecast_inserted, forecast_failures = snapshot_forecasts(now=now)
    failures.extend(forecast_failures)
    settings = db.collectible_series()
    definitions = db.measures_by_series()
    recent_start = now.date() - timedelta(days=RECENT_OVERLAP_DAYS)
    starts = {}
    for setting in settings:
        sid, frequency = str(setting["series_id"]), str(setting["frequency"])
        reference = now.date()
        if frequency == "monthly":
            reference = normalize.calendar_months_before(reference.replace(day=1), 1)
        elif frequency == "quarterly":
            reference = normalize.calendar_months_before(date(reference.year, ((reference.month-1)//3)*3+1, 1), 3)
        starts[sid] = min(recent_start, normalize.required_history_start(
            definitions.get(sid, []), frequency=frequency, ref_period=reference))
    raw_values, actual_failures = actuals.fetch_batch(settings, start=recent_start, end=now.date(),
                                                     starts_by_series=starts)
    failures.extend(item for item in actual_failures if item.get("status") == "failed")
    ingest = ingest_raw(raw_values)
    # 적재가 끝난 뒤에만 줄인다. 실패한 회차에서 지우면 아직 안 들어온 실제치를
    # 기다리던 예상 스냅샷이 먼저 사라진다.
    retention: dict[str, int] = {}
    if not failures:
        try:
            retention = db.prune_release_snapshots()
        except Exception as exc:  # noqa: BLE001 - 정리 실패가 적재 결과를 가리지 않게 한다
            log.warning("econ retention skipped: %r", exc)
    return {**schedule_summary, **ingest, "forecast_inserted": forecast_inserted,
            "unsupported_sources": sum(item.get("status") == "unsupported" for item in actual_failures),
            "retention": retention,
            "failure_count": len(failures), "failures": failures[:30]}


def watch_once(*, now: datetime, limit: int = 50) -> dict[str, Any]:
    """현재 일정의 제한된 발표창만 조회하며 아직 계산 가능한 값이 없으면 기다린다."""
    now = now.astimezone(timezone.utc)
    due = db.due_releases(now=now, limit=limit)
    if not due:
        return {"due": 0, "not_available": 0, "observations_inserted": 0, "first_actuals": 0,
                "first_actual_event_keys": [], "failures": []}
    settings = {str(row["series_id"]): row for row in db.collectible_series()}
    chosen = [row for row in due if str(row["series_id"]) in settings]
    if not chosen:
        return {"due": len(due), "not_available": len(due), "observations_inserted": 0,
                "first_actuals": 0, "first_actual_event_keys": [], "failures": []}
    definitions = db.measures_by_series()
    starts: dict[str, date] = {}
    for row in chosen:
        sid, period = str(row["series_id"]), date.fromisoformat(str(row["ref_period"]))
        needed = normalize.required_history_start(definitions.get(sid, []),
            frequency=str(settings[sid]["frequency"]), ref_period=period)
        starts[sid] = min(starts.get(sid, period), needed, period-timedelta(days=7))
    raw_values, failures = actuals.fetch_batch(
        [settings[sid] for sid in sorted(starts)], start=min(starts.values()), end=now.date(), starts_by_series=starts)
    eligible = {row_event_key(row) for row in chosen}
    # 비교월/전년동월의 수정값도 저장한다. 알림 대상만 이번 발표 자연키로 제한한다.
    ingest = ingest_raw(raw_values, eligible_event_keys=eligible)
    return {"due": len(due), "not_available": len(due) - len(ingest["actualized_event_keys"]),
            "observations_inserted": ingest["observations_inserted"], "first_actuals": ingest["first_actuals"],
            "first_actual_event_keys": ingest["first_actual_event_keys"],
            "failures": [item for item in failures if item.get("status") == "failed"]}


def _as_datetime(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("ECON timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _failure(setting: dict[str, Any], step: str, message: str, kind: str) -> dict[str, Any]:
    return {"series_id": str(setting["series_id"]), "step": step, "error": message, "type": kind}
