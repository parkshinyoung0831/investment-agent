"""미국 경제지표 사이트(FRED)에서 값을 받아온다."""
from __future__ import annotations

import os
from datetime import date

import pandas as pd
import requests

from investment_agent.data.macro.infrastructure.fetch import safe_fetch
from investment_agent.platform.logging import get_logger
from investment_agent.platform.retry import transient_retry

log = get_logger(__name__)
_BASE = "https://api.stlouisfed.org/fred/series/observations"


@transient_retry()
def _fetch_one(series_id: str, start: date, end: date) -> pd.Series:
    r = requests.get(_BASE, params={
        "series_id":         series_id,
        "api_key":           os.environ["FRED_API_KEY"],
        "file_type":         "json",
        "observation_start": str(start),
        "observation_end":   str(end),
    }, timeout=30)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    items = {
        pd.to_datetime(o["date"]): float(o["value"])
        for o in obs if o["value"] not in (".", "")
    }
    return pd.Series(items).sort_index()


def fetch_batch(
    indicators: list[dict], start: date, end: date,
) -> tuple[dict[str, pd.Series], list[dict]]:
    # FRED 실제 시리즈 ID는 source_params.fred_id (내부 series_id와 다름: 예 TNX→DGS10).
    def _per(ind: dict) -> pd.Series:
        params = ind.get("source_params") or {}
        fred_id = params.get("fred_id") or ind["series_id"]
        s = _fetch_one(fred_id, start, end)
        scale = params.get("scale")
        if scale is not None:
            s = s * float(scale)
        return s
    return safe_fetch(log, indicators, _per)
