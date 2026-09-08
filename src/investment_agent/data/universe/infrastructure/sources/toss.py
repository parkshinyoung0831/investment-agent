"""toss.py — 토스증권 Open API에서 미국 종목의 한글명을 보강한다.

OAuth2 client_credentials로 access token을 받아 `GET /api/v1/stocks?symbols=...`(배치)로
종목 마스터를 조회하고, 한글명(`name` 필드)을 가져온다. Wikipedia langlink/Wikidata로
못 채운 추적 종목의 폴백 소스.

인증: 환경변수 `TOSS_CLIENT_ID` / `TOSS_CLIENT_SECRET`.
주의: 토스 Open API는 호출 IP 허용목록 기반이라 GitHub Actions에서는 실행하지 않는다.
      이 source helper는 실패 청크를 미시도 상태로 반환하고, 전용 local entrypoint가
      incomplete metrics를 exit code 1로 판정한다.
심볼 표기: 우리 종목코드는 `BRK-B`(대시), 토스는 `BRK.B`(점) — 조회 시 변환하고 응답을 되돌린다.
"""
from __future__ import annotations

import time

import requests

from investment_agent.platform.logging import get_logger
from investment_agent.platform.retry import retry_on_5xx
from investment_agent.execution.brokers.toss.auth import (
    TossAuthError,
    authorized_request,
    credentials_configured,
)
from investment_agent.execution.brokers.toss.auth import (
    access_token as shared_access_token,
)

log = get_logger(__name__)

_BASE = "https://openapi.tossinvest.com"
_STOCKS_URL = f"{_BASE}/api/v1/stocks"
_BATCH = 50        # 한 번에 조회할 심볼 수 (콤마 구분)
_SLEEP = 0.25      # STOCK 그룹 5 TPS 준수(여유 포함)


def _access_token() -> str | None:
    """공용 token을 반환하고 실패는 미시도 상태로 호출자에게 전달한다."""
    if not credentials_configured():
        return None
    try:
        return shared_access_token()
    except TossAuthError as exc:  # 한글명 보강은 선택 단계라 전체 ETL을 가리지 않는다.
        log.warning("  Toss 토큰 발급 실패(보강 skip): %s", exc)
        return None


def _to_toss_symbol(ticker: str) -> str:
    """우리 표기(BRK-B) → 토스 표기(BRK.B)."""
    return ticker.replace("-", ".")


@retry_on_5xx(attempts=3)
def _fetch_chunk(symbols: list[str], headers: dict) -> list[dict]:
    resp = authorized_request(
        requests.get,
        _STOCKS_URL,
        params={"symbols": ",".join(symbols)},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("result", []) or []


def fetch_korean_names(tickers: list[str]) -> tuple[dict[str, str], list[str]]:
    """종목코드 목록 → (찾은 {ticker: 한글명}, 실제로 조회한 ticker 목록).

    두 번째 값(attempted)은 '실제로 토스에 물어본' 종목만 담는다 — 호출측이 이걸로만
    checked_at을 찍어, 자격증명/IP 문제로 조회를 못 한 경우(예: CI)에 미조회 종목을
    '시도함'으로 잘못 마킹하지 않게 한다. 조회 자체를 못 하면 ({}, [])."""
    if not tickers:
        return {}, []
    token = _access_token()
    if not token:
        return {}, []
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    out: dict[str, str] = {}
    attempted: list[str] = []
    for i in range(0, len(tickers), _BATCH):
        chunk = tickers[i:i + _BATCH]
        toss_to_our = {_to_toss_symbol(t): t for t in chunk}
        try:
            result = _fetch_chunk(list(toss_to_our), headers)
        except Exception as exc:  # noqa: BLE001 - incomplete chunks remain pending and fail locally
            log.warning("  Toss 조회 실패 (chunk %d): %s", i // _BATCH, exc)
            time.sleep(_SLEEP)
            continue
        attempted.extend(chunk)
        for item in result:
            our = toss_to_our.get(str(item.get("symbol")))
            name_ko = (item.get("name") or "").strip()
            if our and name_ko:
                out[our] = name_ko
        time.sleep(_SLEEP)
    log.info("  Toss 한글명: %d/%d (조회 %d)", len(out), len(tickers), len(attempted))
    return out, attempted
