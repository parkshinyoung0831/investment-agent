"""고정 IP 환경에서 실행하는 토스 한글명 증분 보강 진입점."""
from __future__ import annotations

import argparse
import time

from investment_agent.operations.runtime import elapsed_sec
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.data.universe.commands.universe_names")
    parser.add_argument(
        "--retry-after-days",
        type=int,
        default=90,
        help="이름을 받지 못한 추적 종목을 다시 조회할 최소 경과일.",
    )
    args = parser.parse_args(argv)
    if args.retry_after_days < 1:
        parser.error("--retry-after-days must be at least 1")

    from investment_agent.data.universe.application import collection as etl

    t0 = time.monotonic()
    metrics = etl.refresh_korean_names(retry_after_days=args.retry_after_days)
    log.info(
        "universe korean names done: pending=%d attempted=%d updated=%d "
        "duration_sec=%.1f",
        metrics["pending"],
        metrics["attempted"],
        metrics["updated"],
        elapsed_sec(t0),
    )
    if metrics["attempted"] < metrics["pending"]:
        log.error(
            "토스 한글명 조회 미완료: %d개 중 %d개만 조회했습니다. "
            "자격증명과 허용 IP를 확인하세요.",
            metrics["pending"],
            metrics["attempted"],
        )
        return 1
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
