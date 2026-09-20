"""환경변수를 숫자·문자열로 읽는 helper.

`.env.example`을 복사하면 `NAME=` 같은 빈 값이 들어온다. `os.environ.get(name, default)`는
빈 문자열을 "설정됨"으로 보고 `int("")`로 죽거나(숫자), 빈 문자열을 그대로 쓴다(날짜).
빈 값은 미설정과 같게 다룬다.
"""
from __future__ import annotations

import os


def env_str(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name}은 정수여야 합니다: {value!r}") from error


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"{name}은 숫자여야 합니다: {value!r}") from error
