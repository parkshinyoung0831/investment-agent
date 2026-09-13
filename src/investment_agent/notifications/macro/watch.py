"""매크로 경보 — 지표의 경보 상태가 바뀔 때만 알린다.

지표마다 가장 센 등급(eval_row, core와 같은 판정)을 매겨 "지금 상태"를 정한다. 상태는
🔴/🟠/🟡 등급이거나, 최근 경보가 있던 지표가 평시로 돌아온 `clear`다.

알림 하나의 정체성은 (지표, 관측일)이고 내용(basis)은 상태뿐이다. topic이
skip_unchanged라 사람이 이미 아는 직전 상태와 같으면 새 관측이 와도 보내지 않는다 —
임계 위에 몇 주 머무는 지표가 매일 같은 경보를 내지 않는다.
"""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from investment_agent.config import load_config
from investment_agent.notifications.engine import (
    Notice,
    PublishContext,
    Rendered,
    default_context,
    publish,
)
from investment_agent.notifications.macro import embeds
from investment_agent.notifications.problems import report_problems, take_problems
from investment_agent.notifications.subscriptions import discord_target
from investment_agent.notifications.topics import topic
from investment_agent.platform.logging import configure_logging, get_logger
from investment_agent.reporting.notifications.macro import MacroNotificationStore
from investment_agent.reporting.services.macro.thresholds import eval_row

log = get_logger(__name__)

TOPIC = topic("macro.alert")
CLEAR = embeds.CLEARED_TIER
#: 등급 없는 관측이 이만큼 이어져야 평시로 본다. 경계에서 한 번 튀었다 돌아온 값이 경보를 깜빡이지 않게 한다.
CLEAR_AFTER = 2
#: 평시 복귀는 이 관측 수 안에 경보가 있었던 지표만 알린다. 경보가 없던 지표의 복귀는 소식이 아니다.
CLEAR_LOOKBACK = 20


def state_of(row: dict[str, Any]) -> tuple[str, str] | None:
    """(상태, 사유). 알릴 상태가 없으면 None."""
    judged = [eval_row({**row, **point}) for point in row.get("history") or []]
    if not judged:
        return None
    tier, reason = judged[-1]
    if tier:
        return tier, reason or ""
    recent = judged[-CLEAR_AFTER:]
    for earlier_tier, earlier_reason in reversed(recent):
        if earlier_tier:
            return earlier_tier, earlier_reason or ""
    if len(recent) == CLEAR_AFTER and any(t for t, _ in judged[-CLEAR_LOOKBACK:]):
        return CLEAR, "평시 범위로 돌아옴"
    return None


def notices(rows: Sequence[dict[str, Any]]) -> list[Notice]:
    out = []
    for row in rows:
        state = state_of(row)
        if state is None:
            continue
        tier, reason = state
        observed = str(row["obs_date"])[:10]
        out.append(Notice(
            subject=str(row["series_id"]),
            occurrence=observed,
            fact_at=datetime.fromisoformat(observed).replace(tzinfo=timezone.utc),
            basis={"state": tier},
            data={**row, "tier": tier, "reason": reason},
        ))
    return out


def render(batch: list[Notice]) -> Rendered:
    return Rendered({"embeds": [embeds.build_watch([notice.data for notice in batch])]})


def run(*, store: MacroNotificationStore | None = None, target: str | None = None,
        context: PublishContext | None = None) -> int:
    config = load_config()
    store = store or MacroNotificationStore.configured(config)
    candidates = notices(store.load_watch())
    if not candidates:
        log.info("watch: no series is outside its normal range or just returned to it")
        return 0
    report = publish(
        TOPIC, candidates, render,
        context=context or default_context(config),
        target=discord_target(TOPIC.channel_kind, config=config, override=target),
    )
    return report.delivered


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="investment_agent.notifications.macro.watch",
        description="매크로 경보 상태가 바뀐 지표만 한 번씩 알린다.",
    ).parse_args(argv)
    configure_logging()
    take_problems()
    try:
        run()
    except Exception:
        log.exception("macro watch notification failed")
        return 1
    return 1 if report_problems("macro_watch") else 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
