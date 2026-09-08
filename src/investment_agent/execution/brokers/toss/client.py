"""토스증권 Open API의 읽기 전용 계좌·시세·장운영 클라이언트.

주문 mutation은 permit이 필요한 ``toss_orders`` 모듈에만 둔다.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import requests

from investment_agent.platform.retry import retry_on_5xx
from investment_agent.execution.brokers.toss.auth import (
    TossAuthError,
    access_token as shared_access_token,
    authorized_request,
)

_BASE = "https://openapi.tossinvest.com"
_ACCOUNTS_URL = f"{_BASE}/api/v1/accounts"
_HOLDINGS_URL = f"{_BASE}/api/v1/holdings"
_PRICES_URL = f"{_BASE}/api/v1/prices"
_BUYING_POWER_URL = f"{_BASE}/api/v1/buying-power"
_EXCHANGE_RATE_URL = f"{_BASE}/api/v1/exchange-rate"
_ORDERS_URL = f"{_BASE}/api/v1/orders"
_US_MARKET_CALENDAR_URL = f"{_BASE}/api/v1/market-calendar/US"
_PRICE_BATCH = 200


class TossExecutionError(RuntimeError):
    """토스 실행 준비에 필요한 인증·조회·응답 검증 실패."""


@dataclass(frozen=True)
class TossUsRegularSession:
    market_date: date
    start_at: datetime
    end_at: datetime


def to_toss_symbol(ticker: str) -> str:
    """저장소 표기(BRK-B)를 토스 표기(BRK.B)로 변환한다."""
    return str(ticker).strip().upper().replace("-", ".")


def from_toss_symbol(symbol: str) -> str:
    """토스의 미국 종목 표기를 저장소 표기로 변환한다."""
    return str(symbol).strip().upper().replace(".", "-")


def access_token() -> str:
    """공용 토큰 관리자의 token을 실행 계층 오류로 변환해 반환한다."""
    try:
        return shared_access_token()
    except TossAuthError as exc:
        raise TossExecutionError(str(exc)) from exc


def _authorized_headers(*, account_seq: int | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {access_token()}",
        "Accept": "application/json",
    }
    if account_seq is not None:
        headers["X-Tossinvest-Account"] = str(account_seq)
    return headers


@retry_on_5xx(attempts=3)
def _get_json(
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        response = authorized_request(
            requests.get,
            url,
            headers=headers,
            params=params,
            timeout=30,
        )
    except TossAuthError as exc:
        raise TossExecutionError(str(exc)) from exc
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise TossExecutionError("토스 API 응답이 객체가 아닙니다")
    return payload


def _get(
    url: str,
    *,
    account_seq: int | None = None,
    params: dict[str, str] | None = None,
    label: str,
) -> dict[str, Any]:
    try:
        return _get_json(
            url,
            headers=_authorized_headers(account_seq=account_seq),
            params=params,
        )
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        raise TossExecutionError(f"토스 {label} 실패(status={status})") from exc
    except requests.RequestException as exc:
        raise TossExecutionError(f"토스 {label} 중 네트워크 오류가 발생했습니다") from exc


def fetch_accounts() -> list[dict[str, Any]]:
    payload = _get(_ACCOUNTS_URL, label="계좌 목록 조회")
    rows = payload.get("result")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise TossExecutionError("토스 계좌 응답의 result가 객체 배열이 아닙니다")
    for row in rows:
        if not isinstance(row.get("accountSeq"), int):
            raise TossExecutionError("토스 계좌 항목에 유효한 accountSeq가 없습니다")
    return rows


def resolve_account_seq(requested: int | None = None) -> int:
    """명시값 또는 환경변수를 실제 종합매매 계좌와 대조한다."""
    configured = requested
    if configured is None:
        raw = os.environ.get("TOSS_ACCOUNT_SEQ", "").strip()
        if raw:
            try:
                configured = int(raw)
            except ValueError as exc:
                raise TossExecutionError("TOSS_ACCOUNT_SEQ는 정수여야 합니다") from exc

    accounts = fetch_accounts()
    available = {
        int(row["accountSeq"])
        for row in accounts
        if str(row.get("accountType") or "BROKERAGE") == "BROKERAGE"
    }
    if configured is not None:
        if configured not in available:
            raise TossExecutionError("지정한 TOSS_ACCOUNT_SEQ가 사용 가능한 종합매매 계좌가 아닙니다")
        return configured
    if len(available) == 1:
        return next(iter(available))
    if not available:
        raise TossExecutionError("사용 가능한 토스 종합매매 계좌가 없습니다")
    raise TossExecutionError("토스 계좌가 여러 개입니다. TOSS_ACCOUNT_SEQ를 명시하세요")


def fetch_holdings(account_seq: int) -> dict[str, Any]:
    payload = _get(_HOLDINGS_URL, account_seq=account_seq, label="보유종목 조회")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise TossExecutionError("토스 보유종목 응답의 result가 객체가 아닙니다")
    items = result.get("items")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise TossExecutionError("토스 보유종목 응답의 items가 객체 배열이 아닙니다")
    return result


def fetch_buying_power(account_seq: int, *, currency: str = "USD") -> float:
    payload = _get(
        _BUYING_POWER_URL,
        account_seq=account_seq,
        params={"currency": currency},
        label="매수 가능 금액 조회",
    )
    result = payload.get("result")
    if not isinstance(result, dict):
        raise TossExecutionError("토스 매수 가능 금액 응답의 result가 객체가 아닙니다")
    try:
        value = float(result["cashBuyingPower"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TossExecutionError("토스 매수 가능 금액이 올바르지 않습니다") from exc
    if value < 0:
        raise TossExecutionError("토스 매수 가능 금액이 음수입니다")
    return value


def fetch_exchange_rate(
    *,
    base_currency: str = "USD",
    quote_currency: str = "KRW",
    date_time: str | None = None,
) -> dict[str, Any]:
    """토스 참고용 환율을 읽어 통화 변환에 필요한 값만 반환한다."""

    base = str(base_currency).strip().upper()
    quote = str(quote_currency).strip().upper()
    if not base or not quote or base == quote:
        raise TossExecutionError("토스 환율 조회 통화가 올바르지 않습니다")
    params = {"baseCurrency": base, "quoteCurrency": quote}
    if date_time:
        params["dateTime"] = str(date_time)
    payload = _get(
        _EXCHANGE_RATE_URL,
        params=params,
        label="환율 조회",
    )
    result = payload.get("result")
    if not isinstance(result, dict):
        raise TossExecutionError("토스 환율 응답의 result가 객체가 아닙니다")
    try:
        rate = float(result["rate"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TossExecutionError("토스 환율이 올바르지 않습니다") from exc
    if not math.isfinite(rate) or rate <= 0:
        raise TossExecutionError("토스 환율이 양수가 아닙니다")
    return {
        "base_currency": str(result.get("baseCurrency") or base).upper(),
        "quote_currency": str(result.get("quoteCurrency") or quote).upper(),
        "rate": rate,
        "mid_rate": result.get("midRate"),
        "valid_from": result.get("validFrom"),
        "valid_until": result.get("validUntil"),
    }


def fetch_open_orders(account_seq: int) -> list[dict[str, Any]]:
    payload = _get(
        _ORDERS_URL,
        account_seq=account_seq,
        params={"status": "OPEN"},
        label="미체결 주문 조회",
    )
    result = payload.get("result")
    if not isinstance(result, dict):
        raise TossExecutionError("토스 주문 목록 응답의 result가 객체가 아닙니다")
    rows = result.get("orders")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise TossExecutionError("토스 주문 목록의 orders가 객체 배열이 아닙니다")
    return rows


def fetch_prices(symbols: set[str]) -> tuple[dict[str, float], dict[str, str | None]]:
    """저장소 ticker 집합의 현재가와 시세 시각을 반환한다."""
    normalized = sorted({str(symbol).strip().upper() for symbol in symbols if symbol})
    prices: dict[str, float] = {}
    timestamps: dict[str, str | None] = {}
    for index in range(0, len(normalized), _PRICE_BATCH):
        batch = normalized[index:index + _PRICE_BATCH]
        toss_to_local = {to_toss_symbol(symbol): symbol for symbol in batch}
        payload = _get(
            _PRICES_URL,
            params={"symbols": ",".join(toss_to_local)},
            label="현재가 조회",
        )
        rows = payload.get("result")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise TossExecutionError("토스 현재가 응답의 result가 객체 배열이 아닙니다")
        for row in rows:
            local = toss_to_local.get(str(row.get("symbol") or "").upper())
            if local is None:
                continue
            try:
                price = float(row["lastPrice"])
            except (KeyError, TypeError, ValueError) as exc:
                raise TossExecutionError(f"토스 {local} 현재가가 올바르지 않습니다") from exc
            if price <= 0:
                raise TossExecutionError(f"토스 {local} 현재가가 양수가 아닙니다")
            prices[local] = price
            raw_timestamp = row.get("timestamp")
            timestamps[local] = str(raw_timestamp) if raw_timestamp else None
        if index + _PRICE_BATCH < len(normalized):
            time.sleep(0.1)
    missing = sorted(set(normalized) - set(prices))
    if missing:
        raise TossExecutionError("토스 현재가 누락: " + ", ".join(missing))
    return prices, timestamps


def fetch_us_regular_session(market_date: date) -> TossUsRegularSession | None:
    """공식 미국 장 캘린더에서 해당 현지일 정규장 구간을 반환한다."""
    if not isinstance(market_date, date) or isinstance(market_date, datetime):
        raise TossExecutionError("미국 장 캘린더 날짜가 올바르지 않습니다")
    payload = _get(
        _US_MARKET_CALENDAR_URL,
        params={"date": market_date.isoformat()},
        label="미국 장 운영 정보 조회",
    )
    result = payload.get("result")
    today = result.get("today") if isinstance(result, dict) else None
    if not isinstance(today, dict) or today.get("date") != market_date.isoformat():
        raise TossExecutionError("토스 미국 장 캘린더의 today가 요청일과 다릅니다")
    regular = today.get("regularMarket")
    if regular is None:
        return None
    if not isinstance(regular, dict):
        raise TossExecutionError("토스 미국 정규장 정보가 객체가 아닙니다")
    try:
        start = datetime.fromisoformat(str(regular["startTime"]))
        end = datetime.fromisoformat(str(regular["endTime"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise TossExecutionError("토스 미국 정규장 시각이 올바르지 않습니다") from exc
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise TossExecutionError("토스 미국 정규장 구간이 올바르지 않습니다")
    return TossUsRegularSession(
        market_date=market_date,
        start_at=start,
        end_at=end,
    )
