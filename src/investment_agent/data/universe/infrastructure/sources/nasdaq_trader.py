"""Official US symbol-directory metadata used to classify listed securities."""
from __future__ import annotations

import csv
from functools import lru_cache
from io import StringIO

import requests

from investment_agent.data.universe.domain.normalization import norm_ticker
from investment_agent.platform.retry import network_retry

_BASE_URL = "https://www.nasdaqtrader.com/dynamic/SymDir"
_HEADERS = {
    "User-Agent": (
        "investment-agent/0.1 "
        "(+https://github.com/parkshinyoung0831/investment-agent)"
    ),
    "Accept": "text/plain",
}


@network_retry()
def _download(filename: str) -> str:
    response = requests.get(
        f"{_BASE_URL}/{filename}", headers=_HEADERS, timeout=30
    )
    response.raise_for_status()
    return response.text


def _other_listed_ticker(raw: str) -> str:
    # Nasdaq Trader uses ``BAC$B`` for preferred series while SEC/Yahoo use
    # ``BAC-PB``. A dot, by contrast, is a common-share class separator.
    value = str(raw or "").strip().upper()
    if "$" in value:
        root, suffix = value.split("$", 1)
        return norm_ticker(f"{root}-P{suffix}")
    return norm_ticker(value)


def _parse_file(text: str, *, other_listed: bool) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    reader = csv.DictReader(StringIO(text), delimiter="|")
    ticker_field = "ACT Symbol" if other_listed else "Symbol"
    for row in reader:
        raw_ticker = str(row.get(ticker_field) or "")
        if raw_ticker.startswith("File Creation Time"):
            continue
        ticker = _other_listed_ticker(raw_ticker) if other_listed else norm_ticker(raw_ticker)
        title = str(row.get("Security Name") or "").strip()
        if not ticker or not title or row.get("Test Issue") == "Y":
            continue
        rows[ticker] = {
            "security_title": title,
            "is_etf": row.get("ETF") == "Y",
        }
    return rows


@lru_cache(maxsize=1)
def fetch_security_metadata() -> dict[str, dict]:
    """Return active Nasdaq/UTP symbol titles keyed in SEC/Yahoo ticker format."""
    nasdaq = _parse_file(_download("nasdaqlisted.txt"), other_listed=False)
    other = _parse_file(_download("otherlisted.txt"), other_listed=True)
    combined = {**other, **nasdaq}
    if len(combined) < 8_000:
        raise RuntimeError(
            f"Nasdaq Trader symbol directory is unexpectedly small: {len(combined)}"
        )
    return combined
