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

# `OSError`는 파일 오류도 포함한다. 없는 파일·권한 오류는 다시 해도 같은데, 그것을 네 번 재시도하면 고장을
# 늦게 알아채고 백오프만 길어진다. 연결·타임아웃 계열만 남기고 파일 계열은 뺀다.
_NEVER_TRANSIENT_OS_ERRORS: tuple[type[BaseException], ...] = (
    FileNotFoundError,
    FileExistsError,
    PermissionError,
    IsADirectoryError,
    NotADirectoryError,
)


def _is_transport_error(exc: BaseException) -> bool:
    return isinstance(exc, TRANSPORT_ERRORS) and not isinstance(exc, _NEVER_TRANSIENT_OS_ERRORS)


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


def _is_http2_internal_error(exc: BaseException) -> bool:
    """HTTP/2 연결의 내부 상태 오류(`KeyError: 3` 같은 스트림 번호 조회 실패)인가.

    여러 스레드가 한 HTTP/2 연결을 함께 쓰면 httpcore/h2가 스트림 표를 잘못 읽어 예외 종류가 `KeyError`로 새 나온다.
    요청은 이미 실패한 것이라 같은 읽기를 다시 보내면 새 스트림으로 성공한다. 예외 종류만으로는 고를 수 없으므로
    예외가 난 자리가 httpcore의 http2 모듈·h2 안일 때만 그렇다고 본다.
    """
    if not isinstance(exc, KeyError):
        return False
    frame = exc.__traceback__
    while frame is not None:
        filename = frame.tb_frame.f_code.co_filename.replace("\\", "/")
        if "/httpcore/" in filename and filename.endswith("http2.py") or "/h2/" in filename:
            return True
        frame = frame.tb_next
    return False


def is_transient(exc: BaseException) -> bool:
    """다시 해볼 값어치가 있는 실패인가."""
    if _is_http2_internal_error(exc):
        return True
    response = getattr(exc, "response", None)
    if isinstance(exc, (requests.HTTPError, httpx.HTTPStatusError)) and response is not None:
        return _status_is_transient(response.status_code)
    if isinstance(exc, APIError):
        # postgrest-py는 HTTPStatusError 대신 APIError를 던진다. 제약 위반·권한
        # 오류까지 재시도하면 같은 실패를 네 번 반복할 뿐이다.
        code = str(exc.code or "")
        description = f"{getattr(exc, 'message', '')} {getattr(exc, 'details', '')}".lower()
        cloudflare_html = (
            code == "400"
            and "json could not be generated" in description
            and ("cloudflare" in description or "<html" in description)
        )
        return (
            code.startswith(_TRANSIENT_SQLSTATE_PREFIX)
            or code in _TRANSIENT_SQLSTATE
            or code in _TRANSIENT_PGRST
            or cloudflare_html
        )
    return _is_transport_error(exc)


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
    return _policy(_is_transport_error, "network_retry", attempts, max_wait)


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
