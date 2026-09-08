"""세그먼트 Discord embed 조립 — 축 하나가 카드 하나.

펀더멘탈 본문은 계속 PNG 대시보드다(그쪽은 한 장에서 지표들이 서로를 설명해야 해서
쪼개면 읽기가 나빠진다). 세그먼트만 embed로 뺀다 — 회사가 보고하는 축은 사업·제품·
지역으로 종류가 다르고 **축끼리 합산하면 안 되는데**, 한 이미지에 표를 쌓아 두면
그 경계가 보이지 않기 때문이다. 카드가 나뉘면 경계가 곧 눈에 보인다.

  축 하나 = embed 하나 = 그림 하나 + 목록 하나
  그림은 구성(도넛) 또는 규모(막대) — 어느 쪽인지는 quickchart가 데이터로 고른다
  목록은 그림이 말하지 않는 것만 — 매출 금액과 YoY

DESIGN-system.md를 embed 범위에서 따른다.
- 색 voltage 하나. embed 색 막대는 면적 채움이라 상승·하락 색을 쓰지 않는다.
- 방향은 색이 아니라 부호(+/−)로. 모바일에서 색 대비가 뭉개져도 부호는 남는다.
- 숫자만 백틱(모노스페이스), 각주는 `-#`. 세그먼트 이름은 길어서 코드블록에 넣으면
  잘라야 하는데, 자르면 서로 구분이 안 된다 — _lines() 주석 참고.
"""
from __future__ import annotations

from typing import Any

from investment_agent.notifications.renderers import text
from investment_agent.notifications.earnings_report import format as fmt
from investment_agent.notifications.earnings_report import palette, profiles, quickchart
from investment_agent.reporting.services.earnings import metrics

ACCENT = int(palette.PRIMARY.lstrip("#"), 16)

_PERIOD_LABEL = {"Q1": "1분기", "Q2": "2분기", "Q3": "3분기", "Q4": "4분기", "FY": "연간"}
# 이름 안전장치. 회사가 보고한 이름을 그대로 쓰되, 회계 잔차 항목은 폭 179까지 간다
# ("Segment Reconciling Items Equity In Earnings Of Joint Ventures And…").
# 그런 한 줄이 카드를 통째로 먹지 않게 여기서만 막는다 — 실제 이름의 99%는 61 이하다.
_NAME_LIMIT = 56


def _f(value: Any) -> float | None:
    return metrics.as_float(value)


def _signed(value: float | None) -> str:
    """부호를 붙인 퍼센트. 방향을 색이 아니라 부호로 말한다."""
    if value is None:
        return "—"
    return f"{'+' if value >= 0 else ''}{value * 100:.1f}%"


def _period_text(row: dict) -> str:
    return f"FY{row['fiscal_year']} {_PERIOD_LABEL.get(row['fiscal_period'], row['fiscal_period'])}"


def _join(parts: list[str | None]) -> str:
    return " · ".join(part for part in parts if part)


def _footnote(line: str) -> str:
    return f"-# {line}" if line else ""


def _rows(rows: list[dict]) -> list[dict]:
    """차트·표가 함께 쓸 표시용 행. 비중은 축이 verified일 때만 채워져 있다."""
    return [
        {
            "name": str(row.get("name") or "—"),
            "is_remainder": bool(row.get("is_remainder")),
            "revenue": _f(row.get("revenue")),
            "revenue_pct": _f(row.get("revenue_pct")),
            "revenue_yoy": _f(row.get("revenue_yoy")),
            "profit_loss": _f(row.get("profit_loss")),
            "profit_margin": _f(row.get("profit_margin")),
            "profit_label": row.get("profit_measure_label") or "부문이익",
            "profit_verified": row.get("profit_quality_status") == "verified",
        }
        for row in rows
    ]


def _lines(rows: list[dict], *, with_share: bool, with_yoy: bool) -> str:
    """세그먼트 한 줄씩. 코드블록이 아니라 네이티브 글자다.

    코드블록은 Discord에서 줄바꿈 없이 가로 스크롤되므로 열을 맞추려면 이름을 잘라야
    했다. 그런데 세그먼트 이름은 중앙값 20칸에 꼬리가 179칸까지 가서, 자르면 절반이
    뭉개지고("Energy Generatio"가 두 줄) 자르지 않으면 스크롤된다.

    구성 비율은 이미 도넛이 말하므로 표가 열을 맞춰 크기 비교까지 해 줄 이유는 없다.
    이름을 온전히 보이는 쪽을 택하고, 숫자만 백틱으로 감싸 모노스페이스로 낸다.
    행은 매출 내림차순이라 순서가 곧 크기다.
    """
    out = []
    for row in rows:
        numbers = [fmt.money(row["revenue"])]
        if with_share:
            numbers.append(fmt.pct(row["revenue_pct"], digits=0))
        if with_yoy:
            numbers.append(_signed(row["revenue_yoy"]))
        name = text.shorten(row["name"], _NAME_LIMIT)
        out.append(f"**{name}** " + " ".join(f"`{value}`" for value in numbers))
    return "\n".join(out)


def _profit_field(rows: list[dict]) -> dict[str, Any] | None:
    """부문이익은 매출과 같은 표에 붙이지 않고 필드를 따로 세운다.

    한 줄에 이름·매출·YoY·이익·이익률 다섯 칸을 넣으면 60자를 넘어 모바일 코드블록이
    가로로 잘린다. 각주 한 줄로 이어 붙이면 세그먼트가 셋만 돼도 줄이 접힌다.
    회사가 쓴 이익 정의(영업이익·매출총이익 등)를 필드 이름이 그대로 진다.
    """
    earners = [
        row for row in rows
        if row["profit_verified"] and row["profit_loss"] is not None
    ]
    if not earners:
        return None
    lines = [
        f"**{text.shorten(row['name'], _NAME_LIMIT)}** `{fmt.money(row['profit_loss'])}`"
        + (f" `{fmt.pct(row['profit_margin'])}`" if row["profit_margin"] is not None else "")
        for row in earners
    ]
    return {
        "name": f"{earners[0]['profit_label']} · 이익률",
        "value": "\n".join(lines),
    }


def _axis_embed(item: dict, axis: dict, title_main: str, profile: str) -> dict[str, Any] | None:
    rows = _rows(axis.get("rows") or [])
    if not rows:
        return None

    chart = quickchart.axis_chart(rows)
    # 도넛 범례가 비중을 갖는다 → 표에서 비중 칸을 뺀다(같은 값을 두 번 두지 않는다).
    # 막대로 떨어졌거나 그림이 없으면 비중을 아는 한 표가 그걸 진다.
    share_rows = [row for row in rows if row["revenue_pct"] is not None]
    donut = chart is not None and len(share_rows) >= 2
    with_share = not donut and bool(share_rows)
    with_yoy = any(row["revenue_yoy"] is not None for row in rows)

    row = item["row"]
    member_count = int(axis.get("member_count") or 0)
    shown_count = int(axis.get("shown_count") or 0)
    type_label = axis.get("type_label") or "사업"

    fields: list[dict[str, Any]] = [{
        "name": _join(["매출", "비중" if with_share else None, "YoY" if with_yoy else None]),
        "value": _lines(rows, with_share=with_share, with_yoy=with_yoy),
    }]
    if profit_field := _profit_field(rows):
        fields.append(profit_field)

    embed: dict[str, Any] = {
        "title": f"{title_main} · {type_label}부문",
        "description": _footnote(_join([
            f"세그먼트 {member_count}개" if member_count <= shown_count
            else f"세그먼트 {member_count}개 · 상위 {shown_count}개 + 기타",
            f"coverage {fmt.pct(_f(axis.get('coverage_ratio')), digits=0)}"
            if axis.get("coverage_ratio") is not None else None,
        ])),
        "color": ACCENT,
        "fields": fields,
        # 업종 프로필은 세그먼트를 읽는 전제다 — 보험·리츠는 '매출'의 뜻부터 다르다.
        "footer": {"text": _join([_period_text(row), row.get("form_type"), profile])},
    }
    if chart:
        embed["image"] = {"url": chart}
    return embed


def build_segments(item: dict) -> list[dict[str, Any]]:
    """축마다 embed 하나. 표시 가능한 축이 없으면 빈 리스트."""
    state = item.get("segment_state") or {}
    if str(state.get("status") or "processing") not in {"verified", "partial"}:
        return []

    names = item.get("names") or {}
    ticker = str(item["row"]["ticker"])
    title_main = names.get("name_ko") or names.get("name") or ticker
    profile = profiles.label(profiles.classify(names))

    return [
        embed for embed in (
            _axis_embed(item, axis, title_main, profile)
            for axis in (state.get("axes") or [])
        ) if embed
    ]
