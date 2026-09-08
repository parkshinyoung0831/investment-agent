"""Daily ECON entrypoint: schedule sync → forecast snapshot → short actual overlap."""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta, timezone

from investment_agent.operations.runtime import elapsed_sec, notify_ops
from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.data.macro.releases import HORIZON_DAYS

log = get_logger(__name__)
def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="investment_agent.data.macro.commands.econ_calendar_daily")
    parser.add_argument("--horizon-days", type=int, default=HORIZON_DAYS)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="외부 호출과 DB read만 수행한다. 생산 daily 증분 저장은 하지 않는다.",
    )
    args = parser.parse_args(argv)
    if args.horizon_days < 1:
        parser.error("--horizon-days must be at least 1")

    from investment_agent.data.macro.application import release_calendar as etl
    from investment_agent.data.macro.releases import db
    from investment_agent.config import load_config
    from investment_agent.platform.db.postgres import Database
    db.configure(Database.from_config(load_config()))
    if not args.dry_run:
        db.seed_catalog()

    started = time.monotonic()
    now = datetime.now(timezone.utc)
    if args.dry_run:
        # dry-run은 write 경로를 흉내 내지 않는다. DB의 현재 schedule SSOT만 진단한다.
        summary = {
            "series_tracked": len(db.enabled_series()),
            "due_now": len(db.due_releases(now=now)),
            "release_rows": len(db.releases_within(start=now, end=now + timedelta(days=366))),
            "failure_count": 0,
            "dry_run": True,
        }
    else:
        summary = etl.run_daily(now=now, horizon_days=args.horizon_days)

    fail_count = int(summary.get("failure_count", 0))
    log.info(
        "econ daily done: tracked=%d candidates=%d observations=%d first=%d "
        "forecasts=%d unsupported=%d failures=%d duration_sec=%.1f",
        summary.get("series_tracked", 0),
        summary.get("candidate_releases", 0),
        summary.get("observations_inserted", 0),
        summary.get("first_actuals", 0),
        summary.get("forecast_inserted", 0),
        summary.get("unsupported_sources", 0),
        fail_count,
        elapsed_sec(started),
    )
    if fail_count:
        detail = ", ".join(
            f"{item.get('series_id', 'unknown')}({item.get('type', 'Error')})"
            for item in summary.get("failures", [])[:10]
        )
        notify_ops(f"econ_calendar_daily: {fail_count} source failures - {detail}", logger=log)
    return 1 if fail_count else 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
