"""명시적인 넓은 ALFRED revision audit entrypoint."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="investment_agent.data.macro.commands.econ_calendar_revision_audit")
    parser.add_argument("--days", type=int, default=3650)
    args = parser.parse_args(argv)
    if not 30 <= args.days <= 36500:
        parser.error("--days must be between 30 and 36500")

    from investment_agent.data.macro.application import release_calendar as etl
    from investment_agent.data.macro.releases import db
    from investment_agent.data.macro.infrastructure.releases.sources import actuals, alfred
    from investment_agent.config import load_config
    from investment_agent.platform.db.postgres import Database
    db.configure(Database.from_config(load_config()))
    db.seed_catalog()

    now = datetime.now(timezone.utc)
    start = now.date() - timedelta(days=args.days)
    settings = db.collectible_series()
    # FRED component 합성값은 direct ALFRED series id가 없다. 별도 component-vintage
    # replay를 구현하기 전에는 current history로만 검증하며 FRED id가 있는 family만
    # ALFRED revision audit에 넣는다.
    alfred_settings = [
        row for row in settings
        if row.get("revision_provider") == "alfred" and row.get("actual_provider") == "fred"
    ]
    settings_by_id = {str(row["series_id"]): row for row in alfred_settings}
    targets = [
        {
            "series_id": row["series_id"],
            "fred_id": (row.get("source_contract") or {}).get("actual", {}).get("code"),
            "scale": (row.get("source_contract") or {}).get("actual", {}).get("scale"),
        }
        for row in alfred_settings
    ]
    vintages, failures = alfred.fetch_batch(targets, observation_start=start, revisions=True)
    result = etl.ingest_raw(
        {
            series_id: alfred.source_rows(settings_by_id[series_id], rows)
            for series_id, rows in vintages.items()
        },
        notify_first=False,
    )

    # Vintage API가 없는 ECOS/EIA/Fed components는 현재 공개 이력을 넓게 다시 읽되,
    # 이것을 과거 first actual로 승격하지 않는다.
    non_vintage = [row for row in settings if row.get("revision_provider") == "none"]
    raw_values, live_failures = actuals.fetch_batch(non_vintage, start=start, end=now.date())
    failures.extend(item for item in live_failures if item.get("status") == "failed")
    live_result = etl.ingest_raw(raw_values, notify_first=False)
    log.info(
        "econ revision audit done: alfred_observations=%d live_observations=%d failures=%d",
        result["observations_inserted"], live_result["observations_inserted"], len(failures),
    )
    return 1 if failures else 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
