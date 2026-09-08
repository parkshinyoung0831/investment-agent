"""보존 기간을 넘긴 뉴스·소셜과 그 언급을 지운다."""
from __future__ import annotations

import argparse
import json
import sys

from investment_agent.intelligence.repository import IntelligenceRepository
from investment_agent.intelligence.application.retention import RETENTION_DAYS, prune
from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Intelligence 보존 정리")
    parser.add_argument("--retention-days", type=int, default=RETENTION_DAYS)
    args = parser.parse_args(argv)

    configure_logging()
    result = prune(IntelligenceRepository(), retention_days=args.retention_days)
    print(
        json.dumps(
            {
                "news": result.news,
                "social": result.social,
                "mentions": result.mentions,
                "total": result.total,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli

    start_cli()
    sys.exit(main())
