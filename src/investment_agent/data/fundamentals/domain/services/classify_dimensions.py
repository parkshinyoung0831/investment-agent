"""세그먼트 XBRL fact의 축과 멤버를 표준 차원으로 분류한다."""
from __future__ import annotations

import re
from dataclasses import dataclass

from investment_agent.data.fundamentals.domain.taxonomy.segment_axes import (
    GEOGRAPHIC_AXES as GEO_AXES,
)
from investment_agent.data.fundamentals.domain.taxonomy.segment_axes import (
    PRODUCT_AXES,
)

BUSINESS_AXES = (
    "us-gaap:StatementBusinessSegmentsAxis",
    "srt:StatementBusinessSegmentsAxis",
    "us-gaap:BusinessSegmentsAxis",
    "srt:BusinessSegmentsAxis",
    "us-gaap:SegmentsAxis",
    "srt:SegmentsAxis",
    "BusinessSegments",
    "StatementBusinessSegments",
    "Segments",
)

SEGMENT_AXIS_PRIORITY = (
    ("business", BUSINESS_AXES),
    ("product", (*PRODUCT_AXES, "ProductOrService")),
    ("geographic", (*GEO_AXES, "Geographical", "GeographicDistribution")),
)

# 회사별 확장 taxonomy 축을 검토한 뒤 명시적으로 분류할 때 사용한다.
# 키는 namespace와 ``Axis`` 접미사를 제거한 local name이다.
AXIS_TYPE_OVERRIDES: dict[str, str] = {}

_AGGREGATE_MEMBERS = {
    "ProductMember",
    "ProductsMember",
    "ProductOrServiceMember",
    "ProductsAndServicesMember",
    "OperatingSegmentsMember",
    "OperatingSegments",
    "ReportableSegmentsMember",
    "ReportableSegments",
    "BusinessSegmentsMember",
    "BusinessSegments",
    "GeographicAreasMember",
    "GeographicAreas",
}

_AXIS_ALIASES = {
    "StatementBusinessSegments": "BusinessSegments",
    "BusinessSegments": "BusinessSegments",
    "Segments": "BusinessSegments",
    "ProductOrService": "ProductOrService",
    "StatementGeographical": "Geographical",
    "Geographical": "Geographical",
    "GeographicDistribution": "Geographical",
}

_DISPLAY_MEMBER_ALIASES = {
    "IPhone": "iPhone",
    "IPad": "iPad",
    "Service": "Services",
    "WearablesHomeandAccessories": "Wearables, Home & Accessories",
}

# OperatingSegmentsMember는 사업부·지역 축이 어떤 연결 범위에서 공시됐는지를
# 나타내는 qualifier다. 독립된 분석 축으로 세면 실제 단일축 세그먼트도 cross-tab이 된다.
_SCOPE_DIMENSIONS = frozenset({("ConsolidationItems", "OperatingSegments")})


@dataclass(frozen=True)
class SegmentAxis:
    segment_type: str
    axis: str
    member: str
    raw_axis: str
    raw_member: str
    classification_method: str


def local_name(qname: str | None) -> str:
    if not qname:
        return ""
    return qname.split(":", 1)[-1]


def canonical_axis(axis: str | None) -> str:
    value = local_name(axis)
    value = value.removesuffix("Axis")
    return _AXIS_ALIASES.get(value, value)


def canonical_member(member: str | None) -> str:
    value = local_name(member)
    value = value.removesuffix("Member")
    return value


def canonical_segment_dimensions(dimensions: dict[str, str]) -> dict[str, str]:
    """원본 차원을 버리지 않고 축·멤버 local name만 정규화한다."""
    out: dict[str, str] = {}
    for axis, member in dimensions.items():
        canonical = canonical_axis(axis)
        if canonical:
            out[canonical] = canonical_member(member)
    return out


def segment_dimension_count(dimensions: dict[str, str]) -> int:
    """세그먼트 분석에 의미 있는 축 수를 반환한다."""
    return sum(
        (axis, member) not in _SCOPE_DIMENSIONS
        for axis, member in canonical_segment_dimensions(dimensions).items()
    )


def select_segment_axis(
    dimensions: dict[str, str],
    axis_registry: dict[str, dict] | None = None,
) -> SegmentAxis | None:
    """원본 차원에서 대표 축을 고르고 분류 근거를 함께 반환한다."""
    if not dimensions:
        return None
    normalized = canonical_segment_dimensions(dimensions)
    raw_by_axis: dict[str, tuple[str, str]] = {}
    for raw_axis, raw_member in dimensions.items():
        raw_by_axis.setdefault(canonical_axis(raw_axis), (raw_axis, raw_member))

    registry = axis_registry or {}
    registry_matches = [
        (axis, registry[axis]) for axis in sorted(normalized) if axis in registry
    ]
    for axis, rule in registry_matches:
        category = str(rule.get("axis_category") or "unknown")
        if bool(rule.get("is_core")) and bool(rule.get("include_in_revenue_pct")):
            raw_axis, raw_member = raw_by_axis[axis]
            return SegmentAxis(
                category if category in {"business", "product", "geographic"} else "unknown",
                axis,
                normalized[axis],
                raw_axis,
                raw_member,
                "registry",
            )

    if registry_matches and len(registry_matches) == len(normalized):
        axis, _ = registry_matches[0]
        raw_axis, raw_member = raw_by_axis[axis]
        return SegmentAxis(
            "unknown", axis, normalized[axis], raw_axis, raw_member, "registry_excluded"
        )

    for segment_type, axes in SEGMENT_AXIS_PRIORITY:
        for wanted in axes:
            canonical = canonical_axis(wanted)
            if canonical in normalized:
                raw_axis, raw_member = raw_by_axis[canonical]
                return SegmentAxis(
                    segment_type,
                    canonical,
                    normalized[canonical],
                    raw_axis,
                    raw_member,
                    "standard",
                )

    for axis in sorted(normalized):
        override = AXIS_TYPE_OVERRIDES.get(axis)
        if override:
            raw_axis, raw_member = raw_by_axis[axis]
            return SegmentAxis(
                override, axis, normalized[axis], raw_axis, raw_member, "override"
            )

    tokens = (
        ("business", ("segment", "business", "operatingunit", "division", "reportable")),
        ("product", ("product", "service", "revenuecategory", "offering")),
        ("geographic", ("geograph", "country", "region", "territor", "marketarea")),
    )
    for segment_type, needles in tokens:
        for axis in sorted(normalized):
            compact = re.sub(r"[^a-z0-9]", "", axis.lower())
            if any(needle in compact for needle in needles):
                raw_axis, raw_member = raw_by_axis[axis]
                return SegmentAxis(
                    segment_type,
                    axis,
                    normalized[axis],
                    raw_axis,
                    raw_member,
                    "heuristic",
                )

    axis = min(normalized)
    raw_axis, raw_member = raw_by_axis[axis]
    return SegmentAxis(
        "unknown", axis, normalized[axis], raw_axis, raw_member, "unknown"
    )


def select_segment_axes(
    dimensions: dict[str, str],
    axis_registry: dict[str, dict] | None = None,
) -> tuple[SegmentAxis | None, SegmentAxis | None]:
    """세그먼트 축을 최대 2차원까지 분류한다.

    분석 의미가 있는 축(스코프 qualifier 제외)이 정확히 2개면 주 축과 보조
    축을 함께 반환해 지역×제품 같은 교차표를 1차원 부모 아래 계층으로 저장할
    수 있게 한다. 1개 이하거나 3개 이상이면 보조 축은 ``None``이다 — 그 경우
    기존 단일축 선택과 cross_dimension 판정을 그대로 따른다.
    """
    primary = select_segment_axis(dimensions, axis_registry)
    if primary is None or segment_dimension_count(dimensions) != 2:
        return primary, None
    remaining = {
        axis: member for axis, member in dimensions.items() if axis != primary.raw_axis
    }
    secondary = select_segment_axis(remaining, axis_registry)
    return primary, secondary


def display_member_name(member: str | None) -> str:
    """XBRL 멤버 식별자를 카드에서 읽을 수 있는 이름으로 바꾼다."""
    value = canonical_member(member)
    if value in _DISPLAY_MEMBER_ALIASES:
        return _DISPLAY_MEMBER_ALIASES[value]
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", value)
    value = re.sub(r"[_\-]+", " ", value)
    return " ".join(value.split()) or "—"


def is_aggregate_member(member: str | None) -> bool:
    raw = local_name(member)
    return raw in _AGGREGATE_MEMBERS or canonical_member(raw) in _AGGREGATE_MEMBERS
