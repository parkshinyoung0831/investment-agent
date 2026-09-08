"""Read-only ECON production data-quality validation entrypoint."""
from __future__ import annotations

import argparse
import json

from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="investment_agent.data.macro.commands.econ_calendar_validate")
    parser.add_argument("--require-data", action="store_true", help="발표 일정 또는 원자료가 비면 실패한다")
    args = parser.parse_args(argv)

    from investment_agent.data.macro.domain.releases import validation
    from investment_agent.data.macro.releases import db
    from investment_agent.config import load_config
    from investment_agent.platform.db.postgres import Database
    db.configure(Database.from_config(load_config()))

    result = validation.validate_snapshot(db.validation_snapshot())
    if args.require_data and any(result["counts"][name] == 0 for name in ("release_events", "schedule_versions", "observations")):
        result["errors"]["required_data_missing"] = 1
        result["ok"] = False
    log.info("econ validation %s", json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
