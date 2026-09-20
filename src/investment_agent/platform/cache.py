"""선택적 Streamlit 캐시를 감싸는 플랫폼 데이터 cache decorator."""

from __future__ import annotations

from functools import wraps
from typing import Callable, ParamSpec, TypeVar, cast

P = ParamSpec("P")
R = TypeVar("R")


def cache_data(*, ttl: str | int | float, max_entries: int) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Streamlit이 없는 단위 테스트에서도 import 가능한 제한형 데이터 캐시.

    `status == "error"`인 결과는 캐시에 남기지 않는다(다음 호출이 다시 조회한다).
    """

    if max_entries < 1:
        raise ValueError("max_entries는 1 이상이어야 합니다.")

    def decorator(function: Callable[P, R]) -> Callable[P, R]:
        try:
            import streamlit as st

            cached = st.cache_data(
                ttl=ttl,
                max_entries=max_entries,
                show_spinner=False,
            )(function)

            @wraps(function)
            def retry_after_error(*args: P.args, **kwargs: P.kwargs) -> R:
                result = cached(*args, **kwargs)
                # 일시 오류(8초 timeout 등)를 TTL 동안 붙잡아 두면 원인이 사라진 뒤에도 실패가 보인다.
                if getattr(result, "status", None) == "error":
                    try:
                        cached.clear(*args, **kwargs)
                    except Exception:  # 캐시 무효화 실패가 화면 렌더를 막아선 안 된다
                        pass
                return result

            setattr(retry_after_error, "clear", cached.clear)
            return cast(Callable[P, R], retry_after_error)
        except (ImportError, RuntimeError):
            @wraps(function)
            def passthrough(*args: P.args, **kwargs: P.kwargs) -> R:
                return function(*args, **kwargs)

            setattr(passthrough, "clear", lambda: None)
            return passthrough

    return decorator


__all__ = ["cache_data"]
