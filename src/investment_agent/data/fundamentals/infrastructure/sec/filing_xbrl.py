"""SEC filing 원문의 비차원 us-gaap fact 보조 어댑터."""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from investment_agent.data.fundamentals.domain.filings import FilingRef
from investment_agent.data.fundamentals.domain.services.parse_xbrl import (
    parse_consolidated_numeric_facts,
)
from investment_agent.data.fundamentals.domain.filing import (
    SUPPORTED_STATEMENTS as STATEMENTS,
)
from investment_agent.data.fundamentals.domain.filing import normalize_form
from investment_agent.data.fundamentals.domain.taxonomy import gaap_concepts as concepts


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _duration_quarters(start: date | None, end: date, fiscal_period: str) -> int:
    if start is None:
        return 0
    days = (end - start).days + 1
    quarters = max(1, min(4, round(days / 91.25)))
    if fiscal_period == "FY":
        return 4 if 330 <= days <= 400 else quarters
    return quarters


def _period_is_usable(fiscal_period: str, quarters: int) -> bool:
    allowed = {
        "FY": {0, 4},
        "Q1": {0, 1},
        "Q2": {0, 1, 2},
        "Q3": {0, 1, 3},
        "Q4": {0, 1, 4},
    }
    return quarters in allowed.get(fiscal_period, set())


def _measure_name(value: Any) -> str:
    name = str(value or "").split(":")[-1]
    lowered = name.lower()
    if lowered == "usd":
        return "USD"
    if lowered == "shares":
        return "shares"
    if lowered in {"pure", "number"}:
        return "pure"
    return name


def _normalize_unit(
    unit_ref: Any,
    units: Mapping[str, Any],
) -> str | None:
    ref = str(unit_ref or "")
    definition = units.get(ref) or {}
    if definition.get("type") == "simple":
        return _measure_name(definition.get("measure")) or None
    if definition.get("type") == "divide":
        numerator = [_measure_name(value) for value in definition.get("numerator", [])]
        denominator = [
            _measure_name(value) for value in definition.get("denominator", [])
        ]
        if numerator and denominator:
            return f"{'*'.join(numerator)}/{'*'.join(denominator)}"

    lowered = ref.lower().replace("_", "/").replace("-per-", "/")
    if lowered == "usd":
        return "USD"
    if lowered == "shares":
        return "shares"
    if lowered in {"pure", "number"}:
        return "pure"
    if "usd" in lowered and "share" in lowered:
        return "USD/shares"
    return ref or None


def _precision(value: Any) -> int:
    if str(value).upper() == "INF":
        return 10_000
    try:
        return int(value)
    except (TypeError, ValueError):
        return -10_000


def _statement_rank(value: Any) -> int:
    statement = str(value or "")
    if statement in {"BalanceSheet", "IncomeStatement", "CashFlowStatement"}:
        return 2
    if statement.endswith("Parenthetical"):
        return 1
    return 0


def xbrl_rows_to_facts(
    rows: Iterable[Mapping[str, Any]],
    units: Mapping[str, Any],
    *,
    cik: int | str,
    filing: FilingRef,
    fiscal_year: int,
    fiscal_period: str,
    floor: date,
    allowed_keys: set[str] | frozenset[str] | None = None,
) -> list[dict]:
    """공시 XBRL fact 행을 CompanyFacts와 같은 transient 계약으로 바꾼다."""
    report_date = _to_date(filing.report_date)
    if report_date is None:
        raise ValueError(f"filing has no valid report date: {filing.accession_no}")

    padded_cik = str(cik).zfill(10)
    if not (len(padded_cik) == 10 and padded_cik.isdigit()):
        raise ValueError(f"invalid filing CIK: {cik!r}")
    selected: dict[tuple, tuple[tuple[int, int, str], dict]] = {}
    for row in rows:
        concept_qname = str(row.get("concept") or "")
        if not concept_qname.startswith(("us-gaap:", "us-gaap_")):
            continue
        if bool(row.get("is_dimensioned", False)):
            continue
        raw_tag = concept_qname.split(":", 1)[-1].removeprefix("us-gaap_")
        if concepts.is_excluded_tag(raw_tag):
            continue
        column_key = concepts.to_column_key(raw_tag)
        if column_key is None:
            continue
        if allowed_keys is not None and column_key not in allowed_keys:
            continue

        try:
            value = float(row.get("numeric_value"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue

        period_type = str(row.get("period_type") or "")
        period_end = _to_date(
            row.get("period_instant")
            if period_type == "instant"
            else row.get("period_end")
        )
        if period_end is None or period_end < floor:
            continue
        if abs((period_end - report_date).days) > 31:
            continue
        period_start = (
            _to_date(row.get("period_start")) if period_type == "duration" else None
        )
        quarters = _duration_quarters(period_start, period_end, fiscal_period)
        if not _period_is_usable(fiscal_period, quarters):
            continue

        unit = _normalize_unit(row.get("unit_ref"), units)
        if not concepts.policy_accepts(raw_tag, column_key, unit):
            continue

        key = (
            padded_cik,
            column_key,
            raw_tag,
            unit,
            fiscal_year,
            fiscal_period,
            filing.accession_no,
            quarters,
            period_start.isoformat() if period_start else None,
            period_end.isoformat(),
        )
        fact = {
            "cik": padded_cik,
            "statement": STATEMENTS[0] if quarters == 0 else STATEMENTS[1],
            "concept": raw_tag,
            "standard_tag": concepts.to_standard_tag(raw_tag),
            "column_key": column_key,
            "fiscal_year": fiscal_year,
            "fiscal_period": fiscal_period,
            "qtrs": quarters,
            "form_type": normalize_form(filing.form_type),
            "period_start": period_start.isoformat() if period_start else None,
            "period_end": period_end.isoformat(),
            "value": value,
            "unit": unit,
            "filed_at": filing.filing_date,
            "accession_no": filing.accession_no,
            "is_derived": False,
        }
        rank = (
            _statement_rank(row.get("statement_type")),
            _precision(row.get("decimals")),
            str(row.get("fact_key") or row.get("context_ref") or ""),
        )
        if key not in selected or rank > selected[key][0]:
            selected[key] = (rank, fact)
    return [item[1] for item in selected.values()]


def filing_to_facts(
    cik: int,
    filing: FilingRef,
    *,
    fiscal_year: int,
    fiscal_period: str,
    floor: date,
    allowed_keys: set[str] | frozenset[str] | None = None,
) -> list[dict]:
    """CompanyFacts에 없는 accession만 filing 원문 XBRL에서 읽는다."""
    from investment_agent.data.fundamentals.infrastructure.sec import filing_documents

    document = filing_documents.fetch_xbrl_document(cik, filing.accession_no)
    if document is None:
        raise RuntimeError(f"filing has no XBRL document: {filing.accession_no}")
    rows, units = parse_consolidated_numeric_facts(document)
    facts = xbrl_rows_to_facts(
        rows,
        units,
        cik=cik,
        filing=filing,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        floor=floor,
        allowed_keys=allowed_keys,
    )
    if not facts:
        raise RuntimeError(
            f"filing XBRL has no accepted consolidated facts: {filing.accession_no}"
        )
    return facts
