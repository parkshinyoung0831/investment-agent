"""알림 채널 환경변수 구성을 읽기 전용으로 검증한다."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable

from investment_agent.config import Config, load_config
from investment_agent.notifications.subscriptions import KIND_ENV, discord_targets
from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def validate(config: Config, kinds: Iterable[str] | None = None) -> dict[str, str]:
    """각 kind에 정확히 하나의 Discord target 환경변수가 설정돼 있는지 확인한다."""
    selected = tuple(kinds) if kinds is not None else tuple(KIND_ENV)
    unknown = sorted(set(selected) - set(KIND_ENV))
    if unknown:
        raise ValueError(f"unknown subscription kind(s): {', '.join(unknown)}")
    targets: dict[str, str] = {}
    for kind in selected:
        resolved = discord_targets(kind, config=config)
        if len(resolved) != 1:
            raise RuntimeError(
                f"notification kind {kind!r} requires exactly one Discord subscription target"
            )
        targets[kind] = resolved[0]
    return targets


def run(*, config: Config | None = None, kinds: Iterable[str] | None = None) -> dict[str, str]:
    """환경변수만 읽어 검증한다."""
    config = config or load_config()
    resolved = validate(config, kinds)
    log.info("notification subscriptions validated kinds=%d", len(resolved))
    return resolved


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="python -m investment_agent.operations.commands.validate_subscriptions"
    )
    parser.add_argument("--kind", action="append", choices=tuple(KIND_ENV))
    args = parser.parse_args()
    try:
        run(kinds=args.kind)
        return 0
    except Exception:
        log.exception("notification subscription validation failed")
        return 1


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    sys.exit(main())
