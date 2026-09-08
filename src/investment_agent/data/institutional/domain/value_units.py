"""13F ``value``의 달러/천 달러 단위를 공시별로 판별한다.

판별 아이디어는 edgartools 5.36.0의 `_detect_value_in_thousands`를
프로젝트의 typed 모델에 맞게 의존성 없이 다시 구현했다. 자세한 출처는
`src/investment_agent/data/institutional/NOTICE.md`를 참고한다.
"""
from __future__ import annotations

from datetime import date

from investment_agent.data.institutional.domain.models import RawPosition

_THOUSANDS_CUTOFF = date(2022, 9, 30)
_DOLLARS_SCHEMA_VERSION = "X0202"
_SUB_DOLLAR_THRESHOLD = 1.0
_THOUSANDS_FRACTION = 0.5


def _fallback_scale(schema_version: str | None, period_end: date) -> int:
    if schema_version:
        return 1 if schema_version.strip().upper() >= _DOLLARS_SCHEMA_VERSION else 1000
    return 1000 if period_end <= _THOUSANDS_CUTOFF else 1


def detect_value_scale(
    rows: list[RawPosition],
    *,
    schema_version: str | None,
    period_end: date,
) -> int:
    """원본 13F value를 USD로 바꿀 배수(1 또는 1000)를 반환한다."""
    implied_prices = [
        row.reported_value / row.quantity
        for row in rows
        if row.quantity_type == "SH"
        and row.position_kind == "SHARES"
        and row.quantity > 0
        and row.reported_value > 0
    ]
    if implied_prices:
        sub_dollar_fraction = sum(
            price < _SUB_DOLLAR_THRESHOLD for price in implied_prices
        ) / len(implied_prices)
        if sub_dollar_fraction >= _THOUSANDS_FRACTION:
            return 1000
    return _fallback_scale(schema_version, period_end)
