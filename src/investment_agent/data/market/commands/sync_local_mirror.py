"""Supabase → 로컬 사본 동기화. 기본은 증분이고, 마지막 전체 동기화가 7일 넘으면 전체를 받는다.

    python -m investment_agent.data.market.commands.sync_local_mirror
    python -m investment_agent.data.market.commands.sync_local_mirror --full
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from investment_agent.operations.runtime import elapsed_sec, run_log_payload
from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import canonical_json

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.data.market.commands.sync_local_mirror")
    parser.add_argument("--full", action="store_true", help="가격 전체 이력을 다시 받는다")
    parser.add_argument("--lookback-days", type=int, default=10, help="증분에서 다시 받는 최근 일수")
    args = parser.parse_args(argv)
    from investment_agent.data.market.local_mirror.sync import sync_local_mirror

    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    result = sync_local_mirror(full=args.full, lookback_days=args.lookback_days)
    log.info("local mirror %s", canonical_json(run_log_payload(
        workflow="local_mirror_sync", status="success", rows_upserted=int(result.manifest.counts.get("prices", 0)),
        tickers_processed=result.price_securities, duration_sec=elapsed_sec(started), started_at=started_at,
        detail=result.to_dict(),
    )))
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
