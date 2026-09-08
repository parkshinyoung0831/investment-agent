"""거장 13F Discord embed 조립.

13F의 값어치는 '누가 무엇을 샀나'가 아니라 **여러 명의 움직임이 겹치거나 갈리는
지점**에 있다. 그래서 형식도 그 모양을 따른다.

  분기 종합  합의·충돌 매트릭스 — 종목 × 운용사 격자 하나로 공동매수·공동매도·
             의견충돌을 동시에 읽는다. 셋을 따로 나열하면 같은 종목이 세 번 나온다.
  개별 제출  포트폴리오 한 장 — 무엇을 얼마나 들고 있고, 이번 분기에 무엇이 바뀌었나.

DESIGN-system.md를 embed 범위에서 따른다.
- 색 voltage 하나. embed 색 막대는 면적 채움이라 상승·하락 색을 쓰지 않는다.
- 매수·매도 구분은 색이 아니라 기호(+ / −)로 한다. 모바일에서 색 대비가 뭉개져도
  기호는 남는다.
- 결론은 `###`, 각주는 `-#`, 숫자는 백틱(모노스페이스).
"""
from __future__ import annotations

from typing import Any

from investment_agent.notifications.renderers.text import clip as _clip
from investment_agent.notifications.renderers.text import table as _table
from investment_agent.notifications.renderers.text import width as _width
from . import palette, quickchart

ACCENT = int(palette.PRIMARY.lstrip("#"), 16)

# 매트릭스 기호. 색 없이도 방향이 읽히도록 모양으로 구분한다.
_BUY, _SELL, _HOLD, _NONE = "+", "−", "·", " "
# 한 embed에 담을 최대 행. 넘치면 Discord 1024자 제한에 걸린다.
_MATRIX_MAX_ROWS = 12
_CO_HELD_MAX = 6
MOVE_MAX = 10        # 늘림·줄임 각 칸에 세우는 최대 종목 수
# Discord는 inline 필드를 한 줄에 3개씩 채우고, 그 줄의 칸 수만큼 폭을 나눈다.
# 두 줄 모두 세 번째 자리에 빈 칸을 끼워야 2×2로 놓이면서 열도 맞는다 —
# 둘째 줄만 2칸이면 폭이 1/2씩이라 위아래 열이 어긋난다.
_SPACER = {"name": "​", "value": "​", "inline": True}

# 13F 한계. 카드마다 반복하지 않고 푸터에 한 줄로 둔다.
_FOOTER_NOTE = "13F는 분기말 보유 현황 · 숏·파생·해외·비상장은 빠져 있음"


# 좁은 inline 칸에서 이름과 증감이 한 줄에 들어가는 한계 폭(한글은 두 칸).
_MOVE_NAME_WIDTH = 10


def _move_label(row: dict) -> str:
    """이름 우선 표기. 한글이 있으면 한글, 없으면 영문, 둘 다 길면 티커로 떨어진다."""
    ticker = str(row.get("ticker") or "")
    name = str(row.get("company_name") or row.get("company_name_en") or "").strip()
    if name and _width(name) <= _MOVE_NAME_WIDTH:
        return f"**{name}**"
    if ticker.isalpha() and len(ticker) <= 5:
        return f"**{ticker}**"
    return f"**{_clip(name, _MOVE_NAME_WIDTH)}**" if name else f"`{ticker}`"


# ── 분기 종합 ─────────────────────────────────────────────────────────
def _matrix(quarterly: dict) -> tuple[str, dict[str, int]]:
    """종목 × 운용사 매트릭스. 반환값은 (코드블록, 표에서 센 통계).

    통계는 표를 세어 만든다 — 원본 집계값을 따로 쓰면 헤드라인 숫자와 표가 어긋난다
    (buy_signal_total은 6인데 표에 보이는 공동매수는 3인 식으로).

    한 종목을 한 줄로 놓고 운용사별로 +(매수) −(매도) ·(보유·무변동)를 찍는다.
    같은 줄에 +와 −가 함께 있으면 그게 의견 충돌이다 — 따로 셀 필요가 없다.
    """
    empty = {"buy": 0, "sell": 0, "conflict": 0}
    activities = quarterly.get("activities") or []
    # 열 순서는 활동량이 큰 순. 이번 분기에 제출한 운용사만 열로 세운다.
    columns = [(a["initials"], a["name"]) for a in activities]
    if not columns:
        return "", empty

    by_ticker: dict[str, dict[str, str]] = {}

    def mark(rows: list[dict], symbol: str) -> None:
        for row in rows:
            ticker = str(row.get("ticker") or "")
            if not ticker:
                continue
            cell = by_ticker.setdefault(ticker, {})
            for name in row.get("managers") or row.get("buy_names") or []:
                cell[str(name)] = symbol

    # 공동매수·공동매도는 영문 이름, 충돌은 한글 이름을 준다 — 둘 다 받아 둔다.
    for row in quarterly.get("buys") or []:
        mark([row], _BUY)
    for row in quarterly.get("sells") or []:
        mark([row], _SELL)
    for row in quarterly.get("conflicts") or []:
        cell = by_ticker.setdefault(str(row.get("ticker") or ""), {})
        for name in row.get("buy_names") or []:
            cell[str(name)] = _BUY
        for name in row.get("sell_names") or []:
            cell[str(name)] = _SELL

    by_ticker.pop("", None)
    if not by_ticker:
        return "", empty

    # 이름 표기가 한글/영문으로 섞여 오므로 두 표기를 모두 이니셜에 매핑한다.
    alias: dict[str, str] = {}
    for activity in activities:
        for key in ("name", "name_en"):
            if value := activity.get(key):
                alias[str(value)] = activity["initials"]

    def row_for(ticker: str) -> tuple[str, ...]:
        cells = by_ticker[ticker]
        marks = []
        for initial, _ in columns:
            symbol = _HOLD
            for name, sign in cells.items():
                if alias.get(name) == initial:
                    symbol = sign
                    break
            marks.append(symbol)
        return (ticker, *marks)

    # 움직인 운용사가 많은 종목부터. 동수면 충돌(＋와 －가 공존)을 앞에 둔다.
    def sort_key(ticker: str) -> tuple:
        marks = row_for(ticker)[1:]
        moved = sum(m in (_BUY, _SELL) for m in marks)
        conflicted = _BUY in marks and _SELL in marks
        return (-moved, not conflicted, ticker)

    tickers = sorted(by_ticker, key=sort_key)[:_MATRIX_MAX_ROWS]
    header = ("", *(initial for initial, _ in columns))
    body = [row_for(t) for t in tickers]

    stats = {"buy": 0, "sell": 0, "conflict": 0}
    for row in body:
        marks = row[1:]
        buys, sells = marks.count(_BUY), marks.count(_SELL)
        if buys and sells:
            stats["conflict"] += 1
        elif buys >= 2:
            stats["buy"] += 1
        elif sells >= 2:
            stats["sell"] += 1
    return _table([header, *body]), stats


def build_quarterly(quarterly: dict) -> dict[str, Any]:
    """분기 종합 embed. 합의와 충돌을 격자 하나로 보여준다."""
    matrix, stats = _matrix(quarterly)
    filed, active = quarterly["filed_count"], quarterly["active_count"]

    headline = " · ".join(
        part for part in (
            f"공동 매수 {stats['buy']}" if stats["buy"] else "",
            f"공동 매도 {stats['sell']}" if stats["sell"] else "",
            f"의견 충돌 {stats['conflict']}" if stats["conflict"] else "",
        ) if part
    ) or "합의·충돌 없음"
    subtext = [f"제출 {filed}/{active} · 이번 분기 변동 {quarterly['material_move_count']}건"]
    if quarterly["provisional"]:
        subtext.append("잠정 집계 — 미제출: " + ", ".join(quarterly["missing_names"]))

    fields: list[dict[str, Any]] = []
    if matrix:
        fields.append({
            # 필드명은 연속 공백이 하나로 합쳐진다. 간격으로 나누면 뭉치므로 구분자를 쓴다.
            "name": "합의와 충돌  |  + 매수  |  − 매도  |  · 유지",
            "value": matrix,
        })

    if radar := (quarterly.get("radar_status") or []):
        fields.append({
            "name": "레이더 제출 현황",
            "value": "\n".join(
                f"**{g['label']}** `{g['filed']}/{g['total']}`" for g in radar
            ),
        })

    if activities := (quarterly.get("activities") or []):
        fields.append({
            "name": "운용사별 회전율",
            "value": _table([
                (_clip(str(a["name"]), 20), f"{a['holding_count']}종목", f"{a['change_rate']}%")
                for a in activities
            ], right=(1, 2)),
        })

    embed: dict[str, Any] = {
        "title": f"{quarterly['quarter']} 거장 13F 레이더",
        "description": f"### {headline}\n" + "\n".join(f"-# {line}" for line in subtext),
        "color": ACCENT,
        "fields": fields,
        "footer": {"text": f"기준일 {quarterly['period']} · {_FOOTER_NOTE}"},
    }
    if chart := quickchart.co_held_bars((quarterly.get("co_held") or [])[:_CO_HELD_MAX]):
        embed["image"] = {"url": chart}
    return embed


# ── 개별 제출 ─────────────────────────────────────────────────────────
def build_filing(ctx: dict) -> dict[str, Any]:
    """운용사 하나의 13F. 포트폴리오 도넛 하나와 변화 네 칸을 담는다.

    변화는 신규·축소·확대·청산을 각각 제 칸에 둔다. 둘씩 묶으면 한 칸 안에서 서로
    다른 성격(새로 산 것과 비중만 늘린 것)이 섞여 목록이 길어진다.
    """
    counts = ctx["counts"]

    # 보유 종목 이름을 도넛 범례로 넘긴다(한글 우선, 없으면 영문).
    names = {
        str(row.get("ticker")): str(row.get("company_name") or row.get("company_name_en") or "")
        for row in ctx.get("top_holdings") or []
    }
    donut_rows = [
        {**row, "name": names.get(str(row.get("label")), "")}
        for row in ctx.get("donut") or []
    ]

    def moves(kind: str, mark: str) -> str:
        section = next(
            (s for s in ctx.get("sections") or [] if s["kind"] == kind), None
        )
        rows = (section["rows"] if section else [])[:MOVE_MAX]
        lines = []
        for row in rows:
            delta = str(row.get("weight_delta") or "")
            lines.append(
                f"{mark} {_move_label(row)}" + (f" `{delta}`" if delta else "")
            )
        if hidden := max(0, int(counts.get(kind) or 0) - len(rows)):
            lines.append(f"-# 외 {hidden}건")
        return "\n".join(lines) or "없음"

    # 왼쪽 위 신규 · 오른쪽 위 축소 / 왼쪽 아래 확대 · 오른쪽 아래 청산.
    # 빈 칸이 줄을 끊어 2×2로 놓이게 한다.
    fields: list[dict[str, Any]] = [
        {"name": f"신규 {counts['new']}", "value": moves("new", "+"), "inline": True},
        {"name": f"축소 {counts['decrease']}", "value": moves("decrease", "▼"), "inline": True},
        _SPACER,
        {"name": f"확대 {counts['increase']}", "value": moves("increase", "▲"), "inline": True},
        {"name": f"청산 {counts['exit']}", "value": moves("exit", "−"), "inline": True},
        _SPACER,
    ]

    embed: dict[str, Any] = {
        "title": f"{ctx['name']} · {ctx['fund_name']}",
        "description": (
            f"### {ctx['long_equity_value']} Long Equity\n"
            f"-# {ctx['long_equity_count']}종목 · Top5 집중도 {ctx['top5_concentration']}"
            f" · 회전율 {ctx['change_rate']}%"
        ),
        "color": ACCENT,
        "url": ctx["source_url"],
        "fields": fields,
        "footer": {"text": f"{ctx['quarter']} · 공시 {ctx['filing_date']} · {_FOOTER_NOTE}"},
    }
    if donut := quickchart.portfolio_donut(donut_rows):
        embed["image"] = {"url": donut}
    return embed
