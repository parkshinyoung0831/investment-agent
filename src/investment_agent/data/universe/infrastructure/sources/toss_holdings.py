"""토스증권 Open API의 계좌·보유종목 조회 클라이언트.

관심종목 API는 아직 제공되지 않으므로 공식 ``accounts``와 ``holdings``
엔드포인트만 사용한다. 이 클라이언트는 동기화용이라 인증·응답 오류를 숨기지
않는다. 실패한 조회를 빈 보유종목으로 오인하면 정상 관심종목이 해제될 수 있다.
"""
from __future__ import annotations

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


class TossApiError(RuntimeError):
    """토스 인증·API·응답 검증 실패."""


def access_token() -> str:
    """공용 토큰 관리자의 token을 알림 계층 오류로 변환해 반환한다."""
    try:
        return shared_access_token()
    except TossAuthError as exc:
        raise TossApiError(str(exc)) from exc


@retry_on_5xx(attempts=3)
def _get_json(url: str, *, headers: dict[str, str]) -> dict[str, Any]:
    try:
        response = authorized_request(
            requests.get,
            url,
            headers=headers,
            timeout=30,
        )
    except TossAuthError as exc:
        raise TossApiError(str(exc)) from exc
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise TossApiError("토스 API 응답이 객체가 아닙니다")
    return payload


def _authorized_headers(*, account_seq: int | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {access_token()}",
        "Accept": "application/json",
    }
    if account_seq is not None:
        headers["X-Tossinvest-Account"] = str(account_seq)
    return headers


def fetch_accounts() -> list[dict[str, Any]]:
    """사용 가능한 종합매매 계좌 목록을 검증해 반환한다."""
    try:
        payload = _get_json(_ACCOUNTS_URL, headers=_authorized_headers())
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        raise TossApiError(f"토스 계좌 목록 조회 실패(status={status})") from exc
    except requests.RequestException as exc:
        raise TossApiError("토스 계좌 목록 조회 중 네트워크 오류가 발생했습니다") from exc

    accounts = payload.get("result")
    if not isinstance(accounts, list):
        raise TossApiError("토스 계좌 응답의 result가 배열이 아닙니다")
    for account in accounts:
        if not isinstance(account, dict):
            raise TossApiError("토스 계좌 항목이 객체가 아닙니다")
        if not isinstance(account.get("accountSeq"), int):
            raise TossApiError("토스 계좌 항목에 유효한 accountSeq가 없습니다")
    return accounts


def fetch_holdings(account_seq: int) -> list[dict[str, Any]]:
    """한 계좌의 전체 보유종목을 검증해 반환한다."""
    try:
        payload = _get_json(
            _HOLDINGS_URL,
            headers=_authorized_headers(account_seq=account_seq),
        )
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        raise TossApiError(f"토스 보유종목 조회 실패(status={status})") from exc
    except requests.RequestException as exc:
        raise TossApiError("토스 보유종목 조회 중 네트워크 오류가 발생했습니다") from exc

    result = payload.get("result")
    if not isinstance(result, dict):
        raise TossApiError("토스 보유종목 응답의 result가 객체가 아닙니다")
    items = result.get("items")
    if not isinstance(items, list):
        raise TossApiError("토스 보유종목 응답의 items가 배열이 아닙니다")
    if any(not isinstance(item, dict) for item in items):
        raise TossApiError("토스 보유종목 항목이 객체가 아닙니다")
    return items
