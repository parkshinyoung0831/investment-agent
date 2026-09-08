"""재무제표 구조가 실제로 다른 기업 유형의 표시 규칙."""
from __future__ import annotations


PROFILE_LABELS = {
    "corporate": "일반기업",
    "bank": "은행·금융",
    "insurance": "보험",
    "reit": "리츠",
    "utility": "유틸리티",
}


def classify(names: dict | None) -> str:
    """SIC 설명을 보수적으로 다섯 가지 알림 프로필로 분류한다."""
    source = names or {}
    sector = " ".join(
        str(source.get(key) or "") for key in ("sic_industry", "sic_division")
    ).lower()

    if "real estate investment trust" in sector or "reit" in sector:
        return "reit"
    if "insurance" in sector or "surety" in sector:
        return "insurance"
    if any(word in sector for word in (
        "bank", "banking", "savings institution", "credit union",
        "security brokers", "investment advice", "finance services",
    )):
        return "bank"
    if any(word in sector for word in (
        "electric services", "gas distribution", "water supply", "utility",
        "utilities", "power generation", "regulated electric",
    )):
        return "utility"
    return "corporate"


def label(profile: str) -> str:
    return PROFILE_LABELS.get(profile, PROFILE_LABELS["corporate"])


