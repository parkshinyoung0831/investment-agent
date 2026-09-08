"""평일 매시 '매크로 워치' embed를 만들어 Discord로 보내는 부분.

호출: 디스패쳐(__main__)가 --kind macro_watch로 watch.run() 실행.

화면 구성 (embeds.build_watch):
- 지표마다 모든 기준을 보고 가장 센 등급을 매김(eval_row)
- 등급(🔴/🟠/🟡)별 필드 + 한국 시장은 등급과 무관하게 별도 필드
- 임계를 하나도 안 건드린 지표는 필드에 나타나지 않음

발송 규칙:
- 등급 판단은 core와 같은 함수(eval_row)
- 등급 없는 지표는 발송 안 함
- 평가한 지표는 발송 여부와 무관하게 '처리함' 기록 → 같은 날 재평가 차단
- 전송 실패해도 기록은 남김 (오류는 #로컬-실패로 따로 알림)
"""
from __future__ import annotations

import argparse
from collections.abc import Sequence

from investment_agent.config import load_config
from investment_agent.reporting.notifications.macro import MacroNotificationStore
from investment_agent.notifications.channels.discord import DiscordChannel
from investment_agent.notifications.macro import embeds
from investment_agent.notifications.outbox import Outbox
from investment_agent.notifications.service import NotificationService
from investment_agent.notifications.subscriptions import discord_targets
from investment_agent.platform.clock import utc_now
from investment_agent.reporting.services.macro.thresholds import eval_row

from investment_agent.platform.logging import get_logger
from investment_agent.platform.logging import configure_logging

log = get_logger(__name__)


def eval_thresholds(rows):
    """전체 지표 평가. notified=등급이 매겨진 지표, checked=평가를 마친 전체."""
    notified, checked = [], list(rows)
    for r in rows:
        tier, reason = eval_row(r)
        if tier:
            r["tier"] = tier
            r["reason"] = reason or ""
            notified.append(r)
    return notified, checked


def run(*, store: MacroNotificationStore | None = None, service: NotificationService | None = None,
        targets: Sequence[str] | None = None) -> None:
    if store is None:
        store = MacroNotificationStore.configured(load_config())
    if service is None:
        config = load_config()
        service = NotificationService(
            Outbox(store.database), DiscordChannel(config), clock=utc_now,
        )
    rows = store.load_watch_pending()
    if not rows:
        log.info("watch: no pending obs — silent skip")
        return
    notified, checked = eval_thresholds(rows)
    if notified:
        target_ids = tuple(targets) if targets is not None else discord_targets("macro_watch")
        if len(target_ids) != 1:
            raise RuntimeError("macro_watch requires exactly one Discord subscription target")
        message = {"embeds": [embeds.build_watch(notified)]}
        result = service.enqueue(
            producer="macro",
            notification_key=f"watch:{notified[0]['obs_date']}",
            kind="macro_watch",
            target=target_ids[0],
            message=message,
            entity_key=None,
            period_end=str(notified[0]["obs_date"]),
        )
        if result.status in {"enqueued", "duplicate"}:
            service.run_pending()


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="investment_agent.notifications.macro.watch",
        description="매크로 워치 embed 알림을 outbox에 등록하고 디스패치한다.",
    ).parse_args(argv)
    configure_logging()
    try:
        run()
    except Exception:
        log.exception("macro watch notification failed")
        return 1
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
