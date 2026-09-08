"""서브레딧 새 글을 수집해 intelligence.duckdb에 적재한다."""
from __future__ import annotations

import argparse
import json
import sys

from investment_agent.intelligence.repository import IntelligenceRepository
from investment_agent.intelligence.application import collect_social as service
from investment_agent.intelligence.domain.catalog import SUBREDDITS
from investment_agent.intelligence.infrastructure.sources.social.reddit import fetch_new_posts
from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="서브레딧 새 글 수집")
    parser.add_argument("--channel", action="append", default=None, help="반복 지정 가능")
    parser.add_argument("--limit", type=int, default=100, help="채널당 최대 게시물 수")
    args = parser.parse_args(argv)

    configure_logging()
    run = service.collect_social(
        repository=IntelligenceRepository(),
        fetch=lambda channel: fetch_new_posts(channel, limit=args.limit),
        channels=args.channel or list(SUBREDDITS),
        tracked=service.tracked_tickers(),
    )
    print(
        json.dumps(
            {
                "run_id": run.run_id,
                "status": run.status,
                "stored": run.stored_count,
                "duplicates": run.duplicate_count,
            },
            ensure_ascii=False,
        )
    )
    return 0 if run.status in {"ok", "partial", "skipped", "capped"} else 1


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli

    start_cli()
    sys.exit(main())
