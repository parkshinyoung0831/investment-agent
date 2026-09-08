"""8-K 실적 속보 및 가이던스 QuickChart 이미지 URL 생성기."""
from __future__ import annotations

from typing import Any

from investment_agent.notifications.quickchart import build_quickchart_url

COLOR_BEAT = "#00C087"
COLOR_MISS = "#FF3B30"
COLOR_INLINE = "#3182F6"
COLOR_BG = "#0b0e14"


def format_money_short(val: float | None) -> str:
    if val is None:
        return "—"
    if abs(val) >= 1e9:
        return f"${val / 1e9:.1f}B"
    if abs(val) >= 1e6:
        return f"${val / 1e6:.1f}M"
    return f"${val:,.0f}"


def format_eps_short(val: float | None) -> str:
    if val is None:
        return "—"
    return f"${val:.2f}"


def flash_performance_chart_url(
    flash: dict[str, Any],
    *,
    width: int = 520,
    height: int = 210,
) -> str | None:
    """실제 실적 vs 시장 예상치 달성률(%) 가로 막대 차트 URL을 생성한다."""
    eps_act = flash.get("eps_actual")
    eps_est = flash.get("eps_estimate")
    rev_act = flash.get("revenue_actual")
    rev_est = flash.get("revenue_estimate")

    labels: list[str] = []
    achieved_rates: list[float] = []
    bar_colors: list[str] = []

    # 1. EPS 달성률
    if eps_act is not None and eps_est is not None and eps_est != 0:
        rate = round((eps_act / abs(eps_est)) * 100.0, 1)
        label_text = f"EPS ({format_eps_short(eps_act)} / 예상 {format_eps_short(eps_est)})"
        labels.append(label_text)
        achieved_rates.append(rate)
        bar_colors.append(COLOR_BEAT if rate >= 100.0 else COLOR_MISS)

    # 2. 매출 달성률
    if rev_act is not None and rev_est is not None and rev_est > 0:
        rate = round((rev_act / rev_est) * 100.0, 1)
        label_text = f"매출 ({format_money_short(rev_act)} / 예상 {format_money_short(rev_est)})"
        labels.append(label_text)
        achieved_rates.append(rate)
        bar_colors.append(COLOR_BEAT if rate >= 100.0 else COLOR_MISS)

    if not achieved_rates:
        return None

    ticker = flash.get("ticker") or ""
    fy = flash.get("fiscal_year") or ""
    fp = flash.get("fiscal_period") or ""
    title_text = f"⚡ {ticker} · FY{fy} {fp} 시장 컨센서스 대비 달성률 (%)"

    min_val = min(min(achieved_rates) - 5, 85)
    max_val = max(max(achieved_rates) + 5, 115)

    chart = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "시장 예상 기준 (100%)",
                    "data": [100.0] * len(labels),
                    "backgroundColor": "rgba(107, 114, 128, 0.35)",
                    "borderColor": "#9CA3AF",
                    "borderWidth": 1,
                    "borderRadius": 5,
                },
                {
                    "label": "실제 달성률 (%)",
                    "data": achieved_rates,
                    "backgroundColor": bar_colors,
                    "borderRadius": 5,
                },
            ],
        },
        "options": {
            "indexAxis": "y",
            "responsive": True,
            "layout": {"padding": {"top": 8, "bottom": 8, "left": 10, "right": 14}},
            "plugins": {
                "legend": {
                    "position": "top",
                    "labels": {
                        "color": "#F3F4F6",
                        "font": {"size": 11, "weight": "bold"},
                        "boxWidth": 12,
                    },
                },
                "title": {
                    "display": True,
                    "text": title_text,
                    "color": "#F9FAFB",
                    "font": {"size": 13, "weight": "bold"},
                    "padding": {"bottom": 8},
                },
            },
            "scales": {
                "x": {
                    "min": round(min_val, 0),
                    "max": round(max_val, 0),
                    "grid": {"color": "rgba(75, 85, 99, 0.25)"},
                    "ticks": {"color": "#9CA3AF", "font": {"size": 10}},
                },
                "y": {
                    "grid": {"display": False},
                    "ticks": {
                        "color": "#F3F4F6",
                        "font": {"size": 11, "weight": "bold"},
                    },
                },
            },
        },
    }

    return build_quickchart_url(chart, width=width, height=height, background=COLOR_BG)
