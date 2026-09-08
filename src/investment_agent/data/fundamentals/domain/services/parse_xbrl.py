"""SEC XBRL·inline XBRL 문서를 차원이 붙은 숫자 fact로 파싱한다."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from datetime import date
from typing import Any

from lxml import etree

from investment_agent.data.fundamentals.domain.services.classify_dimensions import (
    canonical_segment_dimensions,
    select_segment_axes,
)


def _qname_local(tag: Any) -> str:
    try:
        return etree.QName(tag).localname
    except (TypeError, ValueError):
        return ""


def _qname_namespace(tag: Any) -> str | None:
    try:
        return etree.QName(tag).namespace
    except (TypeError, ValueError):
        return None


def _iter_local(node: etree._Element, local: str) -> Iterable[etree._Element]:
    for child in node.iter():
        if _qname_local(child.tag) == local:
            yield child


def _deep_first_local(node: etree._Element | None, local: str) -> etree._Element | None:
    if node is None:
        return None
    for child in _iter_local(node, local):
        if child is not node:
            return child
    return None


def _text(node: etree._Element | None) -> str | None:
    if node is None:
        return None
    value = "".join(node.itertext()).strip()
    return value or None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _duration_days(start: str | None, end: str | None) -> int | None:
    start_dt = _parse_date(start)
    end_dt = _parse_date(end)
    if not start_dt or not end_dt:
        return None
    return (end_dt - start_dt).days + 1


def _parse_contexts(root: etree._Element) -> dict[str, dict]:
    contexts: dict[str, dict] = {}
    for ctx in _iter_local(root, "context"):
        context_id = ctx.get("id")
        if not context_id:
            continue

        period = _deep_first_local(ctx, "period")
        start = _text(_deep_first_local(period, "startDate"))
        end = _text(_deep_first_local(period, "endDate"))
        instant = _text(_deep_first_local(period, "instant"))
        if end and start:
            info = {
                "period_start": start,
                "period_end": end,
                "is_instant": False,
                "duration_days": _duration_days(start, end),
            }
        elif instant:
            info = {
                "period_start": None,
                "period_end": instant,
                "is_instant": True,
                "duration_days": None,
            }
        else:
            continue

        dimensions: dict[str, str] = {}
        entity = _deep_first_local(ctx, "entity")
        containers = [
            node
            for node in (
                _deep_first_local(entity, "segment"),
                _deep_first_local(ctx, "scenario"),
            )
            if node is not None
        ]
        for container in containers:
            for explicit in _iter_local(container, "explicitMember"):
                axis = explicit.get("dimension")
                member = _text(explicit)
                if axis and member:
                    dimensions[axis] = member
            for typed in _iter_local(container, "typedMember"):
                axis = typed.get("dimension")
                member = _text(typed)
                if axis and member:
                    dimensions[axis] = member

        # 원본 QName 전체를 보존한다. 정규화 결과는 별도 필드에 둔다.
        info["dimensions"] = dimensions
        info["normalized_dimensions"] = canonical_segment_dimensions(dimensions)
        contexts[context_id] = info
    return contexts


def _clean_number(value: str | None) -> float | None:
    if value is None:
        return None
    raw = "".join(value.split()).replace(",", "").replace("$", "")
    if not raw or raw.lower() in {"nan", "inf", "-inf"}:
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("()")
    try:
        parsed = float(raw)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite XBRL numeric value: {raw[:80]}")
    return -parsed if negative else parsed


def _fact_value(fact: etree._Element) -> float | None:
    value = _clean_number(_text(fact))
    if value is None:
        return None
    scale = fact.get("scale")
    if scale not in (None, ""):
        try:
            value *= 10 ** int(scale)
        except ValueError as exc:
            raise ValueError(
                f"invalid XBRL scale {scale!r} for {_qname_local(fact.tag)!r}"
            ) from exc
    if fact.get("sign") == "-":
        value = -abs(value)
    return value


def _concept_qname(root: etree._Element, fact: etree._Element) -> str | None:
    inline_name = fact.get("name") or fact.get("Name")
    if inline_name:
        return inline_name
    if not isinstance(fact.tag, str):
        return None
    local = _qname_local(fact.tag)
    namespace = _qname_namespace(fact.tag)
    if not local:
        return None
    for prefix, ns in (root.nsmap or {}).items():
        if prefix and ns == namespace:
            return f"{prefix}:{local}"
    return local


def _concept_local(root: etree._Element, fact: etree._Element) -> str:
    qname = _concept_qname(root, fact)
    return qname.split(":", 1)[-1] if qname else ""


def _unit_ref(fact: etree._Element) -> str | None:
    return fact.get("unitRef") or fact.get("unitref")


def _context_ref(fact: etree._Element) -> str | None:
    return fact.get("contextRef") or fact.get("contextref")


def _parse_root(document: bytes) -> etree._Element:
    parser = etree.XMLParser(recover=True, huge_tree=True)
    try:
        return etree.fromstring(document, parser=parser)
    except etree.XMLSyntaxError:
        return etree.HTML(document)


def _measure_qname(root: etree._Element, value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if ":" in raw:
        return raw
    namespace = _qname_namespace(root.tag)
    for prefix, uri in (root.nsmap or {}).items():
        if prefix and uri == namespace:
            return f"{prefix}:{raw}"
    return raw


def _parse_units(root: etree._Element) -> dict[str, dict[str, Any]]:
    """XBRL unit definitions in the small shape consumed by the SEC adapter."""
    units: dict[str, dict[str, Any]] = {}
    for unit in _iter_local(root, "unit"):
        unit_id = str(unit.get("id") or "").strip()
        if not unit_id:
            continue
        divide = _deep_first_local(unit, "divide")
        if divide is None:
            measure = _text(_deep_first_local(unit, "measure"))
            units[unit_id] = {
                "type": "simple",
                "measure": _measure_qname(root, measure),
            }
            continue
        numerator = _deep_first_local(divide, "unitNumerator")
        denominator = _deep_first_local(divide, "unitDenominator")
        units[unit_id] = {
            "type": "divide",
            "numerator": [
                value
                for node in _iter_local(numerator, "measure")
                if (value := _measure_qname(root, _text(node)))
            ],
            "denominator": [
                value
                for node in _iter_local(denominator, "measure")
                if (value := _measure_qname(root, _text(node)))
            ],
        }
    return units


def parse_consolidated_numeric_facts(
    document: bytes,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Parse non-dimensioned numeric facts without a runtime XBRL package.

    The return shape deliberately matches the narrow input contract used by
    ``infrastructure.sec.filing_xbrl``. Presentation-linkbase metadata is not
    needed: accepted concepts and units are selected by the project taxonomy,
    while duplicate contexts are ranked deterministically downstream.
    """
    root = _parse_root(document)
    contexts = _parse_contexts(root)
    rows: list[dict[str, Any]] = []
    for fact in root.iter():
        context_id = _context_ref(fact)
        unit_ref = _unit_ref(fact)
        if not context_id or not unit_ref:
            continue
        context = contexts.get(context_id)
        if context is None:
            continue
        value = _fact_value(fact)
        if value is None:
            continue
        concept_qname = _concept_qname(root, fact)
        if not concept_qname:
            continue
        rows.append({
            "concept": concept_qname,
            "numeric_value": value,
            "unit_ref": unit_ref,
            "period_type": "instant" if context["is_instant"] else "duration",
            "period_instant": context["period_end"] if context["is_instant"] else None,
            "period_start": context["period_start"],
            "period_end": context["period_end"],
            "is_dimensioned": bool(context["dimensions"]),
            "decimals": fact.get("decimals"),
            "context_ref": context_id,
            "fact_key": f"{concept_qname}|{context_id}|{unit_ref}",
        })
    return rows, _parse_units(root)


def _period_kind(ctx: dict) -> str:
    if ctx["is_instant"]:
        return "instant"
    days = ctx.get("duration_days")
    if days is None:
        return "other"
    if 60 <= days <= 130:
        return "quarter"
    if 330 <= days <= 380:
        return "annual"
    if 130 < days < 330:
        return "ytd"
    return "other"


def _fiscal_period(period_end: str, period_kind: str) -> str:
    year, month, _ = period_end.split("-")
    if period_kind == "annual":
        return f"{year}FY"
    quarter = (int(month) - 1) // 3 + 1
    if period_kind == "ytd":
        return f"{year}Q{quarter}YTD"
    if period_kind == "instant":
        return f"{year}Q{quarter}I"
    return f"{year}Q{quarter}"


def _dimensions_hash(dimensions: dict[str, str]) -> str:
    payload = json.dumps(dimensions, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _dimension_path(dimensions: dict[str, str]) -> str:
    return " | ".join(f"{axis}={member}" for axis, member in sorted(dimensions.items()))


def parse_segment_facts(
    document: bytes,
    axis_registry: dict[str, dict] | None = None,
) -> list[dict]:
    """사업·제품·지역 축이 붙은 모든 숫자 fact를 반환한다."""
    root = _parse_root(document)
    contexts = _parse_contexts(root)
    rows: list[dict] = []

    for fact in root.iter():
        context_id = _context_ref(fact)
        if not context_id:
            continue
        ctx = contexts.get(context_id)
        if not ctx:
            continue
        primary_axis, secondary_axis = select_segment_axes(ctx["dimensions"], axis_registry)
        if primary_axis is None:
            continue
        unit = _unit_ref(fact)
        if unit is None:
            continue
        value = _fact_value(fact)
        if value is None:
            continue
        concept_qname = _concept_qname(root, fact)
        if not concept_qname:
            continue
        period_kind = _period_kind(ctx)
        period_end = ctx["period_end"]
        row = {
            "context_id": context_id,
            "concept_qname": concept_qname,
            "concept_local": concept_qname.split(":", 1)[-1],
            "axis": primary_axis.axis,
            "member": primary_axis.member,
            "raw_axis": primary_axis.raw_axis,
            "raw_member": primary_axis.raw_member,
            "segment_type": primary_axis.segment_type,
            "classification_method": primary_axis.classification_method,
            "secondary_axis": secondary_axis.axis if secondary_axis else None,
            "secondary_member": secondary_axis.member if secondary_axis else None,
            "depth": 2 if secondary_axis else 1,
            "dimensions": ctx["dimensions"],
            "normalized_dimensions": ctx["normalized_dimensions"],
            "dimensions_hash": _dimensions_hash(ctx["normalized_dimensions"]),
            "dimension_path": _dimension_path(ctx["dimensions"]),
            "period_start": ctx["period_start"],
            "period_end": period_end,
            "duration_days": ctx["duration_days"],
            "is_instant": ctx["is_instant"],
            "period_kind": period_kind,
            "fiscal_period": _fiscal_period(period_end, period_kind),
            "unit": unit,
            "decimals": fact.get("decimals"),
            "scale": fact.get("scale"),
            "value": value,
        }
        rows.append(row)
    return rows


def parse_fiscal_focus(document: bytes) -> tuple[int | None, str | None]:
    """inline XBRL의 fiscal year/period focus를 읽는다."""
    root = _parse_root(document)
    fiscal_year = None
    fiscal_period = None
    for fact in root.iter():
        local = _concept_local(root, fact)
        if local == "DocumentFiscalYearFocus":
            raw_year = str(_text(fact) or "").strip()
            try:
                fiscal_year = int(raw_year)
            except ValueError as exc:
                raise ValueError(
                    f"invalid DocumentFiscalYearFocus: {raw_year!r}"
                ) from exc
        elif local == "DocumentFiscalPeriodFocus":
            value = str(_text(fact) or "").strip().upper()
            if value in {"FY", "Q1", "Q2", "Q3", "Q4"}:
                fiscal_period = value
        if fiscal_year is not None and fiscal_period is not None:
            break
    return fiscal_year, fiscal_period
