"""Supabase 종목 ID가 다시 매겨진 뒤, 로컬 판단 원장의 옛 security_id를 새 ID로 옮긴다.

    python -m investment_agent.operations.commands.remap_runtime_securities            # 확인만
    python -m investment_agent.operations.commands.remap_runtime_securities --apply    # 백업 후 적용

판단 원장(`security_decisions`·`signals`)은 ticker가 아니라 security_id를 저장한다. 재구축으로 ID가
바뀌면 reader가 "unknown securities"로 실패하고 후보 선정 전체가 멈춘다. 새 ID는 `case_key` 앞머리의
ticker를 지금 상장 중인 종목으로 풀어 정한다. 풀리지 않는 행이 하나라도 있으면 아무것도 바꾸지
않는다 — 일부만 옮기면 같은 원장 안에 두 세대의 ID가 섞여 어느 것이 맞는지 알 수 없게 된다.
"""
from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import canonical_json
from investment_agent.platform.storage_paths import runtime_database_path

log = get_logger(__name__)

TABLES = ("security_decisions", "signals")


def _ticker_from_case_key(case_key: str) -> str:
    return str(case_key).split("__", 1)[0].upper()


def plan_remap(
    connection: sqlite3.Connection,
    *,
    resolve: Callable[[Sequence[str]], Mapping[str, int]],
    known_ids: Callable[[Sequence[int]], set[int]],
) -> dict:
    """옮길 (표, case_key, 옛 ID, 새 ID) 목록과 풀리지 않은 행. 원장은 읽기만 한다."""
    rows = []
    for table in TABLES:
        rows += [(table, str(case_key), int(security_id))
                 for case_key, security_id in connection.execute(f"SELECT case_key, security_id FROM {table}")]
    stale = sorted({security_id for _, _, security_id in rows} - known_ids(sorted({row[2] for row in rows})))
    stale_rows = [row for row in rows if row[2] in set(stale)]
    tickers = sorted({_ticker_from_case_key(case_key) for _, case_key, _ in stale_rows})
    mapping = dict(resolve(tickers)) if tickers else {}
    changes, unresolved = [], []
    for table, case_key, old in stale_rows:
        new = mapping.get(_ticker_from_case_key(case_key))
        (changes if new is not None else unresolved).append((table, case_key, old, new))
    return {"rows": len(rows), "stale_ids": len(stale), "changes": changes, "unresolved": unresolved}


def apply_remap(database: Path, plan: Mapping) -> Path:
    if plan["unresolved"]:
        raise RuntimeError(f"{len(plan['unresolved'])} rows cannot be resolved; nothing was changed")
    backup = database.with_name(f"{database.name}.before-remap-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}")
    source = sqlite3.connect(database)
    target = sqlite3.connect(backup)
    source.backup(target)
    target.close()
    try:
        with source:
            for table, case_key, old, new in plan["changes"]:
                source.execute(f"UPDATE {table} SET security_id=? WHERE case_key=? AND security_id=?", (new, case_key, old))
    finally:
        source.close()
    return backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.remap_runtime_securities")
    parser.add_argument("--apply", action="store_true", help="백업을 만든 뒤 실제로 옮긴다")
    args = parser.parse_args(argv)
    from investment_agent.data.universe.repository import UniverseRepository
    from investment_agent.platform.db.postgres import Database, sb

    universe = UniverseRepository(Database(sb))
    database = runtime_database_path()
    with closing(sqlite3.connect(f"{Path(database).resolve().as_uri()}?mode=ro", uri=True)) as connection:
        plan = plan_remap(
            connection,
            resolve=universe.security_ids,
            known_ids=lambda ids: set(universe.securities_by_id(ids)),
        )
    summary = {"rows": plan["rows"], "stale_ids": plan["stale_ids"], "changes": len(plan["changes"]),
               "unresolved": [row[1] for row in plan["unresolved"]][:20]}
    if not args.apply:
        log.info("runtime security remap plan (dry-run) %s", canonical_json(summary))
        return 0 if not plan["unresolved"] else 1
    backup = apply_remap(Path(database), plan)
    log.info("runtime security remap applied backup=%s %s", backup, canonical_json(summary))
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
