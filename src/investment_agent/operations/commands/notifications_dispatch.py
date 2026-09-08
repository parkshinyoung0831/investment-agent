"""v1 알림 outbox 선점 및 발송 진입점 (dispatcher).

미발송(pending/0) 또는 재시도 대상(failed) outbox 항목을 선점하여 Discord로 전송하고,
시도 결과를 deliveries 테이블에 기록한다.
전송 실패나 외부 장애가 발생해도 프로세스를 비정상 종료시키지 않고 진단 로그를 남긴다.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

from investment_agent.config import Config, load_config
from investment_agent.notifications.channels.discord import DiscordChannel
from investment_agent.notifications.outbox import Outbox
from investment_agent.notifications.service import NotificationService
from investment_agent.platform.clock import utc_now
from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def build_service(
    config: Config,
    db: Any | None = None,
    *,
    dry_run: bool = False,
    channel: Any = None,
    clock: Any = None,
) -> NotificationService:
    """설정과 DB로부터 NotificationService를 조립한다."""
    outbox = Outbox()
    if channel is None:
        if dry_run:
            def _mock_post(*args: Any, **kwargs: Any) -> Any:
                log.info("dry-run mock post args=%s kwargs=%s", args, kwargs)
                class _MockResp:
                    status_code = 200
                    def json(self) -> dict[str, Any]:
                        return {"id": "dry_run_message_id"}
                return _MockResp()
            channel = DiscordChannel(config, post=_mock_post)
        else:
            channel = DiscordChannel(config)
    return NotificationService(outbox, channel, clock=clock or utc_now)


def dispatch_pending(
    *,
    config: Config | None = None,
    db: Any | None = None,
    service: NotificationService | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> int:
    """대기 중인 outbox 알림을 선점하고 발송한다."""
    if service is None:
        if config is None:
            config = load_config()
        service = build_service(config, db, dry_run=dry_run)

    results = service.run_pending()
    if limit is not None and limit > 0:
        results = results[:limit]

    sent = sum(1 for r in results if r.status == "sent")
    failed = sum(1 for r in results if r.status in ("failed", "abandoned", "unknown"))
    skipped = sum(1 for r in results if r.status == "skipped")
    errors = sum(1 for r in results if r.status == "error")

    log.info(
        "notifications dispatch finished: total=%d sent=%d failed=%d skipped=%d errors=%d dry_run=%s",
        len(results), sent, failed, skipped, errors, dry_run,
    )
    return 0 if errors == 0 else 1


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="python -m investment_agent.operations.commands.notifications_dispatch")
    parser.add_argument("--dry-run", action="store_true", help="Discord 실제 전송 없이 선점 및 모의 발송만 수행")
    parser.add_argument("--limit", type=int, default=None, help="처리할 최대 알림 건수")
    args = parser.parse_args(argv)

    try:
        return dispatch_pending(dry_run=args.dry_run, limit=args.limit)
    except Exception:
        log.exception("notifications dispatch unhandled exception")
        return 1


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    sys.exit(main())
