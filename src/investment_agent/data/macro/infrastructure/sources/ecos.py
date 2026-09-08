"""한국은행 통계(ECOS)에서 값을 받아온다."""
from __future__ import annotations

import os
from datetime import date

import pandas as pd
import requests

from investment_agent.data.macro.infrastructure.fetch import safe_fetch
from investment_agent.platform.logging import get_logger
from investment_agent.platform.retry import transient_retry

log = get_logger(__name__)
_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"
_PAGE_SIZE = 1000


def _freq_token(freq: str) -> str:
    return {"daily": "D", "weekly": "D", "monthly": "M", "quarterly": "Q"}.get(freq, "D")


def _fmt(d: date, freq: str) -> str:
    if freq == "monthly":
        return d.strftime("%Y%m")
    if freq == "quarterly":
        q = (d.month - 1) // 3 + 1
        return f"{d.year}Q{q}"
    return d.strftime("%Y%m%d")


def _api_error(payload: dict) -> str:
    result = payload.get("RESULT") or {}
    return f"{result.get('CODE') or 'unknown'}: {result.get('MESSAGE') or 'invalid response'}"


@transient_retry()
def _fetch_one(
    stat: str,
    item: str,
    freq: str,
    start: date,
    end: date,
    *,
    expected_item_name: str | None = None,
    expected_unit: str | None = None,
) -> pd.Series:
    api_key = (os.environ.get("ECOS_API_KEY") or "").strip()
    if not api_key:
        raise ValueError("ECOS_API_KEY 환경변수가 설정되지 않았습니다.")
    tok = _freq_token(freq)
    rows: list[dict] = []
    first_row = 1
    total_count: int | None = None
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    while total_count is None or first_row <= total_count:
        last_row = first_row + _PAGE_SIZE - 1
        url = (
            f"{_BASE}/{api_key}/json/kr/{first_row}/{last_row}/{stat}/{tok}/"
            f"{_fmt(start, freq)}/{_fmt(end, freq)}/{item}"
        )
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        payload = r.json()
        block = payload.get("StatisticSearch")
        if block is None:
            raise ValueError(f"ECOS API error ({_api_error(payload)})")
        if not isinstance(block, dict):
            raise TypeError("ECOS StatisticSearch response must be an object")
        page = block.get("row", []) or []
        if total_count is None:
            total_count = int(block.get("list_total_count") or len(page))
        rows.extend(page)
        if not page or len(rows) >= total_count:
            break
        first_row += _PAGE_SIZE

    items: dict = {}
    for row in rows:
        if row.get("STAT_CODE") not in (None, stat):
            raise ValueError(f"ECOS stat contract mismatch: expected {stat}")
        if row.get("ITEM_CODE1") not in (None, item):
            raise ValueError(f"ECOS item contract mismatch: expected {item}")
        if expected_item_name and row.get("ITEM_NAME1") != expected_item_name:
            raise ValueError(
                "ECOS item name contract mismatch: "
                f"expected {expected_item_name!r}, got {row.get('ITEM_NAME1')!r}"
            )
        if expected_unit and row.get("UNIT_NAME") != expected_unit:
            raise ValueError(
                "ECOS unit contract mismatch: "
                f"expected {expected_unit!r}, got {row.get('UNIT_NAME')!r}"
            )
        v = row.get("DATA_VALUE")
        t = row.get("TIME")
        if not v or not t:
            continue
        try:
            if freq == "monthly":
                ts = pd.Period(t, freq="M").end_time.normalize()
            elif freq == "quarterly":
                ts = pd.Period(t, freq="Q").end_time.normalize()
            else:
                ts = pd.to_datetime(t, format="%Y%m%d")
            items[ts] = float(v)
        except (ValueError, TypeError):
            continue
    return pd.Series(items).sort_index()


def fetch_batch(
    indicators: list[dict], start: date, end: date,
) -> tuple[dict[str, pd.Series], list[dict]]:
    def _per(ind: dict) -> pd.Series:
        params = ind.get("source_params") or {}
        stat = params.get("stat")
        item = params.get("item")
        # cycle 값이 있으면 그걸로, 없으면 지표 frequency로 주기 결정
        freq = {"M": "monthly", "Q": "quarterly", "D": "daily"}.get(
            params.get("cycle"), ind.get("frequency", "daily")
        )
        if not stat or not item:
            return pd.Series(dtype=float)
        s = _fetch_one(
            stat,
            item,
            freq,
            start,
            end,
            expected_item_name=params.get("expected_item_name"),
            expected_unit=params.get("expected_unit"),
        )
        scale = params.get("scale")
        if scale is not None:
            s = s * float(scale)
        return s
    return safe_fetch(log, indicators, _per)
