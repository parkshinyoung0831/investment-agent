"""Alpha Vantage NEWS_SENTIMENT 종목 뉴스 fetcher.

TradingAgents(Apache-2.0) `dataflows/alpha_vantage_common.py` + `alpha_vantage_news.py`
에서 이식(요청·에러 분류 로직만). global/insider 엔드포인트는 옮기지 않았다 — 이
저장소는 종목별 뉴스(get_news) 하나만 쓴다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Callable

_API_BASE_URL = "https://www.alphavantage.co/query"
_REQUEST_TIMEOUT = 30.0


class AlphaVantageNotConfiguredError(RuntimeError):
    """ALPHA_VANTAGE_API_KEY가 없거나 provider가 키를 거부했다."""


class AlphaVantageRateLimitError(RuntimeError):
    """Alpha Vantage 호출 한도(일일/분당)를 넘었다."""


def _api_key_from_env() -> str:
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()
    if not api_key:
        raise AlphaVantageNotConfiguredError("ALPHA_VANTAGE_API_KEY environment variable is not set.")
    return api_key


def format_datetime_for_api(date_input: str) -> str:
    """yyyy-mm-dd(또는 이미 변환된 값)을 Alpha Vantage가 요구하는 YYYYMMDDTHHMM으로 바꾼다."""
    if len(date_input) == 13 and "T" in date_input:
        return date_input
    try:
        return datetime.strptime(date_input, "%Y-%m-%d").strftime("%Y%m%dT0000")
    except ValueError:
        pass
    try:
        return datetime.strptime(date_input, "%Y-%m-%d %H:%M").strftime("%Y%m%dT%H%M")
    except ValueError as exc:
        raise ValueError(f"Unsupported date format: {date_input}") from exc


def _default_http_get(params: dict[str, str], timeout: float) -> str:
    import requests

    response = requests.get(_API_BASE_URL, params=params, timeout=timeout)
    response.raise_for_status()
    return response.text


def _request(
    function_name: str,
    params: dict[str, str],
    *,
    http_get: Callable[[dict[str, str], float], str] = _default_http_get,
) -> str:
    api_params = {**params, "function": function_name, "apikey": _api_key_from_env()}
    response_text = http_get(api_params, _REQUEST_TIMEOUT)
    try:
        response_json: Any = json.loads(response_text)
    except json.JSONDecodeError:
        return response_text
    if not isinstance(response_json, dict):
        return response_text
    notice = response_json.get("Information") or response_json.get("Note")
    if notice:
        lowered = str(notice).lower()
        if any(marker in lowered for marker in ("rate limit", "requests per day", "call frequency", "premium")):
            raise AlphaVantageRateLimitError(f"Alpha Vantage rate limit exceeded: {notice}")
        if "api key" in lowered or "apikey" in lowered:
            raise AlphaVantageNotConfiguredError(f"Alpha Vantage API key invalid or missing: {notice}")
    return response_text


def get_news(
    ticker: str,
    start_date: str,
    end_date: str,
    *,
    http_get: Callable[[dict[str, str], float], str] = _default_http_get,
) -> str:
    """종목 뉴스·감성 데이터를 Alpha Vantage NEWS_SENTIMENT에서 가져온다(원문 JSON 텍스트)."""
    params = {
        "tickers": ticker,
        "time_from": format_datetime_for_api(start_date),
        "time_to": format_datetime_for_api(end_date),
    }
    return _request("NEWS_SENTIMENT", params, http_get=http_get)
