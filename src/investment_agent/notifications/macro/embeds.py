"""매크로 워치 Discord embed 조립.

macro_core는 여전히 PNG다 — 4섹션이 한 장에서 서로를 설명하는 대시보드라 쪼개면
읽기가 나빠진다. watch는 지표 "목록"이라 그림이 아니라 네이티브
글자가 맞다 — PNG는 Discord가 폭 ~550px로 줄여 숫자가 뭉개지고, 검색도 복사도 안 된다.

판정(eval_row)과 표시 문구(base_card 등)는 core·watch 공통 SSOT를 그대로
쓴다. 이 파일이 새로 하는 일은 그 결과를 embed 필드·표로 접는 것뿐이다.

DESIGN-system.md를 embed가 표현할 수 있는 범위에서 따른다.
- 색 voltage 하나. embed 왼쪽 막대는 면적 채움이므로 등급과 무관하게 항상
  Brand Blue 하나만 쓴다. 등급은 색이 아니라 WATCH_TIER_LABEL의 아이콘
  (🔴/🟠/🟡)으로 낸다 — 새 색 팔레트를 여기서 만들지 않는다.
- 숫자는 모노스페이스 표(notifications/renderers/text.py의 table). 지표명이 세그먼트 이름과 달리
  짧고 어휘가 고정돼 있어(≈50종) 코드블록 정렬이 적합하다.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from investment_agent.notifications.renderers.text import table as _table
from investment_agent.reporting.services.macro import palette
from investment_agent.reporting.services.macro.constants import (
    CAT_ICON, TIER_ORDER, WATCH_CAT_ORDER, WATCH_TIER_LABEL,
)
from investment_agent.reporting.services.macro.format import base_card, code_map, short_of

ACCENT = int(palette.PRIMARY.lstrip("#"), 16)

# 등급 아이콘. WATCH_TIER_LABEL(이미 있는 워치 섹션 헤더 아이콘)을 그대로 재사용한다 —
# 색맹 배려까지 담긴 값이라 여기서 또 만들 이유가 없다.
_TIER_ICON = {short_of(tier): icon for tier, (icon, _label) in WATCH_TIER_LABEL.items()}
_NEUTRAL = "·"  # 등급 없음

# embed 필드 값 상한(Discord 1024자). 넘으면 뒤에서부터 줄이고 잘림을 알린다.
_FIELD_LIMIT = 1024


def _tier_icon(tier) -> str:
    return _TIER_ICON.get(short_of(tier), _NEUTRAL)


def _capped_table(rows: list[tuple[str, ...]], *, right: tuple[int, ...] = ()) -> str:
    """표가 embed 필드 한도(1024자)를 넘으면 뒤에서부터 줄이고 잘림을 표시한다.

    카테고리 하나에 지표가 몰릴 때도 Discord 한도를 넘지 않게 하는 안전망이다.
    """
    if not rows:
        return ""
    value = _table(rows, right=right)
    if len(value) <= _FIELD_LIMIT:
        return value
    kept = list(rows)
    while len(kept) > 1:
        kept.pop()
        note = f"\n-# 외 {len(rows) - len(kept)}건 (한도 초과로 생략)"
        candidate = _table(kept, right=right) + note
        if len(candidate) <= _FIELD_LIMIT:
            return candidate
    return _table(kept, right=right)[:_FIELD_LIMIT]


# ── 워치 ──────────────────────────────────────────────────────────────────
def build_watch(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """임계 통과 지표 embed 1장. 필드=등급, 값=표(지표|값|임계사유). 한국은 별도 필드.

    rows는 watch.eval_thresholds()가 이미 tier·reason을 채운 '통과분'만 받는다.
    """
    tiers: dict[str, list[dict[str, Any]]] = {t: [] for t in TIER_ORDER}
    kr: list[dict[str, Any]] = []
    for r in rows:
        card = {
            **base_card(r), "tier": r["tier"], "reason": r.get("reason") or "",
            "category": r.get("category") or "",
        }
        (kr if card["kr"] else tiers[card["tier"]]).append(card)

    def _cat_rank(card: dict[str, Any]) -> int:
        cat = card["category"] if card["category"] in WATCH_CAT_ORDER else "equity_index"
        return WATCH_CAT_ORDER.index(cat)

    fields: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for tier in TIER_ORDER:
        items = sorted(tiers[tier], key=_cat_rank)
        counts[short_of(tier)] = len(items)
        if not items:
            continue
        icon, label = WATCH_TIER_LABEL[tier]
        table_rows = [
            (f"{CAT_ICON.get(c['category'], '')} {c['name']}".strip(), c["value"], c["reason"] or "—")
            for c in items
        ]
        fields.append({
            "name": f"{icon} {label} `{len(items)}`",
            "value": _capped_table(table_rows, right=(1,)),
        })

    if kr:
        table_rows = [
            (f"{_tier_icon(c['tier'])} {c['name']}", c["value"], c["reason"] or "—")
            for c in kr
        ]
        fields.append({
            "name": f"🇰🇷 한국 지표 `{len(kr)}`",
            "value": _capped_table(table_rows, right=(1,)),
        })

    headline = " · ".join(
        f"{icon} {counts.get(short_of(t), 0)}" for t, (icon, _label) in WATCH_TIER_LABEL.items()
    )
    if kr:
        headline += f" · 🇰🇷 {len(kr)}"

    return {
        "title": "신호 워치",
        "description": f"### {headline}\n-# 평시 범위를 벗어난 지표만 선별해 보여줍니다",
        "color": ACCENT,
        "fields": fields[:25],
        "footer": {"text": f"{date.today().isoformat()} · {code_map(rows)}"[:2048]},
    }
