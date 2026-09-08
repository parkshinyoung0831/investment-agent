"""공시와 회계기간을 식별하는 순수 값 객체."""
from __future__ import annotations

SUPPORTED_FORMS: tuple[str, ...] = ("10-K", "10-Q", "10-K/A", "10-Q/A")
SUPPORTED_STATEMENTS: tuple[str, ...] = ("BS", "IS", "CF")


def normalize_form(form_type: str) -> str:
    """수정 공시 표기를 원 공시 유형으로 정규화한다."""
    return (form_type or "").replace("/A", "").strip()
