"""8-K 실적 속보 outbox 등록·전송 진입점."""
from __future__ import annotations

import argparse
from collections.abc import Sequence

from investment_agent.config import load_config
from investment_agent.notifications.earnings_flash.candidates import load_pending_flash
from investment_agent.reporting.notifications.earnings_flash import EarningsFlashStore
from investment_agent.notifications.channels.discord import DiscordChannel
from investment_agent.notifications.earnings_flash.embeds import build_flash_embed
from investment_agent.notifications.outbox import Outbox
from investment_agent.notifications.service import NotificationService
from investment_agent.notifications.subscriptions import discord_targets
from investment_agent.notifications.channels import routing
from investment_agent.platform.clock import utc_now
from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def run(
    target_channel_id: str | None = None,
    *,
    tickers: set[str] | None = None,
    store: EarningsFlashStore | None = None,
    service: NotificationService | None = None,
    targets: Sequence[str] | None = None,
) -> int:
    """미발송 8-K 속보를 v1 outbox에 등록하고 디스패치한다."""
    config = load_config()
    if store is None:
        store = EarningsFlashStore.configured(config)

    pending = load_pending_flash(store, tickers)
    if not pending:
        log.info("flash: 발송할 신규 8-K 실적 속보 없음")
        return 0

    if target_channel_id:
        target_ids = (target_channel_id,)
    elif targets is not None:
        target_ids = tuple(targets)
    else:
        target_ids = discord_targets("fundamentals_flash", config=config)
    if len(target_ids) != 1:
        raise RuntimeError("fundamentals_flash requires exactly one Discord subscription target")
    channel_id = target_ids[0]
    if service is None:
        service = NotificationService(Outbox(store.database), DiscordChannel(config), clock=utc_now)

    enqueued = 0
    for item in pending:
        flash = item["flash"]
        ticker = str(flash["ticker"])
        accession_no = str(flash["accession_no"])
        key = f"flash:{ticker}:{accession_no}"
        result = service.enqueue(
            producer="fundamentals",
            notification_key=key,
            kind="fundamentals_flash",
            target=channel_id,
            message={
                "content": f"⚡ **{ticker}** 실적 발표 속보가 접수되었습니다.",
                "embeds": [build_flash_embed(item)],
            },
            entity_key=ticker,
            period_end=flash.get("period_end"),
            # 목적지는 실적 포럼이다. 속보와 정밀 분석이 **같은 종목 스레드**에
            # 쌓여야 "그 종목에 무슨 일이 있었나"를 한 줄기로 읽는다. 제목을
            # 빼면 Discord가 400으로 거절하고 그 실패는 outbox에만 남는다.
            thread_name=routing.ticker_thread_title(
                ticker, str(flash.get("company_name") or ticker)),
        )
        if result.status == "enqueued":
            enqueued += 1
        elif result.status == "error":
            log.warning("flash: outbox 등록 실패 ticker=%s accession_no=%s", ticker, accession_no)

    results = service.run_pending()
    sent = sum(
        1 for result in results
        if result.producer == "fundamentals"
        and result.status == "sent"
    )
    log.info("flash: outbox 등록=%d 전송 완료=%d", enqueued, sent)
    return sent


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="investment_agent.notifications.earnings_flash.run",
        description="8-K 실적 속보를 outbox에 등록하고 디스패치한다.",
    ).parse_args(argv)
    configure_logging()
    return run()


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
