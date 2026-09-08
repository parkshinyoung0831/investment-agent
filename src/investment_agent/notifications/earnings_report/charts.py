"""실적 카드 차트 기하(geometry) 계산.

PNG는 Playwright 정적 캡처라 JS를 안 쓴다 → 막대 높이·꺾은선 좌표·게이지 마커 위치를
여기서 미리 계산해 템플릿엔 그릴 수치만 넘긴다. 모두 순수 함수(테스트 쉬움).
"""
from __future__ import annotations

from datetime import date, timedelta
import math
import statistics
from typing import Any

from investment_agent.notifications.earnings_report import format as fmt
from investment_agent.notifications.earnings_report import palette

def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _q_label(row: dict) -> str:
    return f"{row['fiscal_period']}·{str(row['fiscal_year'])[2:]}"


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _clamp_pct(v: float) -> float:
    return max(0.0, min(100.0, v))


def _eps_diluted(row: dict) -> float | None:
    """분기 희석 EPS = 보통주 귀속 순이익 / 희석 평균주식수.
    원천 EPS 컬럼을 보관하지 않으므로 순이익·희석주식수로 직접 계산한다."""
    ni = _num(row.get("net_income_to_common_shareholders"))
    if ni is None:
        ni = _num(row.get("net_income"))
    return _div(ni, _num(row.get("shares_fully_diluted_average")))


def _nice_axis(values: list[float], *, intervals: int = 4) -> tuple[float, float, list[float]]:
    """양수·음수 모두 포함하는 읽기 좋은 공통 축 범위를 만든다."""
    vals = [v for v in values if math.isfinite(v)]
    if not vals:
        return 0.0, 1.0, [0.0, 0.25, 0.5, 0.75, 1.0]
    lo, hi = min(0.0, min(vals)), max(0.0, max(vals))
    if lo == hi:
        hi = lo + 1.0
    rough = (hi - lo) / intervals
    magnitude = 10 ** math.floor(math.log10(abs(rough)))
    normalized = rough / magnitude
    step_base = 1 if normalized <= 1 else (2 if normalized <= 2 else (5 if normalized <= 5 else 10))
    step = step_base * magnitude
    axis_lo = math.floor(lo / step) * step
    axis_hi = math.ceil(hi / step) * step
    count = max(1, int(round((axis_hi - axis_lo) / step)))
    ticks = [axis_lo + i * step for i in range(count + 1)]
    return axis_lo, axis_hi, ticks


def _axis_money(v: float) -> str:
    sign = "−" if v < 0 else ""
    a = abs(v)
    if a >= 1e12:
        return f"{sign}${a / 1e12:.1f}T"
    if a >= 1e9:
        return f"{sign}${a / 1e9:.0f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.0f}M"
    return f"{sign}${a:.0f}"


def _signed_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{'+' if v >= 0 else ''}{v * 100:.1f}%"


# 게이지 색(palette.gauge_zone) → 한 줄 태그 매핑. 색 판정은 palette가 SSOT.
_ZONE_TAG = {palette.GREEN: "양호", palette.AMBER: "주의", palette.RED: "경계", palette.MUTED: "—"}


def _gauge(name: str, value: float, *, lower_better: bool,
           good: float, bad: float, value_label: str) -> dict:
    color = palette.gauge_zone(value, good=good, bad=bad, lower_better=lower_better)
    return {
        "name": name,
        "value": value_label,
        "tag": _ZONE_TAG.get(color, "—"),
        "color": color,
    }


def gauges(health: dict | None) -> list[dict] | None:
    """재무건전성 — 순부채/EBITDA·Altman Z''.

    값과 등급을 함께 표시해 공간을 적게 쓰면서도 좋고·나쁨의 경계를 전달한다.
    """
    if not health:
        return None
    out = []
    nde = _num(health.get("net_debt_to_ebitda"))
    if nde is not None:
        out.append(_gauge(
            "순부채/EBITDA", nde, lower_better=True, good=1, bad=3,
            value_label=(f"{nde:.1f}x" if nde >= 0 else "순현금"),
        ))
    z = _num(health.get("altman_z"))
    if z is not None:
        out.append(_gauge("Altman Z''", z, lower_better=False, good=2.6, bad=1.1, value_label=f"{z:.1f}"))
    return out or None


# 표시할 배수. 전부 "몇 배"라 같은 로그 축을 쓴다. FCF수익률은 수익률(%)이라 축이
# 다르고, 0.0~1.0% 구간에 붙어 소수점 한 자리로는 네 행이 전부 같은 숫자로 보였다.
_VAL_HISTORY_ROWS = (
    ("PER", "pe"),
    ("PBR", "pb"),
    ("PSR", "ps"),
    ("EV/EBITDA", "ev_ebitda"),
)


def _log(value: float) -> float:
    """배수 축은 로그다 — 곱셈 척도이기도 하고, 이익이 0에 가까워지면 발산하기 때문.

    TSLA는 실제로 PER 5~95분위가 41~887배다(2020년 순이익이 0에 가까웠던 구간).
    선형 축에서는 관측치 대부분이 모인 30~120 구간이 트랙 왼쪽 10%에 눌려 안 보인다.
    """
    return math.log10(max(value, 1e-9))


def _spark(points: list, *, w: int = 210, h: int = 56, pad: int = 8,
           top: int = 17, bottom: int = 5) -> dict | None:
    """PER 스파크라인 좌표 + 중앙선/축 라벨 (history.downsample_weekly 결과를 받음).

    top은 축 라벨이 앉는 자리다 — 선이 거기까지 올라오면 글자와 겹친다.
    """
    vals = [v for _, v in points if v > 0]
    if len(vals) < 3:
        return None
    logs = [_log(v) for v in vals]
    lo, hi = min(logs), max(logs)
    rng = (hi - lo) or 1.0
    n = len(logs)
    plot_h = h - top - bottom
    xs = [pad + i * (w - 2 * pad) / (n - 1) for i in range(n)]
    ys = [(h - bottom) - (v - lo) / rng * plot_h for v in logs]
    # 극단치 한 점이 평균을 통째로 끌어올린다 — 기준선은 중앙값으로 긋는다.
    mid = _log(statistics.median(vals))
    return {
        "points": " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys)),
        "w": w, "h": h,
        "avg_y": round((h - bottom) - (mid - lo) / rng * plot_h, 1),
        "last_x": round(xs[-1], 1), "last_y": round(ys[-1], 1),
        "hi": _multiple(max(vals)), "lo": _multiple(min(vals)),
        "avg": _multiple(statistics.median(vals)),
    }


def _track_pos(value: float, lo: float, hi: float) -> float:
    """값 → 트랙 위치(%). 양끝 2~98%로 클램프해 마커가 트랙 밖으로 안 나가게."""
    span = (_log(hi) - _log(lo)) or 1.0
    return round(max(2.0, min(98.0, (_log(value) - _log(lo)) / span * 100)), 1)


def _multiple(value: float | None) -> str:
    """배수 표기 — 1000배가 넘으면 소수점을 버려야 칸에 들어간다."""
    if value is None:
        return "—"
    if value >= 1000:
        return f"{value:,.0f}x"
    if value >= 100:
        return f"{value:.0f}x"
    return f"{value:.1f}x"


def valuation_history(hist: dict | None) -> dict | None:
    """valuation_history.compute() 결과 → 역사 밸류에이션 표 행 + PER 스파크라인(색 기준 적용).

    트랙은 백분위 축이 아니라 값 축(5~95분위 범위)을 로그로 편 것이다. 25~75분위
    밴드·중앙값선·현재 마커를 값 위치로 찍어 "현재가 역사적 정상범위 안/밖"이 한눈에
    보이게 한다.
    """
    if not hist or not hist.get("stats"):
        return None
    rows = []
    for label, key in _VAL_HISTORY_ROWS:
        s = hist["stats"].get(key)
        if not s:
            continue
        prim = max(s)  # 가장 긴 가용 윈도
        st = s[prim]
        cur, med, pct = st["current"], st["median"], st["percentile"]
        lo, hi = st["lo"], st["hi"]
        if min(cur, med, lo, hi, st["q25"], st["q75"]) <= 0:
            continue  # 로그 축에 올릴 수 없는 값 — 표시하지 않는다
        band_l = _track_pos(st["q25"], lo, hi)
        rows.append({
            "label": label,
            "value": _multiple(cur),
            "median": _multiple(med),
            "lo_label": _multiple(lo),   # 트랙 좌측 끝 = 5분위(역사적 저점권) 실제 값
            "hi_label": _multiple(hi),   # 트랙 우측 끝 = 95분위(역사적 고점권) 실제 값
            "pct": pct,
            "color": palette.percentile_color(pct, key),
            "cur_pos": _track_pos(cur, lo, hi),
            "med_pos": _track_pos(med, lo, hi),
            "band_l": band_l,
            "band_w": round(_track_pos(st["q75"], lo, hi) - band_l, 1),
            # 기간별 "전형적" 밸류 = 중앙값(평균은 NVDA 급등기처럼 극단치에 휘둘려 왜곡됨).
            "windows": [
                {
                    "y": w,
                    "value": (_multiple(s[w]["median"]) if w in s else None),
                    "color": (palette.value_vs_avg_color(cur, s[w]["median"], key) if w in s else palette.MUTED),
                }
                for w in (1, 3, 5, 7)
            ],
            "prim_years": prim,
        })
    if not rows:
        return None
    return {"rows": rows, "spark": _spark(hist.get("pe_spark") or []),
            "span_years": round(hist.get("span_days", 0) / 365.25, 1)}


def quality(health: dict | None) -> list[dict] | None:
    """수익성·자본효율 스트립 — ROE·ROA·ROIC·이자보상배율(v_quality에 이미 계산됨)."""
    if not health:
        return None
    specs = [
        ("ROE", health.get("roe"), "%"),
        ("ROA", health.get("roa"), "%"),
        ("ROIC", health.get("roic"), "%"),
        ("이자보상배율", health.get("interest_coverage"), "x"),
    ]
    out = []
    for name, val, unit in specs:
        f = _num(val)
        if f is None:
            continue
        out.append({"name": name, "value": (f"{f * 100:.1f}%" if unit == "%" else f"{f:.1f}x")})
    return out or None


def _pct1(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def _ttm_sum(history: list[dict], key: str) -> float | None:
    """이력 마지막 4분기 합(TTM 근사). 4개 미만이면 None."""
    vals = [_num(r.get(key)) for r in history[-4:]]
    vals = [v for v in vals if v is not None]
    return sum(vals) if len(vals) == 4 else None


def income_waterfall(row: dict, prev: dict | None) -> dict | None:
    """손익 워터폴 — 매출 100% 기준 단계별 금액·이익률(+ 마진 전년 대비 변화)."""
    rev = _num(row.get("revenue"))
    if not rev:
        return None
    steps = []
    for label, key in (
        ("매출", "revenue"), ("매출총이익", "gross_profit"), ("영업이익", "operating_income_loss"),
        ("세전이익", "pretax_income_loss"), ("순이익", "net_income"),
    ):
        v = _num(row.get(key))
        if v is None:
            continue
        p = _num(prev.get(key)) if prev else None
        yoy = (v - p) / abs(p) if p not in (None, 0) else None
        steps.append({
            "label": label,
            "money": fmt.money(v),
            "pct": None if key == "revenue" else f"{v / rev * 100:.1f}%",
            "yoy": _signed_pct(yoy),
            "yoy_color": palette.direction(yoy),  # 손익 라인은 증가=개선(초록)
            "width": max(0.0, min(100.0, abs(v / rev) * 100)),
        })
    delta = None
    if prev:
        p_rev = _num(prev.get("revenue"))
        parts = []
        for nm, key in (("매출총", "gross_profit"), ("영업", "operating_income_loss"), ("순", "net_income")):
            cur = _div(_num(row.get(key)), rev)
            pp = _div(_num(prev.get(key)), p_rev)
            if cur is not None and pp is not None:
                d = (cur - pp) * 100
                parts.append(f"{nm} {'+' if d >= 0 else ''}{d:.1f}%p")
        delta = " · ".join(parts) or None
    return {"steps": steps, "margin_delta": delta}


def combo(
    history: list[dict],
    quality_history: list[dict],
    consensus_revenue: dict | None = None,
    next_quarter: dict | None = None,
) -> dict | None:
    """최근 13분기 손익 막대와 부채·유동비율 선 차트 좌표.

    consensus_revenue가 있으면 마지막 분기 매출 막대 위에 **기대치 눈금**과
    low~high 수염을 얹고, next_quarter가 있으면 그 뒤에 **다음 분기 예상 매출**을
    빈 막대로 덧붙인다. 예상은 실적이 아니므로 채우지 않고 테두리만 그린다.
    """
    qs = [r for r in history if _num(r.get("revenue")) is not None][-13:]
    if len(qs) < 3:
        return None

    # 판 폭에 비례해 높이가 정해지므로(width:100%) 종횡비가 곧 카드 높이다.
    fin_w, ratio_w, h = 720, 480, 150
    top, base = 18, 122
    fin_lm, fin_rm = 42, 8
    ratio_lm, ratio_rm = 12, 66
    plot_h = base - top
    n = len(qs)

    financial_values = [
        value
        for r in qs
        for value in (
            _num(r.get("revenue")),
            _num(r.get("operating_income_loss")),
            _num(r.get("net_income")),
        )
        if value is not None
    ]
    # 기대치 수염이 축 밖으로 잘리면 '기대보다 훨씬 위/아래'가 안 보인다.
    if consensus_revenue:
        financial_values += [
            value
            for value in (
                _num(consensus_revenue.get("estimate")),
                _num(consensus_revenue.get("low")),
                _num(consensus_revenue.get("high")),
            )
            if value is not None
        ]
    forward_revenue = _num((next_quarter or {}).get("revenue"))
    if forward_revenue is not None:
        financial_values.append(forward_revenue)
    fin_lo, fin_hi, fin_ticks = _nice_axis(financial_values)

    def fin_y(value: float) -> float:
        return top + (fin_hi - value) / (fin_hi - fin_lo) * plot_h

    fin_zero = fin_y(0.0)
    # 다음 분기 예상 매출은 마지막 실적 뒤 한 칸을 더 쓴다.
    slots = n + (1 if forward_revenue is not None else 0)
    fin_span = (fin_w - fin_lm - fin_rm) / slots
    de_by_pe = {str(r["period_end"]): _num(r.get("debt_to_equity")) for r in quality_history}
    cr_by_pe = {str(r["period_end"]): _num(r.get("current_ratio")) for r in quality_history}

    bars = []
    for i, r in enumerate(qs):
        xi = fin_lm + (i + 0.5) * fin_span

        def bar(key: str, dx: float) -> dict:
            value = _num(r.get(key))
            if value is None:
                return {"x": round(xi + dx, 1), "y": round(fin_zero, 1), "h": 0}
            y = fin_y(value)
            return {
                "x": round(xi + dx, 1),
                "y": round(min(y, fin_zero), 1),
                "h": round(abs(y - fin_zero), 1),
            }

        bars.append({
            "rev": bar("revenue", -10),
            "op": bar("operating_income_loss", -2),
            "net": bar("net_income", 6),
            "label": _q_label(r), "lx": round(xi, 1),
            # 13개를 다 찍으면 글자가 겹친다 — 세 분기마다와 마지막만 남긴다.
            "show": i % 3 == 0 or i == n - 1,
            "hi": i == n - 1,  # 이번(가장 최근) 분기 라벨 강조
        })

    fin_grid = [
        {"y": round(fin_y(tick), 1), "label": _axis_money(tick)}
        for tick in reversed(fin_ticks)
    ]

    # 기대치 오버레이 — 마지막 분기 매출 막대([xi-10, xi-3]) 위에만 얹는다.
    estimate_mark = None
    if consensus_revenue:
        estimate = _num(consensus_revenue.get("estimate"))
        if estimate is not None:
            last_xi = fin_lm + (n - 0.5) * fin_span  # 마지막 실적 분기
            low, high = _num(consensus_revenue.get("low")), _num(consensus_revenue.get("high"))
            actual = _num(qs[-1].get("revenue"))
            estimate_mark = {
                "x1": round(last_xi - 13, 1), "x2": round(last_xi, 1),
                "y": round(fin_y(estimate), 1),
                "cx": round(last_xi - 6.5, 1),
                "y_low": round(fin_y(low), 1) if low is not None else None,
                "y_high": round(fin_y(high), 1) if high is not None else None,
                "beat": actual is not None and actual >= estimate,
                "label": _axis_money(estimate),
            }

    # 다음 분기 예상 매출 — 실적이 아니므로 채우지 않고 테두리만 그린다.
    forward_bar = None
    if forward_revenue is not None:
        xi = fin_lm + (n + 0.5) * fin_span
        y = fin_y(forward_revenue)
        forward_bar = {
            "x": round(xi - 10, 1), "w": 7,
            "y": round(min(y, fin_zero), 1),
            "h": round(abs(y - fin_zero), 1),
            "lx": round(xi, 1),
            "label": (next_quarter or {}).get("label") or "다음 분기 예상",
            "label_money": _axis_money(forward_revenue),
        }

    ratio_rows = []
    ratio_values = []
    for r in qs:
        pe = str(r.get("period_end"))
        de, cr = de_by_pe.get(pe), cr_by_pe.get(pe)
        ratio_rows.append((r, de, cr))
        ratio_values.extend(v for v in (de, cr) if v is not None)
    ratio_lo, ratio_hi, ratio_ticks = _nice_axis(ratio_values)

    def ratio_y(value: float) -> float:
        return top + (ratio_hi - value) / (ratio_hi - ratio_lo) * plot_h

    ratio_span = (ratio_w - ratio_lm - ratio_rm) / max(1, n - 1)
    de_pts, cr_pts, de_dots, cr_dots, ratio_labels = [], [], [], [], []
    for i, (r, de, cr) in enumerate(ratio_rows):
        x = ratio_lm + i * ratio_span
        if de is not None:
            y = ratio_y(de)
            de_pts.append(f"{x:.1f},{y:.1f}")
            de_dots.append({"x": round(x, 1), "y": round(y, 1)})
        if cr is not None:
            y = ratio_y(cr)
            cr_pts.append(f"{x:.1f},{y:.1f}")
            cr_dots.append({"x": round(x, 1), "y": round(y, 1)})
        if i in {0, n - 1} or i % 3 == 0:
            ratio_labels.append({"x": round(x, 1), "label": _q_label(r)})

    ratio_grid = [
        {"y": round(ratio_y(tick), 1), "label": f"{tick:.1f}x"}
        for tick in reversed(ratio_ticks)
    ]
    return {
        "financials": {
            "w": fin_w, "h": h, "bars": bars, "grid": fin_grid,
            "zero_y": round(fin_zero, 1), "estimate": estimate_mark, "forward": forward_bar,
            # 예상이 없어도 마지막 막대가 얼마인지는 말한다.
            "last_revenue": fmt.money(_num(qs[-1].get("revenue"))),
        },
        "ratios": {
            "w": ratio_w, "h": h, "grid": ratio_grid, "labels": ratio_labels,
            "de_points": " ".join(de_pts), "cr_points": " ".join(cr_pts),
            "de_dots": de_dots, "cr_dots": cr_dots,
        },
    }


def _match_quarter(period_end: str, points: list[dict], *, tolerance: int = 25) -> dict | None:
    """분기말이 tolerance 안에서 가장 가까운 컨센서스 점. 회계·캘린더 분기말이 어긋난다."""
    target = _as_date(period_end)
    if target is None:
        return None
    best: tuple[int, dict] | None = None
    for point in points:
        when = _as_date(point.get("quarter_end"))
        if when is None:
            continue
        gap = abs((when - target).days)
        if gap <= tolerance and (best is None or gap < best[0]):
            best = (gap, point)
    return best[1] if best else None


def eps_trend(
    history: list[dict],
    consensus: dict | None = None,
    *,
    w: int = 400,
    h: int = 124,
) -> dict | None:
    """최근 13분기 EPS 추이 — GAAP 실선에 **예상 점선**과 조정 실제 점을 겹친다.

    순이익률은 여기서 뺐다. 이 블록의 질문이 "EPS가 기대와 얼마나 달랐나"로 좁혀지면서
    다른 단위(%)의 두 번째 축이 자리만 차지하게 됐다 — 마진은 `손익 구조`가 이미 낸다.

    예상은 과거 분기까지 점선으로 잇는다(`earnings_estimates`가 회계기간별 기준 예상을 준다).
    그래서 별도의 '서프라이즈 추이' 그림이 필요 없다 — 예상 점선과 실제 점 사이의
    벌어진 간격이 곧 서프라이즈다.

    파란 선은 GAAP(순이익÷희석주식수), 점·점선은 조정 기준이라 서로 다른 값이다.
    같은 축에 **그리는** 건 단위가 같아 문제가 없다 — 하면 안 되는 건 둘을 **빼서**
    서프라이즈를 만드는 것이고, 서프라이즈는 점끼리(예상↔조정 실제)만 계산한다.
    """
    qs = [r for r in history if _eps_diluted(r) is not None][-13:]
    if len(qs) < 2:
        return None
    top, bot, side = 16, 24, 46
    plot_h, n = h - top - bot, len(qs)
    eps = [_eps_diluted(r) for r in qs]

    points = (consensus or {}).get("history") or []
    forward = (consensus or {}).get("next_quarter")
    forward_value = _num((forward or {}).get("estimate"))
    # 예상 점이 축 밖으로 잘리면 '기대보다 훨씬 위/아래'가 안 보인다.
    overlay = [
        value
        for point in points
        for value in (_num(point.get("actual")), _num(point.get("estimate")))
        if value is not None
    ]
    if forward_value is not None:
        overlay.append(forward_value)
    elo, ehi = min(eps + overlay), max(eps + overlay)
    er = (ehi - elo) or 1.0

    # 다음 분기 예상은 마지막 실적 뒤 한 칸을 더 쓴다.
    slots = n + (1 if forward_value is not None else 0)

    def xat(i):
        return side + i * (w - 2 * side) / max(1, slots - 1)

    def eps_y(value: float) -> float:
        return top + (ehi - value) / er * plot_h

    eps_pts = " ".join(f"{xat(i):.1f},{eps_y(v):.1f}" for i, v in enumerate(eps))

    actual_dots, estimate_dots = [], []
    estimate_path: list[str] = []
    for i, row in enumerate(qs):
        point = _match_quarter(str(row.get("period_end") or ""), points)
        if not point:
            continue
        actual, estimate = _num(point.get("actual")), _num(point.get("estimate"))
        if actual is not None:
            actual_dots.append({"x": round(xat(i), 1), "y": round(eps_y(actual), 1)})
        if estimate is not None:
            estimate_dots.append({"x": round(xat(i), 1), "y": round(eps_y(estimate), 1)})
            estimate_path.append(f"{xat(i):.1f},{eps_y(estimate):.1f}")

    forward_dot = None
    if forward_value is not None:
        forward_dot = {
            "x": round(xat(slots - 1), 1),
            "y": round(eps_y(forward_value), 1),
            "prev_x": round(xat(n - 1), 1),
            "prev_y": round(eps_y(eps[-1]), 1),
            "label": f"{forward_value:.2f}",
            "quarter": (forward or {}).get("label"),
        }
        # 예상 점선은 다음 분기까지 이어진다 — 과거 예상과 앞으로의 예상이 한 줄이다.
        estimate_path.append(f"{xat(slots - 1):.1f},{eps_y(forward_value):.1f}")
    # 축이 하나(달러)뿐이라 오른쪽 라벨이 없다.
    grid = [
        {"y": top, "left": f"{ehi:.2f}"},
        {"y": top + plot_h / 2, "left": f"{(ehi + elo) / 2:.2f}"},
        {"y": top + plot_h, "left": f"{elo:.2f}"},
    ]
    # 아래 숫자 줄은 **이번 분기** 쌍이어야 한다. points의 마지막을 그냥 집으면
    # financial_versions가 아직 이번 분기의 조정 EPS를 못 받았을 때 직전 분기 값이 올라와,
    # 헤더의 기간말과 다른 분기를 말하게 된다.
    latest = _match_quarter(str(qs[-1].get("period_end") or ""), points)
    surprise = (
        _signed_pct(latest["surprise"])
        if latest and latest.get("reliable") and latest.get("surprise") is not None
        else None
    )
    return {
        "w": w, "h": h, "eps_points": eps_pts, "grid": grid,
        "last_x": round(xat(n - 1), 1), "last_y": round(eps_y(eps[-1]), 1),
        "last_eps": f"{eps[-1]:.2f}",
        "first_q": _q_label(qs[0]), "last_q": _q_label(qs[-1]),
        "actual_dots": actual_dots, "estimate_dots": estimate_dots, "forward": forward_dot,
        "estimate_points": " ".join(estimate_path),
        "actual_label": f"{latest['actual']:.2f}" if latest and latest.get("actual") else None,
        "estimate_label": f"{latest['estimate']:.2f}" if latest and latest.get("estimate") else None,
        "surprise": surprise,
        "surprise_color": (
            palette.direction(latest["surprise"]) if surprise else palette.MUTED
        ),
    }


def cashflow_quarters(history: list[dict], *, w: int = 440, h: int = 150) -> dict | None:
    """최근 13분기 영업·투자·재무 현금흐름 선 차트.

    연 단위로 그리면 점이 다섯 개뿐이라 계절성도, 이번 분기가 흐름의 어디인지도 안 보인다.
    financial_versions의 분기 현금흐름은 누적(YTD)이 아니라 분기별 실제값이라 그대로 이을 수 있다.
    """
    rows = [
        r for r in history
        if any(_num(r.get(key)) is not None for key in (
            "net_cash_from_operating_activities",
            "net_cash_from_investing_activities",
            "net_cash_from_financing_activities",
        ))
    ][-13:]
    if len(rows) < 2:
        return None

    top, base, left, right = 18, 122, 42, 18
    plot_h = base - top
    specs = (
        ("operating", "net_cash_from_operating_activities"),
        ("investing", "net_cash_from_investing_activities"),
        ("financing", "net_cash_from_financing_activities"),
    )
    values = [
        value
        for row in rows
        for _, key in specs
        if (value := _num(row.get(key))) is not None
    ]
    lo, hi, ticks = _nice_axis(values)

    def yat(value: float) -> float:
        return top + (hi - value) / (hi - lo) * plot_h

    def xat(index: int) -> float:
        return left + index * (w - left - right) / max(1, len(rows) - 1)

    series = {}
    for name, key in specs:
        points, dots = [], []
        for i, row in enumerate(rows):
            value = _num(row.get(key))
            if value is None:
                continue
            x, y = xat(i), yat(value)
            points.append(f"{x:.1f},{y:.1f}")
            dots.append({"x": round(x, 1), "y": round(y, 1)})
        series[name] = {"points": " ".join(points), "dots": dots}

    return {
        "w": w,
        "h": h,
        "zero_y": round(yat(0.0), 1),
        "grid": [
            {"y": round(yat(tick), 1), "label": _axis_money(tick)}
            for tick in reversed(ticks)
        ],
        "labels": [
            {
                "x": round(xat(i), 1),
                "label": _q_label(row),
                "anchor": "start" if i == 0 else "end" if i == len(rows) - 1 else "middle",
            }
            # 분기가 13개면 라벨이 겹친다 — 양끝과 3분기마다만 찍는다.
            for i, row in enumerate(rows)
            if i in {0, len(rows) - 1} or i % 3 == 0
        ],
        **series,
    }


def _bridge_parts(row: dict | None) -> dict[str, float] | None:
    """브릿지 한 기간분 — 순이익에서 FCF까지의 단계값."""
    if not row:
        return None
    ni = _num(row.get("net_income"))
    ocf = _num(row.get("net_cash_from_operating_activities"))
    if ni is None or ocf is None:
        return None
    da = _num(row.get("depreciation_amortization_cf")) or 0.0
    sbc = _num(row.get("stock_based_compensation_cf")) or 0.0
    capex = _num(row.get("capital_expenses")) or 0.0
    return {
        "순이익": ni,
        "+감가상각": da,
        "+주식보상": sbc,
        # 잔차 = 운전자본/기타 (브릿지가 항상 OCF로 맞아떨어지게)
        "±운전자본/기타": ocf - ni - da - sbc,
        "영업현금흐름": ocf,
        "−CAPEX": -capex,
        "잉여현금흐름": ocf - capex,
    }


_BRIDGE_KINDS = {
    "순이익": "total", "영업현금흐름": "subtotal", "잉여현금흐름": "total", "−CAPEX": "sub",
}


def cashflow_bridge(row: dict, prev: dict | None = None) -> dict | None:
    """현금흐름 브릿지 — 순이익 → (+감가·주식보상 ±운전자본) → OCF → −CAPEX → FCF.

    금액과 YoY만 낸다. 매출 대비(현금전환율)는 브릿지 각 단계에 붙이면 감가상각 3.0%,
    주식보상 3.1%처럼 판단에 안 쓰이는 숫자가 대부분이라 뺐다 — 정작 볼 값인 OCF·FCF의
    매출 대비는 이익의 질(TTM)이 이미 갖고 있다.

    부호가 뒤집힌 항목은 YoY를 내지 않는다. 운전자본은 해마다 유입·유출이 바뀌는데
    −$2B에서 +$1B로 간 것을 "−150%"라고 적으면 없는 방향을 지어내는 것이다.
    """
    parts = _bridge_parts(row)
    if parts is None:
        return None
    before = _bridge_parts(prev)
    scale = max(abs(parts["순이익"]), abs(parts["영업현금흐름"]), 1.0)

    steps = []
    for label, value in parts.items():
        was = (before or {}).get(label)
        same_sign = was is not None and (value >= 0) == (was >= 0)
        yoy = (value - was) / abs(was) if same_sign and was else None
        steps.append({
            "label": label,
            "money": fmt.money(value),
            "yoy": _signed_pct(yoy),
            "yoy_color": palette.direction(yoy),   # 현금 라인은 증가 = 개선(초록)
            "width": max(0.0, min(100.0, abs(value) / scale * 100)),
            "kind": _BRIDGE_KINDS.get(label, "add" if value >= 0 else "sub"),
        })
    return {"steps": steps}


def earnings_quality(eq: dict | None) -> list[dict] | None:
    """이익의 질(TTM) — OCF/순이익·FCF/순이익·발생액.

    FCF마진은 브릿지 표의 '잉여현금흐름 · 매출 대비'와 같은 값이라 여기서 뺐다.
    """
    if not eq:
        return None
    ocf, ni = _num(eq.get("operating_cash_flow_ttm")), _num(eq.get("net_income_ttm"))
    fcf = _num(eq.get("free_cash_flow_ttm"))
    rows = [
        ("OCF/순이익", (ocf / ni if ocf is not None and ni else None)),
        ("FCF/순이익", (fcf / ni if fcf is not None and ni else None)),
        ("발생액", _num(eq.get("accruals_ttm"))),
    ]
    out = [{"name": nm, "value": _pct1(v)} for nm, v in rows if v is not None]
    return out or None


def working_capital(row: dict, history: list[dict]) -> list[dict] | None:
    """운전자본 — 회전일수는 전년 동기와 현재 잔액의 평균으로 계산한다."""
    ttm_rev = _ttm_sum(history, "revenue")
    ttm_cogs = _ttm_sum(history, "cost_of_goods_and_services_sold")
    ar = _num(row.get("trade_receivables"))
    inv = _num(row.get("inventories"))
    ap = _num(row.get("trade_payables"))
    if not ttm_rev:
        return None
    prior = next((
        r for r in reversed(history)
        if r is not row
        and r.get("fiscal_period") == row.get("fiscal_period")
        and r.get("fiscal_year") == row.get("fiscal_year", 0) - 1
    ), None)

    def avg_balance(current: float | None, key: str) -> float | None:
        previous = _num(prior.get(key)) if prior else None
        if current is None:
            return None
        return (current + previous) / 2 if previous is not None else current

    avg_ar = avg_balance(ar, "trade_receivables")
    avg_inv = avg_balance(inv, "inventories")
    avg_ap = avg_balance(ap, "trade_payables")
    dso = avg_ar / ttm_rev * 365 if avg_ar is not None else None
    dio = avg_inv / ttm_cogs * 365 if (avg_inv is not None and ttm_cogs) else None
    dpo = avg_ap / ttm_cogs * 365 if (avg_ap is not None and ttm_cogs) else None
    ccc = (dso + dio - dpo) if None not in (dso, dio, dpo) else None
    rows = [
        ("CCC", f"{ccc:.0f}일" if ccc is not None else None),
        ("DSO", f"{dso:.0f}일" if dso is not None else None),
        ("DIO", f"{dio:.0f}일" if dio is not None else None),
        ("DPO", f"{dpo:.0f}일" if dpo is not None else None),
    ]
    out = [{"name": nm, "value": v} for nm, v in rows if v is not None]
    return out or None


def shareholder_return(prices: list[dict], shares: list[tuple[str, float]]) -> list[dict] | None:
    """주주환원 — 배당수익률·TTM 배당(market.div_amount)·주식수 YoY."""
    if not prices:
        return None
    last = prices[-1]
    price = _num(last.get("close"))
    cut = (date.fromisoformat(str(last["trade_date"])) - timedelta(days=365)).isoformat()
    ttm_div = sum(_num(r.get("div_amount")) or 0.0 for r in prices if str(r["trade_date"]) >= cut)
    if ttm_div <= 0:
        return None
    rows = [
        ("배당수익률", f"{(ttm_div / price) * 100:.2f}%" if (price and ttm_div) else None),
        ("TTM 배당", f"${ttm_div:.2f}" if ttm_div else None),
    ]
    if len(shares) >= 2:
        latest = shares[-1][1]
        cutd = (date.fromisoformat(shares[-1][0]) - timedelta(days=365)).isoformat()
        prior = next((s for d, s in reversed(shares) if d <= cutd), None)
        if prior:
            rows.append(("주식수 YoY", f"{(latest / prior - 1) * 100:+.1f}%"))
    return [{"name": nm, "value": v} for nm, v in rows if v is not None]


def technicals(tech: dict | None, prices: list[dict]) -> list[dict] | None:
    """주가·기술 — 저장된 가격·기술 입력으로 52주 위치·추세·변동성을 만든다."""
    if not tech:
        return None
    close = _num(tech.get("close"))
    hi, sma200 = _num(tech.get("high_52w")), _num(tech.get("sma_200"))
    vol = _num(tech.get("hist_vol_20_ann"))
    trend_map = {"bullish": "골든크로스", "bearish": "데드크로스", "neutral": "중립"}
    rows = [
        ("52주 위치", _pct1(close / hi - 1) if (close and hi) else None),
        ("vs 200일선", _pct1(close / sma200 - 1) if (close and sma200) else None),
        ("추세", trend_map.get(tech.get("ma_trend_50_200"))),
        ("변동성(연)", f"{vol * 100:.0f}%" if vol is not None else None),
    ]
    if prices and close:
        cut = (date.fromisoformat(str(prices[-1]["trade_date"])) - timedelta(days=365)).isoformat()
        base = next((_num(r.get("close")) for r in prices if str(r["trade_date"]) >= cut), None)
        if base:
            rows.append(("1년 수익률", _pct1(close / base - 1)))
    out = [{"name": nm, "value": v} for nm, v in rows if v is not None]
    return out or None


def prices_before_filing(prices: list[dict], filed_at: str | None) -> list[dict]:
    """공시 당일 반응까지 배제한 직전 거래일 이하 가격을 오름차순으로 반환한다."""
    if not prices or not filed_at:
        return []
    return sorted(
        (
            row for row in prices
            if str(row.get("trade_date") or "") < str(filed_at)
            and _num(row.get("close")) is not None
        ),
        key=lambda row: str(row["trade_date"]),
    )


def technical_snapshot(prices: list[dict]) -> dict | None:
    """공시 전 가격만으로 52주 위치·이동평균·20일 변동성을 계산한다."""
    closes = [_num(row.get("close")) for row in prices]
    closes = [value for value in closes if value is not None]
    if not closes:
        return None
    year = closes[-252:]
    sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
    sma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
    returns = [
        math.log(current / previous)
        for previous, current in zip(closes[-21:-1], closes[-20:])
        if previous > 0 and current > 0
    ]
    volatility = None
    if len(returns) >= 2:
        mean = sum(returns) / len(returns)
        variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
        volatility = math.sqrt(variance) * math.sqrt(252)
    trend = None
    if sma50 is not None and sma200 is not None:
        trend = "bullish" if sma50 >= sma200 else "bearish"
    return {
        "trade_date": str(prices[-1]["trade_date"]),
        "close": closes[-1],
        "sma_50": sma50,
        "sma_200": sma200,
        "high_52w": max(year),
        "low_52w": min(year),
        "ma_trend_50_200": trend,
        "hist_vol_20_ann": volatility,
    }


def _price(v: float | None) -> str:
    return "—" if v is None else f"${v:,.2f}"


def week52_range(tech: dict | None, price_target: dict | None = None) -> dict | None:
    """가격 트랙 — 실제로 거래된 52주 구간과 애널리스트 목표를 한 축에 얹는다.

    price_target이 있으면 축을 둘의 합집합으로 넓힌다. 목표는 보통 52주 고가 밖에
    있어서(관측: NVDA 52주 165~236 대 목표 180~500), 52주 축에 그대로 그리면 끝에
    붙어 눌린다 — '어디까지 갔었나'와 '어디로 본다'가 같은 자에서 읽혀야 한다.
    """
    if not tech:
        return None
    lo, hi, close = _num(tech.get("low_52w")), _num(tech.get("high_52w")), _num(tech.get("close"))
    if lo is None or hi is None or close is None or hi <= lo:
        return None
    sma200 = _num(tech.get("sma_200"))

    t_low = _num((price_target or {}).get("low"))
    t_high = _num((price_target or {}).get("high"))
    t_mean = _num((price_target or {}).get("mean"))
    bounds = [lo, hi, close] + [v for v in (t_low, t_high, t_mean) if v is not None]
    axis_lo, axis_hi = min(bounds), max(bounds)
    span = (axis_hi - axis_lo) or 1.0

    def pos(value: float) -> float:
        return round(_clamp_pct((value - axis_lo) / span * 100), 1)

    target = None
    if t_mean is not None:
        target = {
            "mean_pos": pos(t_mean),
            "mean_label": _price(t_mean),
            "low_pos": pos(t_low) if t_low is not None else None,
            "high_pos": pos(t_high) if t_high is not None else None,
            "range_label": (
                f"{_price(t_low)} – {_price(t_high)}"
                if t_low is not None and t_high is not None else None
            ),
            "upside": _signed_pct((price_target or {}).get("upside")),
            "above": t_mean >= close,
        }
    return {
        "lo_label": _price(lo),
        "hi_label": _price(hi),
        "close_label": _price(close),
        # 52주 구간이 축 전체를 안 채울 수 있으므로 시작점과 폭을 함께 낸다.
        "band_left": pos(lo),
        "band_width": round(pos(hi) - pos(lo), 1),
        "close_pos": pos(close),
        "sma200_pos": pos(sma200) if sma200 is not None else None,
        "axis_lo_label": _price(axis_lo),
        "axis_hi_label": _price(axis_hi),
        "from_high": _pct1(close / hi - 1) if hi else "—",
        "target": target,
    }


def dividend_trend(prices: list[dict]) -> dict | None:
    """월별(배당 발생월) 주당배당 막대 + 시가배당수익률 꺾은선 듀얼 차트."""
    if not prices:
        return None

    div_events: list[dict] = []
    for r in prices:
        d = _num(r.get("div_amount"))
        if d is not None and d > 0:
            div_events.append({
                "trade_date": str(r["trade_date"]),
                "div_amount": d,
                "close": _num(r.get("close")),
            })

    if not div_events:
        return None

    # 최근 12개월 지급 월 → 연간 지급 횟수 (분기배당=4, 월배당=12)
    last_td = div_events[-1]["trade_date"]
    cut = (date.fromisoformat(last_td) - timedelta(days=363)).isoformat()
    recent_months = sorted({int(p["trade_date"][5:7]) for p in div_events if p["trade_date"] >= cut})
    freq = len(recent_months) or 4
    months_label = "·".join(f"{m}월" for m in recent_months) if recent_months else None

    # 최근 최대 20회 배당 이벤트 선택 (분기배당 기준 최대 5개년)
    events = div_events[-20:]
    for e in events:
        close = e["close"]
        e["yield_pct"] = (e["div_amount"] * freq / close * 100) if close and close > 0 else None
        td = e["trade_date"]
        e["label"] = f"'{td[2:4]}.{td[5:7]}"

    # SVG geometry
    w = 340
    h = 88
    pad_l = 26
    pad_r = 26
    pad_t = 14
    pad_b = 20
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    baseline_y = h - pad_b

    div_vals = [e["div_amount"] for e in events]
    min_div = min(div_vals)
    max_div = max(div_vals)
    span_div = max_div - min_div

    yield_vals = [e["yield_pct"] for e in events if e.get("yield_pct") is not None]
    if yield_vals:
        min_y = min(yield_vals)
        max_y = max(yield_vals)
        span_y = max_y - min_y
    else:
        min_y, max_y, span_y = 0.0, 1.0, 1.0

    n = len(events)
    step = plot_w / n
    bars = []
    line_pts = []
    dots = []

    # X축 라벨 희소화: 전체가 8개 이하이면 전부 표시, 초과이면 4분기(1년)마다 및 양끝만 표시
    for i, e in enumerate(events):
        cx = pad_l + (i + 0.5) * step
        bw = min(14.0, max(6.0, step * 0.56))

        if span_div > 0:
            bh = round(14.0 + ((e["div_amount"] - min_div) / span_div) * 34.0, 1)
        else:
            bh = 30.0

        by = round(baseline_y - bh, 1)
        bx = round(cx - bw / 2, 1)
        is_latest = (i == n - 1)
        show_label = (n <= 8 or i == 0 or is_latest or (n - 1 - i) % 4 == 0)

        bars.append({
            "x": bx,
            "y": by,
            "w": bw,
            "h": bh,
            "value": f"${e['div_amount']:.2f}",
            "label": e["label"],
            "cx": round(cx, 1),
            "hi": is_latest,
            "show_label": show_label,
        })

        if e.get("yield_pct") is not None:
            if span_y > 0:
                ly = round(baseline_y - 8.0 - ((e["yield_pct"] - min_y) / span_y) * (plot_h - 16.0), 1)
            else:
                ly = round(baseline_y - plot_h / 2.0, 1)

            line_pts.append(f"{cx:.1f},{ly:.1f}")
            dots.append({
                "cx": round(cx, 1),
                "cy": ly,
                "yield_str": f"{e['yield_pct']:.2f}%",
                "hi": is_latest,
            })

    cagr = None
    if len(events) >= 4 and events[0]["div_amount"] > 0:
        d1 = date.fromisoformat(events[0]["trade_date"])
        d2 = date.fromisoformat(events[-1]["trade_date"])
        span_years = (d2 - d1).days / 365.25
        if span_years >= 0.8:
            cagr = (events[-1]["div_amount"] / events[0]["div_amount"]) ** (1.0 / span_years) - 1.0

    return {
        "svg": {
            "w": w,
            "h": h,
            "bars": bars,
            "line_points": " ".join(line_pts),
            "dots": dots,
            "baseline_y": baseline_y,
            "div_top_label": f"${max_div:.2f}",
            "div_min_label": f"${min_div:.2f}" if span_div > 0 else None,
            "yield_top_label": f"{max_y:.1f}%" if yield_vals else None,
        },
        "freq": (freq or None),
        "months": months_label,
        "cagr": (_pct1(cagr) if cagr is not None else None),
        "latest_dps": f"${events[-1]['div_amount']:.2f}",
        "latest_yield": f"{events[-1]['yield_pct']:.2f}%" if events[-1].get("yield_pct") else None,
    }
