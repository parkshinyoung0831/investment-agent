"""edgartools 사전과 작은 승인 예외로 세그먼트 지표를 표준화한다."""
from __future__ import annotations

import re
from typing import Any

from investment_agent.data.fundamentals.domain.services.classify_dimensions import local_name
from investment_agent.data.fundamentals.domain.taxonomy import gaap_concepts as fund_concepts
from investment_agent.data.fundamentals.domain.taxonomy.segment_metrics import SEGMENT_WIDE_COLUMN_SET

# edgartools 표준 태그 중 영구 보존할 핵심 지표만 번역한다. 이익은 정의를 함께
# 저장해 영업이익·순이익·EBITDA 등을 서로 같은 값처럼 섞지 않는다.
_STANDARD_METRICS: dict[str, tuple[str, str | None, str | None]] = {
    "Revenue": ("revenue", None, None),
    "OperatingIncomeLoss": ("profit_loss", "operating_income", "영업이익"),
    "GrossProfit": ("profit_loss", "gross_profit", "매출총이익"),
    "PretaxIncomeLoss": ("profit_loss", "pretax_income", "세전이익"),
    "ProfitLoss": ("profit_loss", "net_income", "순이익"),
    "net_income": ("profit_loss", "net_income", "순이익"),
    "Assets": ("assets", None, "자산"),
}

_RAW_ALIASES: dict[str, tuple[str, str | None, str | None]] = {
    "SegmentProfitLoss": ("profit_loss", "segment_profit", "부문이익"),
    "NetIncomeLoss": ("profit_loss", "net_income", "순이익"),
}

# 이익 정의 -> 표기. 저장은 `profit_measure_kind` 하나만 하고, 라벨은 읽을 때 만든다.
# 같은 사실을 두 컬럼에 넣으면 한쪽만 고쳐질 수 있다.
_PROFIT_MEASURE_LABELS: dict[str, str] = {
    kind: label
    for _, kind, label in (*_STANDARD_METRICS.values(), *_RAW_ALIASES.values())
    if kind and label
}


def profit_measure_label(kind: str | None) -> str:
    """`profit_measure_kind`의 사람이 읽는 이름. 모르는 값은 일반 표기로 돌려준다."""
    return _PROFIT_MEASURE_LABELS.get(str(kind or "").strip(), "부문이익")


_REVENUE_DENY = (
    "deferred", "remainingperformance", "backlog", "receivable",
    "costofrevenue", "tax", "percentage", "pershare",
)


def _compact(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _humanize(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", " ", value).strip()


def _registry_detail(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "column_key": value.get("column_key") if value.get("is_active", True) else None,
            "measure_kind": value.get("measure_kind"),
            "measure_label": value.get("display_label"),
        }
    return {"column_key": value, "measure_kind": None, "measure_label": None}


def _candidate(concept: str) -> tuple[str, str | None, str | None] | None:
    compact = _compact(concept)
    if not any(part in compact for part in _REVENUE_DENY) and (
        compact.endswith(("revenue", "revenues", "sales", "netsales"))
        or "revenuefromexternalcustomer" in compact
    ):
        return "revenue", None, None
    profit_suffixes = (
        ("adjustedebitda", "adjusted_ebitda", "조정 EBITDA"),
        ("ebitda", "ebitda", "EBITDA"),
        ("operatingincome", "operating_income", "영업이익"),
        ("operatingprofit", "operating_income", "영업이익"),
        ("segmentprofitloss", "segment_profit", "부문이익"),
        ("segmentprofit", "segment_profit", "부문이익"),
        ("grossprofit", "gross_profit", "매출총이익"),
        ("pretaxincome", "pretax_income", "세전이익"),
        ("netincome", "net_income", "순이익"),
    )
    for suffix, kind, label in profit_suffixes:
        if compact.endswith(suffix):
            return "profit_loss", kind, label
    return None


def resolve_concept_details(
    concept_qname: str | None,
    concept_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """컬럼·근거·이익 정의를 함께 반환한다."""
    concept = local_name(concept_qname)
    empty = {
        "column_key": None, "method": "unmapped", "measure_kind": None,
        "measure_label": None, "standard_tag": None,
    }
    if not concept:
        return empty
    if concept_registry and concept in concept_registry:
        detail = _registry_detail(concept_registry[concept])
        key = detail["column_key"]
        return {
            **empty,
            **detail,
            "column_key": key if key in SEGMENT_WIDE_COLUMN_SET else None,
            "method": "override",
        }

    standard = fund_concepts.to_standard_tag(concept)
    mapped = _STANDARD_METRICS.get(str(standard)) or _RAW_ALIASES.get(concept)
    if mapped:
        key, kind, label = mapped
        return {
            "column_key": key,
            "method": "edgartools" if standard else "candidate",
            "measure_kind": kind,
            "measure_label": label,
            "standard_tag": standard,
        }
    candidate = _candidate(concept)
    if candidate:
        key, kind, label = candidate
        return {
            "column_key": key,
            "method": "candidate",
            "measure_kind": kind,
            "measure_label": label or _humanize(concept),
            "standard_tag": standard,
        }
    return {**empty, "standard_tag": standard}


def resolve_concept(
    concept_qname: str | None,
    concept_registry: dict[str, Any] | None = None,
) -> tuple[str | None, str]:
    detail = resolve_concept_details(concept_qname, concept_registry)
    return detail["column_key"], detail["method"]


def to_column_key(
    concept_qname: str | None,
    concept_registry: dict[str, Any] | None = None,
) -> str | None:
    return resolve_concept_details(concept_qname, concept_registry)["column_key"]


def concept_rank(
    concept_qname: str | None,
    concept_registry: dict[str, Any] | None = None,
) -> int:
    concept = local_name(concept_qname)
    if concept_registry and concept in concept_registry:
        return -2
    return fund_concepts.concept_rank(concept)


def to_standard_tag(concept_qname: str | None) -> str | None:
    return fund_concepts.to_standard_tag(local_name(concept_qname))
