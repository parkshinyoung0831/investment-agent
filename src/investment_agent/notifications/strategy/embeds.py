"""전략 알림 Discord embed 조립.

DESIGN-system.md를 embed가 표현할 수 있는 범위에서 따른다.

- **색 voltage 하나.** embed 왼쪽 막대는 면적 채움이므로 상승·하락 색을 쓰지 않고
  항상 Brand Blue 하나만 쓴다. 변동 강도는 색이 아니라 문장으로 말한다.
- **글자 크기로 위계를 만든다.** `###` 결론 → 본문 → `-#` 각주 3단.
- **숫자는 모노스페이스.** Discord에서 백틱이 모노스페이스다.
- **아이콘은 최소·기하학적.** 이모지 대신 +/−/▲/▼ 만 쓴다.

본문 구성은 전략마다 다르다(layouts.py) — 결정의 모양이 다르기 때문이다.
공통 껍데기(제목·색·도넛·변화·푸터)만 여기서 씌운다.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from . import palette
from .changes import analyze_allocation_change
from .format import (
    mode_label,
    numf,
    pct,
    strategy_description,
    strategy_name,
    ticker_label,
    ym,
)
from .layouts import BUILDERS, Layout
from .models import AllocationRow, StrategyNotification
from .quickchart import allocation_chart_url
from .reasons import render_reason
from .text import plain

# 색은 하나. 변동 강도는 아래 문구가 말한다.
ACCENT = int(palette.PRIMARY.lstrip("#"), 16)

# 보유가 하나뿐이면 도넛이 원 하나가 되어 정보가 없다. 둘 이상일 때만 그린다.
_DONUT_MIN_HOLDINGS = 2
_DONUT_SIZE = 200

_TURNOVER_NOTE = {
    "new": "최초 배분",
    "high": "대폭 교체",
    "mid": "부분 교체",
    "low": "소폭 조정",
    "flat": "지난달과 동일",
}

# 배분 막대는 색이 아니라 글자 모양으로 구분한다. 모바일 클라이언트에서 색 대비가
# 뭉개지면 색은 정보를 나르지 못한다 — 모양은 어디서나 남는다.
_RISK_BLOCK = "█"
_DEFENSIVE_BLOCK = "░"
_SUMMARY_BAR_WIDTH = 20

# Discord는 embed 폭을 그 카드에서 가장 긴 한 줄에 맞춰 늘린다(최대치까지). 카드마다
# 내용 길이가 달라 폭이 제각각으로 보이므로, 모든 카드 맨 아래에 같은 길이의 구분선을
# 강제로 깐다 — 실제 내용과 무관하게 카드 폭이 항상 같아진다. 이름을 zero-width space로
# 두면 필드 제목 없이 선만 보인다(Discord는 빈 문자열 name을 거부한다).
_WIDTH_RULE_FIELD = {"name": "​", "value": "─" * 42}


def _as_row(row: AllocationRow | Mapping[str, Any]) -> AllocationRow:
    return row if isinstance(row, AllocationRow) else AllocationRow.from_mapping(row)


def _generic_layout(row: AllocationRow) -> Layout:
    """전략 전용 형식을 만들 수 없을 때의 안전한 기본형.

    새 전략이 붙거나 signals 형식이 바뀌어도 알림이 죽지 않게 한다.
    """
    holdings = sorted(row.alloc.items(), key=lambda kv: (-kv[1], kv[0]))
    return Layout(
        headline=plain(mode_label(row.mode)),
        subtext=strategy_description(row.strategy_id),
        fields=[{
            "name": "배분",
            "value": "\n".join(
                f"**{t}** {ticker_label(t)} `{pct(w)}`" for t, w in holdings
            ) or "없음",
        }, {
            "name": "결정 근거",
            "value": plain(render_reason(row.strategy_id, row.signals)),
        }],
    )


def _layout_for(row: AllocationRow) -> Layout:
    builder = BUILDERS.get(row.strategy_id)
    if builder is None or not row.signals:
        return _generic_layout(row)
    try:
        return builder(row.signals, row.alloc)
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
        # 신호 형식이 어긋나도 알림 자체는 나가야 한다(관례: 알림 실패가 판정을 가리지 않는다).
        return _generic_layout(row)


def _moves_text(change) -> str:
    """신규·제거·변경을 기호 하나로 표시한다. embed는 색을 못 주므로 기호가 대신한다."""
    parts = []
    for ticker, weight in sorted(change.added.items()):
        parts.append(f"`+` **{ticker}** {ticker_label(ticker)} `{pct(weight)}`")
    for ticker, weight in sorted(change.removed.items()):
        parts.append(f"`−` **{ticker}** {ticker_label(ticker)} `{pct(weight)}`")
    for ticker, delta in sorted(change.changed.items()):
        mark = "▲" if delta.delta > 0 else "▼"
        parts.append(
            f"`{mark}` **{ticker}** {ticker_label(ticker)} "
            f"`{pct(delta.from_weight)}` → `{pct(delta.to_weight)}`"
        )
    return "\n".join(parts)


def build_card(
    curr_row: AllocationRow | Mapping[str, Any],
    prev_alloc: dict[str, float] | None,
) -> StrategyNotification:
    """전략 하나의 Discord embed와 발송 메타를 만든다."""
    row = _as_row(curr_row)
    change = analyze_allocation_change(row.alloc, prev_alloc)
    tone = palette.turnover_tone(change.turnover_pct, is_first=change.is_first)
    layout = _layout_for(row)

    description = f"### {layout.headline}"
    if layout.subtext:
        # 각주는 -# 로 작고 흐리게. 여러 줄이면 줄마다 붙여야 한다.
        description += "\n" + "\n".join(f"-# {line}" for line in layout.subtext.splitlines())

    fields = list(layout.fields)
    turnover = (
        _TURNOVER_NOTE[tone] if change.is_first or not change.has_changes
        else f"{_TURNOVER_NOTE[tone]} · 턴오버 `{numf(change.turnover_pct)}%`"
    )
    if moves := _moves_text(change):
        fields.append({"name": turnover, "value": moves})
    else:
        fields.append({"name": "변화", "value": turnover})
    fields.append(dict(_WIDTH_RULE_FIELD))

    embed: dict[str, Any] = {
        "title": f"{strategy_name(row.strategy_id)} · 위험자산 {pct(palette.risk_weight(row.alloc))}",
        "description": description,
        "color": ACCENT,
        "fields": fields,
        "footer": {"text": " · ".join(x for x in (f"적용일 {row.apply_date}", layout.note) if x)},
    }
    if len(row.alloc) >= _DONUT_MIN_HOLDINGS:
        # 우상단 작은 링. 범례는 끈다 — 80px에서는 못 읽는다. 티커·이름·비중은
        # 본문 필드가 이미 갖고 있어서 링은 비율만 눈으로 잡아 주면 된다.
        embed["thumbnail"] = {"url": allocation_chart_url(
            row.alloc, width=_DONUT_SIZE, height=_DONUT_SIZE, legend=False,
        )}

    return StrategyNotification(
        allocation_id=row.allocation_id,
        strategy_id=row.strategy_id,
        apply_date=row.apply_date,
        has_changes=change.has_changes,
        turnover_pct=change.turnover_pct,
        embed=embed,
    )


def _as_card(card: StrategyNotification | Mapping[str, Any]) -> StrategyNotification:
    if isinstance(card, StrategyNotification):
        return card
    return StrategyNotification(
        allocation_id=str(card["allocation_id"]),
        strategy_id=str(card["strategy_id"]),
        apply_date=str(card["apply_date"]),
        has_changes=bool(card["has_changes"]),
        turnover_pct=float(card["turnover_pct"]),
        embed=dict(card["embed"]),
    )


def _summary_bar(alloc: dict[str, float]) -> str:
    ordered = sorted(alloc.items(), key=lambda kv: (-kv[1], kv[0]))
    return "".join(
        (_DEFENSIVE_BLOCK if t in palette.DEFENSIVE_TICKERS else _RISK_BLOCK)
        * max(1, round(w * _SUMMARY_BAR_WIDTH))
        for t, w in ordered
    )


def build_summary(
    cards: Iterable[StrategyNotification | Mapping[str, Any]],
    allocations: Mapping[str, dict[str, float]] | None = None,
) -> dict[str, Any] | None:
    """개별 카드들에서 월간 종합 embed를 만든다.

    allocations를 주면 전략별 배분 막대를 함께 그린다(모노스페이스 코드블록).
    """
    card_list = [_as_card(card) for card in cards]
    if not card_list:
        return None

    total = len(card_list)
    changed = len([c for c in card_list if c.has_changes])
    avg = sum(c.turnover_pct for c in card_list) / total
    movers = [c for c in card_list if c.turnover_pct > 0]
    # 숫자로 비교한다 — 표시용 문자열로 정렬하면 "25%" > "100%"가 된다.
    top = max(movers, key=lambda c: c.turnover_pct) if movers else None

    fields = [
        {"name": "변화", "value": f"`{changed}` / `{total}` 전략", "inline": True},
        {"name": "평균 턴오버", "value": f"`{numf(avg)}%`", "inline": True},
        {
            "name": "최대 변동",
            "value": (
                f"**{strategy_name(top.strategy_id)}** `{numf(top.turnover_pct)}%`"
                if top else "없음"
            ),
            "inline": True,
        },
    ]
    if allocations:
        width = max(len(strategy_name(c.strategy_id)) for c in card_list)
        bars = "\n".join(
            f"{strategy_name(c.strategy_id):<{width}}  {_summary_bar(allocations[c.strategy_id])}"
            for c in card_list if c.strategy_id in allocations
        )
        if bars:
            fields.append({"name": "전략별 배분", "value": f"```\n{bars}\n```"})
    fields.append(dict(_WIDTH_RULE_FIELD))

    return {
        "title": f"월간 전략 배분 · {ym(card_list[0].apply_date)}",
        "description": "-# █ 위험자산 · ░ 현금·채권",
        "color": ACCENT,
        "fields": fields,
    }
