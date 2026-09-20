"""매일 '매크로 코어' PNG를 만들어 Discord로 보내는 부분.

호출: 디스패쳐(__main__)가 --kind macro_core로 core.run() 실행.

화면 구성 (4열 카드):
- CORE_LAYOUT 순서대로 4섹션(주식·크립토 / 금리 / 환율 / 원자재) 카드 4열 표시
- 헤더: '매크로 코어' 제목 옆에 톤 칩(주식·채권·달러·금·원유·BTC 화살표) 일렬
- 리본: 좌측 공포·탐욕 게이지(=오늘의 레짐, 숫자+라벨) + 우측 VIX 심리
- 요약: 위험/주의/관심 개수(색 점), 등급 카드는 우상단 색 점만 표시
- 데이터가 이틀 이상 안 들어왔으면 갱신 지연 경고
"""
from __future__ import annotations
import argparse
import asyncio
from collections.abc import Sequence
from datetime import date, datetime, time, timezone
from typing import Any

from investment_agent.config import load_config
from investment_agent.notifications.context import default_context
from investment_agent.reporting.notifications.macro import MacroNotificationStore
from investment_agent.notifications.engine import (
    Notice,
    PublishContext,
    Rendered,
    publish,
)
from investment_agent.notifications.problems import report_problems, take_problems
from investment_agent.notifications.subscriptions import discord_target
from investment_agent.notifications.topics import topic
from investment_agent.reporting.services.macro.constants import CORE_LAYOUT, STALE_COLOR, TONE_ALIAS
from investment_agent.reporting.services.macro.format import (
    base_card, color_for, fng_color, fng_label, short_of, tier_badge,
)
from investment_agent.notifications.macro.render import render, shoot_png
from investment_agent.notifications.playwright import persist_png
from investment_agent.reporting.services.macro.thresholds import eval_row, stronger

from investment_agent.platform.logging import get_logger
from investment_agent.platform.logging import configure_logging

log = get_logger(__name__)


TOPIC = topic("macro.daily")
SUBJECT = "market"


def _pct(curr, prev):
    if curr is None or prev is None or float(prev) == 0:
        return None
    return (float(curr) - float(prev)) / abs(float(prev)) * 100


def _tone_arrow(by_sid: dict, key: str, reverse: bool = False) -> str:
    """레짐 리본 톤 칩용 화살표(플레인 글리프 — 이모지 변형 selector 미사용)."""
    sid = TONE_ALIAS.get(key)
    r = by_sid.get(sid)
    if not r:
        return "→"
    p = _pct(r.get("curr"), r.get("prev_value"))
    if p is None:
        return "→"
    v = -p if reverse else p
    if v > 0.3: return "↗"
    if v < -0.3: return "↘"
    return "→"


def _stale_info(rows):
    """개별 카드의 freshness를 집계한다."""
    stale = [
        r for r in rows
        if (r.get("freshness") or {}).get("state") in {"stale", "missing"}
    ]
    if not stale:
        return (0, None)
    oldest = min(
        (r.get("freshness") or {}).get("obs_date") or "9999-12-31"
        for r in stale
    )
    return (len(stale), oldest if oldest != "9999-12-31" else None)


def _build_ctx(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_sid = {r["series_id"]: r for r in rows}
    strong = {"alert": 0, "caution": 0, "watch": 0}
    max_level = None

    # 전 지표 등급 평가 — 요약 칩 카운트 + 카드 우상단 점 색.
    tiers: dict[str, Any] = {}
    for r in rows:
        tier, _reason = eval_row(r)
        tiers[r["series_id"]] = tier
        if tier:
            short = short_of(tier)  # "🔴 alert" → "alert"
            if short in strong:
                strong[short] += 1
            max_level = stronger(max_level, tier)

    def _card(sid: str):
        r = by_sid.get(sid)
        return {**base_card(r), **tier_badge(tiers.get(sid))} if r else None

    # 4섹션 명시 순서 (CORE_LAYOUT). VIX·FEAR_GREED는 카드 그리드에서 제외 — 리본에서 표시.
    sections = []
    for name, icon, sids in CORE_LAYOUT:
        cards = [c for c in (_card(s) for s in sids) if c]
        if cards:
            sections.append({"name": name, "icon": icon, "cards": cards})

    # VIX → 리본 우측 심리 패널.
    vix = _card("VIX")

    # FEAR_GREED → 오늘의 레짐 게이지 (하단 별도 섹션 없이 이걸로 통합, 숫자+라벨 표시).
    fng = None
    rf = by_sid.get("FEAR_GREED")
    if rf and rf.get("curr") is not None:
        v = float(rf["curr"])
        fng = {"value": f"{v:.0f}", "pct": max(0, min(100, v)),
               "label": fng_label(v), "color": fng_color(v)}

    # 헤더 톤 칩 (제목 옆 일렬) — 채권은 금리 역방향(가격 기준).
    tone_specs = [("주식", "spy", False), ("채권", "tnx", True), ("달러", "dxy", False),
                  ("금", "gold", False), ("원유", "wti", False), ("BTC", "btc", False)]
    tone_chips = [{"label": lbl, "arrow": _tone_arrow(by_sid, key, rev)}
                  for lbl, key, rev in tone_specs]

    stale_count, stale_oldest = _stale_info(rows)
    side_color = STALE_COLOR if stale_count else color_for(max_level)

    code_map = " · ".join(
        f'{(by_sid[s].get("name_ko") or s)} {s}'
        for _n, _i, sids in CORE_LAYOUT for s in sids if s in by_sid
    )

    return {
        "today": date.today().isoformat(),
        "side_color": side_color,
        "strong_counts": strong,
        "tone_chips": tone_chips,
        "vix": vix,
        "fng": fng,
        "sections": sections,
        "stale_count": stale_count,
        "stale_oldest": stale_oldest,
        "code_map": code_map,
    }


async def shoot(rows: list[dict[str, Any]]) -> str:
    return await shoot_png(render("core.html.j2", _build_ctx(rows)))


def notice_for(rows: list[dict[str, Any]], today: date) -> Notice:
    """하루 한 장. 내용은 카드에 찍히는 지표·관측일·값이다 — 같으면 새 날이라도 보내지 않는다."""
    return Notice(
        subject=SUBJECT,
        occurrence=today.isoformat(),
        fact_at=datetime.combine(today, time.min, tzinfo=timezone.utc),
        basis={"series": sorted([str(r["series_id"]), str(r["obs_date"]), r.get("curr")] for r in rows)},
        data=rows,
    )


def render_card(batch: list[Notice]) -> Rendered:
    notice, = batch
    png_path = persist_png(asyncio.run(shoot(notice.data)), kind="macro_core", name=notice.occurrence)
    return Rendered({"content": "📊 매크로 코어 (Stack 1)"}, attachment_path=png_path)


def run(*, store: MacroNotificationStore | None = None, target: str | None = None,
        context: PublishContext | None = None, today: date | None = None) -> int:
    config = load_config()
    store = store or MacroNotificationStore.configured(config)
    rows = store.load_core()
    if not rows:
        log.info("core: no rows from macro v1 observation reader (CORE_SERIES) — silent skip (stale)")
        return 0
    report = publish(
        TOPIC, [notice_for(rows, today or date.today())], render_card,
        context=context or default_context(config),
        target=discord_target(TOPIC.channel_kind, config=config, override=target),
    )
    return report.delivered


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="investment_agent.notifications.macro.core",
        description="매크로 코어 PNG 알림을 원장에 예약하고 발송한다.",
    ).parse_args(argv)
    configure_logging()
    take_problems()
    try:
        run()
    except Exception:
        log.exception("macro core notification failed")
        return 1
    return 1 if report_problems("macro_core") else 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
