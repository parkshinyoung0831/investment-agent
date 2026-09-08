"""경제발표 결과를 survey/nowcast/own_model과 혼동 없이 Discord에 표시한다."""
from __future__ import annotations

from datetime import date
from typing import Any

from investment_agent.notifications.renderers.text import table

_ACCENT = int("4B5563", 16)
_CATEGORY = {
    "inflation": ("📊", "물가"),
    "labor": ("👷", "고용"),
    "growth_consumption": ("🏭", "성장·소비"),
    "policy_housing": ("🏦", "정책·주택"),
    "liquidity_trade_energy": ("💧", "유동성·무역·에너지"),
}


def _number(value: Any, unit: str | None) -> str:
    if value is None:
        return "—"
    number = float(value)
    if unit in {"percent", "percent_annualized", "rate"}:
        return f"{number:.2f}%"
    if unit == "pmi":
        return f"{number:.1f}"
    if abs(number) >= 1_000:
        return f"{number:,.0f}"
    return f"{number:.2f}"


def build(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("category") or "other"), []).append(row)
    fields = []
    for category, items in grouped.items():
        icon, label = _CATEGORY.get(category, ("🗓", "기타"))
        lines = []
        for row in items:
            lines.append((
                str(row.get("series_name_ko") or row["series_id"]),
                _number(row.get("first_actual_value"), row.get("unit")),
                _number(row.get("closing_survey_value"), row.get("unit")),
                _number(row.get("market_surprise"), row.get("unit")),
                _number(row.get("closing_nowcast_value"), row.get("unit")),
                _number(row.get("closing_own_model_value"), row.get("unit")),
                _number(row.get("model_error"), row.get("unit")),
                _number(row.get("revision"), row.get("unit")),
            ))
        fields.append({
            "name": f"{icon} {label} ({len(items)})",
            "value": table(lines, right=(1, 2, 3, 4, 5, 6, 7)),
        })
    return {
        "title": "경제지표 발표",
        "description": (
            f"### 🗓 {len(rows)}건의 first actual\n"
            "-# 열: 실제 · Survey · 시장 서프라이즈 · Nowcast · 자체모델 · 모델오차 · 개정\n"
            "-# Survey가 없으면 시장 서프라이즈는 — 입니다. 자체모델은 시장 예상이 아닙니다."
            " 실제는 최초 보관값, 예상은 발표 전에 수집한 마지막 값입니다."
        ),
        "color": _ACCENT,
        "fields": fields[:25],
        "footer": {"text": date.today().isoformat()},
    }
