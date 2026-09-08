"""단위가 US GDP headline measure와 동일한 Atlanta Fed GDPNow만 수집한다."""
from __future__ import annotations

import math
import os
from datetime import date

import requests

from investment_agent.platform.retry import retry_on_5xx
from investment_agent.data.macro.infrastructure.releases.sources.actuals import _fred_slot

_BASE = "https://api.stlouisfed.org/fred/series/observations"


@retry_on_5xx()
def fetch_gdpnow(*, observation_start: date) -> dict[str, dict[str, float]]:
    """US_GDP ref_period -> annualized QoQ nowcast.

    STLENI는 GDP nowcast와 같은 측정 대상이 아니므로 의도적으로 포함하지 않는다.
    """
    _fred_slot()
    response = requests.get(
        _BASE,
        params={
            "series_id": "GDPNOW",
            "api_key": os.environ["FRED_API_KEY"],
            "file_type": "json",
            "observation_start": observation_start.isoformat(),
        },
        timeout=30,
    )
    response.raise_for_status()
    values: dict[str, float] = {}
    for item in response.json().get("observations", []):
        raw = item.get("value")
        if raw in (None, "", "."):
            continue
        value = float(raw)
        if math.isfinite(value):
            values[str(item["date"])] = value
    if not values:
        raise ValueError("GDPNow returned no finite observations")
    return {"US_GDP": values}
