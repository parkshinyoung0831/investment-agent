"""명시적 과거 자료 적재. 원자료 빈티지·예상값의 실제 수집시각을 보존한다."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from investment_agent.operations.backfill import add_backfill_from_arg, resolve_backfill_window
from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.data.macro.domain.releases import baseline, normalize, schedule
from investment_agent.data.macro.releases import BASELINE_WINDOW

log = get_logger(__name__)
DEFAULT_YEARS = 10


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="investment_agent.data.macro.commands.econ_calendar_backfill")
    add_backfill_from_arg(
        parser, help_text="ALFRED observation start, YYYY-MM-DD (default: 10 years)."
    )
    parser.add_argument("--series", nargs="*", default=None)
    parser.add_argument("--no-revisions", action="store_true")
    parser.add_argument("--no-forecasts", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from investment_agent.data.macro.application import release_calendar as etl
    from investment_agent.data.macro.releases import db
    from investment_agent.data.macro.infrastructure.releases.sources import alfred
    from investment_agent.data.macro.infrastructure.releases.sources import actuals
    from investment_agent.config import load_config
    from investment_agent.platform.db.postgres import Database
    db.configure(Database.from_config(load_config()))
    if not args.dry_run:
        db.seed_catalog()

    window = resolve_backfill_window(args.backfill_from, default_years=DEFAULT_YEARS)
    selected = db.collectible_series()
    if args.series:
        wanted = set(args.series)
        missing = wanted - {str(row["series_id"]) for row in selected}
        if missing:
            raise ValueError(f"unknown or unsupported ECON series: {', '.join(sorted(missing))}")
        selected = [row for row in selected if row["series_id"] in wanted]
    if not selected:
        raise RuntimeError("no collectible ECON series selected")
    settings = [row for row in selected
                if row.get("actual_provider") == "fred" and row.get("revision_provider") == "alfred"]
    by_id = {str(row["series_id"]): row for row in settings}
    targets = [
        {
            "series_id": sid,
            "fred_id": (setting.get("source_contract") or {}).get("actual", {}).get("code"),
            "scale": (setting.get("source_contract") or {}).get("actual", {}).get("scale"),
        }
        for sid, setting in by_id.items()
    ]
    # 먼저 공식 최초 발표일을 확보한다. 과거 추정 일정을 썼다가 즉시 고치는
    # 불필요한 버전을 만들지 않도록 실제 첫 발표를 달력 후보보다 먼저 저장한다.
    failures: list[dict[str, Any]] = []
    schedule_summary = {"candidate_releases": 0}
    fetched, first_failures = alfred.fetch_batch(targets, observation_start=window.start)
    failures.extend(first_failures)
    release_rows: list[dict[str, Any]] = []
    source_rows: dict[str, list[dict[str, Any]]] = {}
    for series_id, rows in fetched.items():
        setting = by_id[series_id]
        release_rows.extend(_release_rows(setting, rows))
        source_rows[series_id] = alfred.source_rows(setting, rows)

    non_vintage_settings = [row for row in selected
        if row.get("revision_provider") == "none"
        and row.get("actual_provider") in {"fred", "ecos", "eia", "fred_components"}]
    non_vintage_values, non_vintage_failures = actuals.fetch_batch(
        non_vintage_settings, start=window.start, end=window.end)
    failures.extend(item for item in non_vintage_failures if item.get("status") == "failed")

    if args.dry_run:
        log.info(
            "econ backfill preview: series=%d first_prints=%d current_observations=%d revision_fetch=%s failures=%d",
            len(selected), sum(len(rows) for rows in fetched.values()),
            sum(len(rows) for rows in non_vintage_values.values()), not args.no_revisions, len(failures),
        )
        return 1 if failures else 0

    release_map = db.upsert_releases(release_rows)
    schedule_summary, schedule_failures = etl.sync_schedules(
        today=window.start,
        horizon_days=(window.end - window.start).days + 180,
        series_ids={str(row["series_id"]) for row in selected},
    )
    failures.extend(schedule_failures)
    # 원자료 빈티지만 넣는다. 최초값과 개정 계산은 조회 시점의 원자료로 재구성한다.
    first = etl.ingest_raw(source_rows, notify_first=False)

    # 공개 빈티지가 없는 자료는 collector_seen으로 표시하고 과거 PIT에서 제외한다.
    non_vintage = etl.ingest_raw(non_vintage_values, notify_first=False)

    revision_result = {"observations_inserted": 0}
    revisions: dict[str, list[dict[str, Any]]] = {}
    if not args.no_revisions:
        revisions, revision_failures = alfred.fetch_batch(
            targets, observation_start=window.start, revisions=True
        )
        failures.extend(revision_failures)
        revision_rows = {
            series_id: alfred.source_rows(by_id[series_id], rows)
            for series_id, rows in revisions.items()
        }
        # 백필과 수정 감사는 알림을 유발하지 않는다.
        revision_result = etl.ingest_raw(revision_rows, notify_first=False)

    forecast_count = 0
    gdpnow_count = 0
    if not args.no_forecasts:
        forecast_rows = _historical_own_model_rows(
            fetched=fetched,
            settings=by_id,
            release_map=release_map,
            measures=db.measures_by_series(),
        )
        forecast_count = db.append_forecasts(forecast_rows)
        if "US_GDP" in fetched:
            try:
                from investment_agent.data.macro.infrastructure.releases.sources import gdpnow_archive

                gdp_rows = _gdpnow_rows(
                    gdpnow_archive.fetch_rows(ref_period_start=window.start),
                    release_map=release_map,
                )
                gdpnow_count = db.append_forecasts(gdp_rows)
            except Exception as exc:  # noqa: BLE001 - 아카이브 실패가 다른 이력을 막지 않는다.
                failures.append({
                    "series_id": "US_GDP", "step": "gdpnow_archive",
                    "error": type(exc).__name__, "type": type(exc).__name__,
                })

    log.info(
        "econ backfill done: series=%d schedule_candidates=%d events=%d first_observations=%d "
        "non_vintage_observations=%d revision_observations=%d own_model=%d gdpnow=%d failures=%d",
        len(selected), schedule_summary["candidate_releases"], len(release_rows), first["observations_inserted"],
        non_vintage["observations_inserted"], revision_result["observations_inserted"],
        forecast_count, gdpnow_count, len(failures),
    )
    return 1 if failures else 0


def _release_rows(setting: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contract = setting.get("source_contract") or {}
    schedule_contract = contract.get("schedule") or {}
    output: list[dict[str, Any]] = []
    for row in rows:
        released = date.fromisoformat(str(row["released_on"]))
        when = schedule.scheduled_at_utc(
            released,
            release_time=schedule_contract.get("time"),
            release_tz=str(schedule_contract["timezone"]),
            confidence=str(schedule_contract["confidence"]),
        )
        output.append({
            "series_id": setting["series_id"],
            "ref_period": str(row["ref_period"]),
            "scheduled_at": when,
            "schedule_source": "alfred_first_print",
            "schedule_confidence": schedule_contract["confidence"],
            "status": "scheduled",
            "provenance": {
                "schedule": {
                    "source": "ALFRED realtime_start",
                    "availability_precision": "date_only",
                    "released_on": row["released_on"],
                    "source_date": released.isoformat(),
                    "timezone": schedule_contract["timezone"],
                    "local_time": schedule_contract.get("time"),
                    "confidence": schedule_contract["confidence"],
                }
            },
        })
    return output


def _historical_own_model_rows(
    *,
    fetched: dict[str, list[dict[str, Any]]],
    settings: dict[str, dict[str, Any]],
    release_map: dict[tuple[str, str], dict[str, Any]],
    measures: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """각 first print 직전 정보만 쓴 measure-level own model PIT reconstruction."""
    output: list[dict[str, Any]] = []
    for series_id, rows in fetched.items():
        setting = settings[series_id]
        forecast_measure_id = str(setting.get("forecast_measure_id") or "")
        target = next((row for row in measures.get(series_id, [])
                       if row["measure_id"] == forecast_measure_id), None)
        if target is None:
            continue
        by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_day[str(row["released_on"])].append(row)
        raw_history: dict[date, float] = {}
        forecast_history: list[float] = []
        window = BASELINE_WINDOW.get(str(setting["frequency"]), 12)
        for released_on in sorted(by_day):
            day_rows = sorted(by_day[released_on], key=lambda row: str(row["ref_period"]))
            # 같은 날 공개된 actual은 모두 forecast 생성 뒤에 history에 넣는다.
            for row in day_rows:
                release = release_map.get((series_id, str(row["ref_period"])))
                forecast = baseline.drift_forecast(forecast_history, window=window)
                if release is None or forecast is None:
                    continue
                as_of = datetime.combine(
                    date.fromisoformat(released_on) - timedelta(days=1),
                    time(23, 59), tzinfo=timezone.utc,
                )
                output.append({
                    "ref_period": str(row["ref_period"]),
                    "series_id": series_id,
                    "measure_id": target["measure_id"],
                    "forecast_kind": "own_model",
                    "source": f"alfred_baseline_v1_{forecast['method']}",
                    "value": forecast["value"],
                    "as_of": as_of,
                    "collected_at": datetime.now(timezone.utc),
                    "time_precision": "date_only",
                    "provenance": {
                        "reconstruction": "ALFRED first prints only",
                        "not_market_consensus": True,
                        "method": forecast["method"],
                    },
                })
            for row in day_rows:
                raw_history[date.fromisoformat(str(row["ref_period"]))] = float(row["value"])
            calculated = normalize.calculate_family(measures.get(series_id, []), raw_history)
            for row in day_rows:
                values = calculated.get(date.fromisoformat(str(row["ref_period"])), {})
                if target["measure_id"] in values:
                    forecast_history.append(values[target["measure_id"]])
    return output


def _gdpnow_rows(
    archive_rows: list[dict[str, Any]],
    *,
    release_map: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in archive_rows:
        release = release_map.get(("US_GDP", str(row["ref_period"])))
        if release is None:
            continue
        as_of = datetime.combine(date.fromisoformat(str(row["snapshot_date"])), time(12), tzinfo=timezone.utc)
        scheduled = datetime.fromisoformat(str(release["scheduled_at"]).replace("Z", "+00:00"))
        if as_of >= scheduled:
            continue
        output.append({
            "ref_period": str(row["ref_period"]),
            "series_id": "US_GDP",
            "measure_id": "US_GDP.QOQ_ANNUALIZED",
            "forecast_kind": "nowcast",
            "source": "atlanta_fed_gdpnow_archive",
            "value": row["value"],
            "as_of": as_of,
            "collected_at": datetime.now(timezone.utc),
            "time_precision": "date_only",
            "provenance": {"provider": "Atlanta Fed GDPNow archive", "pit_checked": True},
        })
    return output


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
