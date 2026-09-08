"""재시도 정책.

## 무엇을 다시 시도하는가

**다시 해서 달라질 수 있는 것만** 다시 한다. 네트워크 끊김, 타임아웃, 429, 5xx,
Postgres의 일시적 상태(연결 없음·자원 부족·교착)가 그렇다.

반대로 401·403·404·제약 위반은 몇 번을 해도 같다. 그것을 재시도하면 두 가지를
잃는다 — 고장을 알아채는 시간이 늦어지고, 상대 서비스에 같은 실패를 반복해 보내
rate limit을 스스로 만든다.

## 예외 메시지를 그대로 찍지 않는다

외부 API 예외에는 요청 URL이 통째로 들어 있고, 그 URL에는 API 키가 붙어 있다.
`redact()`를 거쳐야 로그로 나간다.

## 재시도가 안전한 호출에만 붙인다

읽기는 몇 번 해도 같다. **쓰기는 다르다** — 주문 제출처럼 두 번 실행되면 안 되는
호출은 재시도 데코레이터가 아니라 멱등키로 보호한다. 여기 정책을 주문 경로에
그대로 붙이지 마라.
"""
from __future__ import annotations

from typing import Any, Callable

import httpx
import requests
from postgrest.exceptions import APIError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from investment_agent.platform.logging import get_logger, redact

log = get_logger(__name__)

# 어느 라이브러리를 쓰든 "연결이 안 됐다/늦었다"는 같은 뜻이다.
TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    TimeoutError,
    ConnectionError,
    OSError,
    requests.Timeout,
    requests.ConnectionError,
    httpx.TimeoutException,
    httpx.TransportError,
)

# PostgREST/Postgres의 일시적 상태. 08=연결 예외, 53=자원 부족.
_TRANSIENT_SQLSTATE_PREFIX = ("08", "53")
_TRANSIENT_SQLSTATE = frozenset({
    "40001",   # serialization_failure
    "40P01",   # deadlock_detected
    "55P03",   # lock_not_available
    "57014",   # query_canceled (statement_timeout)
    "57P01", "57P02", "57P03",  # admin shutdown / crash / cannot connect now
})
# PGRST002는 스키마 캐시를 못 읽은 상태다. 노출 스키마 목록이 잠시 어긋나면 나므로
# 재시도할 값어치가 있다.
_TRANSIENT_PGRST = frozenset({"PGRST000", "PGRST001", "PGRST002", "PGRST003"})


def _status_is_transient(status: int) -> bool:
    return status == 429 or 500 <= status < 600


def is_transient(exc: BaseException) -> bool:
    """다시 해볼 값어치가 있는 실패인가."""
    response = getattr(exc, "response", None)
    if isinstance(exc, (requests.HTTPError, httpx.HTTPStatusError)) and response is not None:
        return _status_is_transient(response.status_code)
    if isinstance(exc, APIError):
        # postgrest-py는 HTTPStatusError 대신 APIError를 던진다. 제약 위반·권한
        # 오류까지 재시도하면 같은 실패를 네 번 반복할 뿐이다.
        code = str(exc.code or "")
        return (
            code.startswith(_TRANSIENT_SQLSTATE_PREFIX)
            or code in _TRANSIENT_SQLSTATE
            or code in _TRANSIENT_PGRST
        )
    return isinstance(exc, TRANSPORT_ERRORS)


def _policy(predicate: Callable[[BaseException], bool], label: str, attempts: int, max_wait: float) -> Any:
    return retry(
        # reraise=True: 마지막 예외를 그대로 올린다. tenacity가 감싸면 부르는 쪽의
        # except 절이 안 잡힌다.
        reraise=True,
        retry=retry_if_exception(predicate),
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1, min=1, max=max_wait),
        before_sleep=lambda state: log.warning(
            "%s attempt %d/%d failed: %s",
            label,
            state.attempt_number,
            attempts,
            redact(str(state.outcome.exception())) if state.outcome else "?",
        ),
    )


def network_retry(attempts: int = 4, max_wait: float = 30.0) -> Any:
    """연결·타임아웃만 재시도. 상태 코드는 보지 않는다."""
    return _policy(lambda exc: isinstance(exc, TRANSPORT_ERRORS), "network_retry", attempts, max_wait)


def transient_retry(attempts: int = 4, max_wait: float = 30.0) -> Any:
    """연결 오류 + 429/5xx + Postgres 일시 오류를 재시도. 외부 API 읽기의 기본값."""
    return _policy(is_transient, "transient_retry", attempts, max_wait)


def _is_retryable(exc: BaseException) -> bool:
    """구 공통 API의 private 테스트 계약을 최종 platform 정책으로 연결한다."""
    return is_transient(exc)


def retry_on_5xx(attempts: int = 4, max_wait: float = 30.0) -> Any:
    """네트워크·429·5xx·PostgREST 일시 오류 재시도 데코레이터."""
    return _policy(is_transient, "retry_on_5xx", attempts, max_wait)


__all__ = [
    "TRANSPORT_ERRORS",
    "_is_retryable",
    "is_transient",
    "network_retry",
    "retry_on_5xx",
    "transient_retry",
]
