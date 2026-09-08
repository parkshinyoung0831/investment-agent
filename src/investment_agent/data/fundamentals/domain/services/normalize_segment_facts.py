"""SEC 벌크 segment 차원을 transient fact 형태로 표준화한다."""
from __future__ import annotations

import calendar
import hashlib
import json
import math
from collections import defaultdict
from datetime import date
from typing import Any

from investment_agent.data.fundamentals.domain.services.classify_dimensions import (
    canonical_segment_dimensions,
    select_segment_axes,
)
from investment_agent.data.fundamentals.domain.services.segment_periods import (
    belongs_to_report_period,
)
from investment_agent.data.fundamentals.domain.taxonomy import segment_concepts as concepts
from investment_agent.data.fundamentals.domain.taxonomy.segment_axes import (
    SEGMENT_MAPPING_VERSION as MAPPING_VERSION,
)


def _int_to_date(value: Any) -> date | None:
    try:
        text = str(int(value))
    except (TypeError, ValueError):
        return None
    if len(text) != 8:
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def _to_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _qtrs(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _sub_months(day: date, months: int) -> date:
    year, month = day.year, day.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def parse_dimensions(raw: str | None) -> dict[str, str]:
    """num.segments의 ``Axis=Member;`` 문자열을 원본 QName dict로 바꾼다."""
    out: dict[str, str] = {}
    for part in str(raw or "").strip().strip(";").split(";"):
        if "=" not in part:
            continue
        axis, member = part.split("=", 1)
        axis = axis.strip()
        member = member.strip()
        if axis and member:
            out[axis] = member
    return out


def _dimensions_hash(dimensions: dict[str, str]) -> str:
    payload = json.dumps(dimensions, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _dimension_path(dimensions: dict[str, str]) -> str:
    return " | ".join(f"{axis}={member}" for axis, member in sorted(dimensions.items()))


def _period_is_usable(period_kind: str, qtrs: int) -> bool:
    if period_kind == "annual":
        return qtrs in (0, 4)
    return qtrs in (0, 1)


def bulk_frames_to_filings_and_facts(
    frames,
    *,
    ciks: set[int] | dict[int, object],
    period_kind: str,
    axis_registry: dict[str, dict] | None = None,
    concept_registry: dict[str, dict] | None = None,
) -> tuple[list[dict], dict[str, list[dict]], list[str]]:
    """벌크 sub/num frame을 filing 행과 accession_no별 transient fact로 변환한다.

    세 번째 반환값은 컬럼으로 매핑되지 않아 버려진 concept 이름이다. 이 경로는
    wide 변환 전에 여기서 미매핑 태그를 걸러내므로, 계측을 여기 두지 않으면
    무엇이 얼마나 빠지는지 알 수 없다(사전 보강 판단 근거).
    """
    sub_meta = {
        str(row["adsh"]): row
        for row in frames.sub_df.to_dict("records")
    }
    filings: list[dict] = []
    facts_by_accession: dict[str, list[dict]] = defaultdict(list)

    num = frames.num_df
    if num is None or len(num) == 0:
        return filings, facts_by_accession, []

    segments = num["segments"].fillna("").astype(str).str.strip()
    coreg = num["coreg"].fillna("").astype(str).str.strip()
    selected = num[segments.ne("") & coreg.eq("")].copy()
    if selected.empty:
        return filings, facts_by_accession, []

    tag_map = {
        tag: concepts.to_column_key(str(tag), concept_registry)
        for tag in selected["tag"].unique()
    }
    unmapped = sorted(
        str(tag) for tag, column_key in tag_map.items() if column_key is None
    )
    selected["_column_key"] = selected["tag"].map(tag_map)
    selected = selected[selected["_column_key"].notna()]

    counts: dict[str, int] = defaultdict(int)
    for rec in selected.to_dict("records"):
        accession_no = str(rec["adsh"])
        meta = sub_meta.get(accession_no)
        if meta is None:
            continue

        cik = int(meta["cik"])
        if cik not in ciks:
            continue

        period_end = _int_to_date(rec.get("ddate"))
        filing_end = _int_to_date(meta.get("period"))
        if period_end is None or filing_end is None:
            continue
        qtrs = _qtrs(rec.get("qtrs"))
        if not _period_is_usable(period_kind, qtrs):
            continue
        if not belongs_to_report_period(
            period_end,
            filing_end,
            is_instant=qtrs == 0,
        ):
            continue

        dimensions = parse_dimensions(rec.get("segments"))
        primary_axis, secondary_axis = select_segment_axes(dimensions, axis_registry)
        if primary_axis is None:
            continue

        value = _to_number(rec.get("value"))
        if value is None:
            continue

        try:
            fiscal_year = int(meta.get("fy"))
        except (TypeError, ValueError):
            fiscal_year = period_end.year
        fiscal_period = "FY" if period_kind == "annual" else str(meta.get("fp") or "")
        if fiscal_period not in {"FY", "Q1", "Q2", "Q3", "Q4"}:
            continue

        normalized_dimensions = canonical_segment_dimensions(dimensions)
        dimensions_hash = _dimensions_hash(normalized_dimensions)
        period_start = None if qtrs == 0 else _sub_months(period_end, qtrs * 3).isoformat()
        context_id = hashlib.sha1(
            "|".join(
                (
                    accession_no,
                    str(rec.get("tag") or ""),
                    period_end.isoformat(),
                    str(qtrs),
                    dimensions_hash,
                )
            ).encode("utf-8")
        ).hexdigest()

        fact = {
            "context_id": context_id,
            "concept_qname": str(rec["tag"]),
            "axis": primary_axis.axis,
            "member": primary_axis.member,
            "raw_axis": primary_axis.raw_axis,
            "raw_member": primary_axis.raw_member,
            "segment_type": primary_axis.segment_type,
            "classification_method": primary_axis.classification_method,
            "secondary_axis": secondary_axis.axis if secondary_axis else None,
            "secondary_member": secondary_axis.member if secondary_axis else None,
            "depth": 2 if secondary_axis else 1,
            "dimensions": dimensions,
            "normalized_dimensions": normalized_dimensions,
            "dimensions_hash": dimensions_hash,
            "dimension_path": _dimension_path(dimensions),
            "period_start": period_start,
            "period_end": period_end.isoformat(),
            "duration_days": None,
            "is_instant": qtrs == 0,
            "period_kind": "instant" if qtrs == 0 else period_kind,
            "fiscal_year": fiscal_year,
            "fiscal_period": fiscal_period,
            "period_key": f"{fiscal_year}{fiscal_period}",
            "unit": str(rec.get("uom") or "") or None,
            "value": value,
        }
        facts_by_accession[accession_no].append(fact)
        counts[accession_no] += 1

    for accession_no, meta in sub_meta.items():
        cik = int(meta["cik"])
        if cik not in ciks:
            continue
        report_date = _int_to_date(meta.get("period"))
        filed_date = _int_to_date(meta.get("filed"))
        filings.append({
            "cik": f"{cik:010d}",
            "accession_no": accession_no,
            # sub_df는 load_batch에서 이미 form -> form_type으로 바꿔 온다. 원본
            # 이름으로 읽으면 항상 None이 되고, 빈 문자열은
            # filing_processing form check에 걸려 그 분기 배치 전체가 실패한다.
            "form_type": str(meta.get("form_type") or "") or None,
            "filing_date": filed_date.isoformat() if filed_date else None,
            "report_date": report_date.isoformat() if report_date else None,
            "status": "parsed" if counts.get(accession_no, 0) else "empty",
            "mapping_version": MAPPING_VERSION,
            "source": "backfill_fsds",
            "facts_count": counts[accession_no],
            "rows_count": 0,
        })

    return filings, facts_by_accession, unmapped
