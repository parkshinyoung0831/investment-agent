"""로컬 runtime SQLite 스키마를 읽기 작업 전에 명시적으로 준비한다."""
from __future__ import annotations

import argparse
from pathlib import Path

from investment_agent.platform.db.sqlite import (
    default_runtime_database_path,
    runtime_connection,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Initialize the local runtime SQLite ledger and exit.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=default_runtime_database_path(),
        help="runtime SQLite file (defaults to the configured runtime path)",
    )
    args = parser.parse_args(argv)

    with runtime_connection(args.path):
        pass
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli

    start_cli()
    raise SystemExit(main())
