"""로컬 뉴스·소셜 DuckDB의 90일 retention을 적용한다."""
from __future__ import annotations

import argparse
import json

from investment_agent.trading.evidence.cache import LocalEvidenceCache


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.trading.evidence.cleanup")
    parser.add_argument("--path", default=None)
    parser.add_argument("--retention-days", type=int, default=90)
    args = parser.parse_args(argv)
    result = LocalEvidenceCache(args.path, retention_days=args.retention_days).cleanup()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
