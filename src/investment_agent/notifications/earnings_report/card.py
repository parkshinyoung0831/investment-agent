"""실적 PNG 카드 — 템플릿 컨텍스트(ctx)와 Discord 캡션 조립.

candidates.load_pending() 항목 + run.py가 모은 extras(역사 밸류에이션·분기 건전성·이익의질
·기술·가격·주식수)를 받아 earnings.html.j2가 그릴 모든 값을 만든다. 숫자 포맷은 format,
파생/등급은 reporting.earnings.metrics·thresholds, 차트 기하·색은 charts·palette에 위임.
"""
from __future__ import annotations

from investment_agent.notifications.earnings_report import charts
from investment_agent.notifications.earnings_report import consensus
from investment_agent.notifications.earnings_report import format as fmt
from investment_agent.notifications.earnings_report import palette
from investment_agent.reporting.services.earnings import metrics
from investment_agent.reporting.services.earnings.thresholds import grade


_PERIOD_LABEL = {"Q1": "1분기", "Q2": "2분기", "Q3": "3분기", "Q4": "4분기", "FY": "연간"}


def _period_text(row: dict) -> str:
    return f"FY{row['fiscal_year']} {_PERIOD_LABEL.get(row['fiscal_period'], row['fiscal_period'])}"


def _yoy(curr, prev) -> float | None:
    c, p = metrics.as_float(curr), metrics.as_float(prev)
    if c is None or p is None or p == 0:
        return None
    return (c - p) / abs(p)


def _big(v: float | None) -> str:
    """시총·EV용 큰 금액 — 조 단위(T)까지."""
    f = metrics.as_float(v)
    if f is None:
        return "—"
    if abs(f) >= 1e12:
        return f"${f / 1e12:.2f}T"
    if abs(f) >= 1e9:
        return f"${f / 1e9:.0f}B"
    return fmt.money(f)


def _beat_color(surprise: float | None, *, reliable: bool = True) -> str:
    """상회=초록·하회=빨강. 기준이 어긋난 값은 색으로 단정하지 않는다."""
    if surprise is None or not reliable:
        return palette.MUTED
    return palette.direction(surprise)


def revisions_text(rev: dict) -> str:
    """상·하향 건수를 해석 문장으로. 서프라이즈를 읽는 전제가 된다."""
    net = rev["net"]
    if net > 0:
        return "발표 전 컨센서스가 오르는 중이었습니다 — 소폭 상회는 사실상 실망일 수 있습니다."
    if net < 0:
        return "발표 전 컨센서스가 내려가는 중이었습니다 — 낮아진 눈높이를 넘은 것일 수 있습니다."
    return "발표 전 컨센서스는 크게 움직이지 않았습니다."


def _inconsistent_7d(rev: dict) -> bool:
    """7일 값이 30일 값을 넘는가 — 출처가 두 창을 따로 갱신해 생기는 어긋남.

    7일은 30일에 포함되므로 논리적으로 30일이 크거나 같아야 한다. 실측에서 관심종목
    7개 중 3개가 어긋났다(UBER 상향 7일 7 대 30일 6, TSLA 하향 16 대 14,
    GOOGL 하향 18 대 15). 값을 깎아 맞추면 출처에 없는 숫자를 만들게 되고, 줄을
    지우면 어긋났다는 사실까지 숨는다 — 그대로 내되 어긋났다고 표시한다.
    """
    for recent, window in (("up_7d", "up"), ("down_7d", "down")):
        near = rev.get(recent)
        far = rev.get(window)
        if near is not None and far is not None and int(near) > int(far):
            return True
    return False


def _expectation_view(data: dict | None) -> dict | None:
    """consensus.build() 결과를 템플릿이 그대로 쓸 수 있는 표기로 바꾼다."""
    if not data:
        return None
    eps, revenue, revisions = data.get("eps"), data.get("revenue"), data.get("revisions")
    view: dict = {
        "snapshot_label": (
            f"{data['snapshot_date'].month}/{data['snapshot_date'].day} 기준"
            if data.get("snapshot_date") else None
        ),
        "lead_days": data.get("lead_days"),
        "has_numbers": bool(eps or revenue),
    }
    if eps:
        view["eps"] = {
            "estimate": fmt.num(eps["estimate"]),
            "actual": fmt.num(eps["actual"]) if eps.get("actual") is not None else None,
            "range": (
                f"{eps['low']:.2f} – {eps['high']:.2f}"
                if eps.get("low") is not None and eps.get("high") is not None else None
            ),
            "analysts": eps.get("analysts"),
            "surprise": fmt.yoy(eps["surprise"]).replace(" YoY", "") if eps.get("reliable") else None,
            "color": _beat_color(eps.get("surprise"), reliable=bool(eps.get("reliable"))),
            "position": (
                round(eps["position"] * 100, 1) if eps.get("position") is not None else None
            ),
            # 카드 아래쪽 'EPS' 블록의 선은 GAAP 계산값이라 기준이 다르다 —
            # 여기 숫자가 무엇을 비교한 것인지 밝힌다.
            "basis": "조정 기준",
            "unreliable": eps.get("actual") is not None and not eps.get("reliable"),
        }
    if revenue:
        view["revenue"] = {
            "estimate": fmt.money(revenue["estimate"]),
            "actual": fmt.money(revenue["actual"]) if revenue.get("actual") is not None else None,
            "range": (
                f"{fmt.money(revenue['low'])} – {fmt.money(revenue['high'])}"
                if revenue.get("low") is not None and revenue.get("high") is not None else None
            ),
            "analysts": revenue.get("analysts"),
            "surprise": (
                fmt.yoy(revenue["surprise"]).replace(" YoY", "")
                if revenue.get("surprise") is not None else None
            ),
            "color": _beat_color(revenue.get("surprise")),
            "position": (
                round(revenue["position"] * 100, 1) if revenue.get("position") is not None else None
            ),
        }
    if revisions:
        # 상향이 '좋다'는 뜻이 아니다 — 눈높이가 올라갔다는 뜻이고, 그래서 같은 상회도
        # 다르게 읽힌다. 색으로 단정하지 않고 문장이 의미를 지게 둔다.
        view["revisions"] = {
            **revisions,
            "text": revisions_text(revisions),
            "has_7d": revisions.get("up_7d") is not None or revisions.get("down_7d") is not None,
            "inconsistent_7d": _inconsistent_7d(revisions),
        }
    return view


def build(item: dict, extras: dict | None = None) -> tuple[dict, str]:
    """항목(+extras) → (템플릿 ctx, Discord 캡션)."""
    ex = extras or {}
    row = item["row"]
    prev = item.get("prev")
    history = item.get("history") or []
    val = item.get("valuation") or {}
    d = metrics.derive(row, prev)
    badge, color, label = grade(d, has_anomaly=bool(row.get("_has_anomaly")))
    market_prices = charts.prices_before_filing(ex.get("prices") or [], row.get("filed_at"))
    market_shares = [
        point for point in (ex.get("shares") or [])
        if str(point[0]) < str(row.get("filed_at") or "")
    ]
    market_technicals = charts.technical_snapshot(market_prices)

    # 목표주가는 v1에 저장하지 않지만, 서프라이즈 이력은 reporting view에서 읽는다.
    # 각 자료가 없으면 consensus.build가 해당 블록만 생략하고 카드는 계속 만든다.
    expectation = consensus.build(
        row,
        list(ex.get("earnings_estimates") or []),
        list(ex.get("surprise_history") or []),
        list(ex.get("price_targets") or []),
    )

    # 표시 이름: 한글명 우선, 없으면 영문명, 둘 다 없으면 티커. 영문명은 메인과 다를 때만 별도 표기.
    names = item.get("names") or {}
    ticker = row["ticker"]
    name_ko = names.get("name_ko")
    name_en = names.get("name")
    title_main = name_ko or name_en or ticker
    title_en = name_en if (name_en and name_en != title_main) else None

    ctx = {
        # 헤더
        "ticker": ticker,
        "title_main": title_main,
        "title_en": title_en,
        "period": _period_text(row),
        "form_type": row.get("form_type") or "—",
        "period_end": row.get("period_end"),
        "filed_at": row.get("filed_at"),
        "price": (f"${metrics.as_float(val.get('price')):.2f}" if val.get("price") is not None else None),
        "market_cap": _big(val.get("market_cap")),
        "enterprise_value": _big(val.get("enterprise_value")),
        "badge": badge,
        "accent": f"#{color:06x}",
        "label": label,
        "tokens": {
            "primary": palette.PRIMARY,
            "primary_active": palette.PRIMARY_ACTIVE,
            "ink": palette.INK,
            "body": palette.BODY,
            "muted": palette.MUTED,
            "muted_soft": palette.MUTED_SOFT,
            "hairline": palette.HAIRLINE,
            "hairline_soft": palette.HAIRLINE_SOFT,
            "canvas": palette.CANVAS,
            "surface_soft": palette.SURFACE_SOFT,
            "surface_strong": palette.SURFACE_STRONG,
            "surface_dark": palette.SURFACE_DARK,
            "surface_dark_elevated": palette.SURFACE_DARK_ELEVATED,
            "on_dark": palette.ON_DARK,
            "on_dark_soft": palette.ON_DARK_SOFT,
            "semantic_up": palette.GREEN,
            "semantic_down": palette.RED,
            "accent_yellow": palette.AMBER,
        },
        # 섹션들
        "combo": charts.combo(
            history,
            ex.get("quality_history") or [],
            (expectation or {}).get("revenue"),
            (expectation or {}).get("next_quarter"),
        ),
        "eps_trend": charts.eps_trend(history, expectation),
        "expectation": _expectation_view(expectation),
        "val_history": charts.valuation_history(ex.get("hist")),
        "cashflow_quarters": charts.cashflow_quarters(history),
        "waterfall": charts.income_waterfall(row, prev),
        "profitability": charts.quality(item.get("health")),
        "gauges": charts.gauges(item.get("health")),
        "cashflow_bridge": charts.cashflow_bridge(row, prev),
        "working_capital": charts.working_capital(row, history),
        "shareholder_return": charts.shareholder_return(market_prices, market_shares),
        "dividend_trend": charts.dividend_trend(market_prices),
        "technicals": charts.technicals(market_technicals, market_prices),
        "price_range": charts.week52_range(
            market_technicals, (expectation or {}).get("price_target")
        ),
        # 하단 요약 — 잔액(분기)과 이익의 질(TTM)을 한 줄에 모은다. 둘 다 "그래서 현금이
        # 얼마나 남았나"의 결론이라, 본문 블록을 차지하기보다 마무리 줄이 맞다.
        "footer": [
            ("FCF(분기)", fmt.money(d["fcf"])),
            ("현금", fmt.money(d["cash"])),
            ("순부채", fmt.money(d["net_debt"])),
            *(
                (item["name"], item["value"])
                for item in (charts.earnings_quality(ex.get("eq")) or [])
            ),
        ],
    }
    caption_name = f"{title_main} · {title_en}" if title_en else title_main
    caption = f"{badge} {caption_name} ({ticker}) — {ctx['period']} 실적"
    return ctx, caption
