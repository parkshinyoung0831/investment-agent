"""Yahoo Finance에서 발표 실적과 EPS 서프라이즈를 읽는 어댑터."""
from __future__ import annotations

import math

import yfinance as yf

from investment_agent.platform.retry import network_retry


@network_retry(attempts=3, max_wait=5)
def fetch_reported_earnings(
    ticker: str,
) -> dict[str, dict[str, float | None]]:
    """발표 일자별 EPS 예상·실제·서프라이즈를 반환한다."""
    # 속보 감지의 최근값뿐 아니라 수동 백필도 이 어댑터를 공유한다. Yahoo의
    # 한 번 요청 상한 안에서 가능한 넓은 발표 이력을 읽는다.
    dates = yf.Ticker(ticker).get_earnings_dates(limit=100)
    if dates is None or dates.empty:
        return {}
    rows: dict[str, dict[str, float | None]] = {}
    for index, row in dates.iterrows():
        report_date = (
            index.strftime("%Y-%m-%d")
            if hasattr(index, "strftime")
            else str(index)[:10]
        )
        rows[report_date] = {
            "eps_estimate": _optional_float(row.get("EPS Estimate")),
            "eps_actual": _optional_float(row.get("Reported EPS")),
            "surprise_pct": _optional_float(row.get("Surprise(%)")),
        }
    return rows


def _optional_float(value) -> float | None:
    if value is None or str(value).lower().startswith("nan"):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None
