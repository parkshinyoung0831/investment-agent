"""선택적 Streamlit 캐시를 감싸는 플랫폼 데이터 cache decorator."""

from __future__ import annotations

from functools import wraps
from typing import Callable, ParamSpec, TypeVar, cast

P = ParamSpec("P")
R = TypeVar("R")


def cache_data(*, ttl: str | int | float, max_entries: int) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Streamlit이 없는 단위 테스트에서도 import 가능한 제한형 데이터 캐시."""

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
            return cast(Callable[P, R], cached)
        except (ImportError, RuntimeError):
            @wraps(function)
            def passthrough(*args: P.args, **kwargs: P.kwargs) -> R:
                return function(*args, **kwargs)

            setattr(passthrough, "clear", lambda: None)
            return passthrough

    return decorator


__all__ = ["cache_data"]
