"""세그먼트 핵심 지표를 카드가 그릴 축(axis) 요약으로 접는 순수 변환.

입력은 db.load_segment_highlights()가 읽어 온 fundamentals.segment_metrics 행과 공시 상태,
출력은 (ticker, accession_no, fiscal_year, fiscal_period)별 {status, axes}다. DB에 접근하지
않으므로 픽스처만으로 단위 테스트할 수 있다.

회사가 보고한 축은 전부 싣는다. 사업+제품만 보고하는 회사와 3축을 다 보고하는 회사가
섞여 있어서, 자리 수를 고정하면 어느 쪽이든 축이 비거나 통째로 잘린다.
"""
from __future__ import annotations

from investment_agent.data.fundamentals.domain.taxonomy.segment_concepts import profit_measure_label
from investment_agent.notifications.earnings_report.capital import f

SEGMENT_TYPES = ("business", "product", "geographic")
SEGMENT_TYPE_LABELS = {
    "business": "사업",
    "product": "제품",
    "geographic": "지역",
}
# 축당 표시 행 수. 넘치는 세그먼트는 버리지 않고 '기타 N개'로 합산해 축 합계를 보존한다
# (제품 축은 종목의 절반 가까이가 4개를 넘고, NVDA는 28개까지 간다).
AXIS_LIMIT = 6

_USABLE_QUALITY = ("verified", "partial")


def _usable(row: dict) -> bool:
    """카드에 올릴 수 있는 최소 품질을 갖춘 핵심 세그먼트 행인지."""
    return bool(
        int(row.get("dimension_count", 1) or 0) == 1
        and row.get("segment_type") in SEGMENT_TYPES
        and (
            row.get("quality_status") in _USABLE_QUALITY
            and f(row.get("revenue")) is not None
            or row.get("profit_quality_status") in _USABLE_QUALITY
            and f(row.get("profit_loss")) is not None
        )
    )


def _axis_rank(item: tuple[str, list[dict]]) -> tuple[float, float, int, str]:
    """축 정렬 키 — 검증 수준 우선, 그다음 커버리지가 100%에 가까운 순."""
    axis, axis_rows = item
    verified = sum(
        row.get("quality_status") == "verified"
        or row.get("profit_quality_status") == "verified"
        for row in axis_rows
    )
    partial = sum(
        row.get("quality_status") == "partial"
        or row.get("profit_quality_status") == "partial"
        for row in axis_rows
    )
    status_rank = 0.0 if verified >= 2 else 1.0 if verified else 2.0 if partial else 3.0
    coverage = next(
        (value for value in (f(row.get("coverage_ratio")) for row in axis_rows) if value is not None),
        None,
    )
    distance = abs(coverage - 1.0) if coverage is not None else 999.0
    return status_rank, distance, -len(axis_rows), axis


def _best_axis(current: list[dict], segment_type: str) -> tuple[str, list[dict]] | None:
    """해당 세그먼트 종류 안에서 품질이 가장 좋은 축 하나를 고른다."""
    groups: dict[str, list[dict]] = {}
    for row in current:
        if row.get("segment_type") == segment_type:
            groups.setdefault(str(row.get("axis") or ""), []).append(row)
    return min(groups.items(), key=_axis_rank) if groups else None


def _summarize_axis(
    axis: str,
    candidates: list[dict],
    previous: dict[str, dict],
    *,
    limit: int,
) -> dict:
    """축 하나를 표시 행 + '기타 N개' 합산 행으로 접는다."""
    revenues = [
        f(row.get("revenue")) for row in candidates
        if row.get("quality_status") in _USABLE_QUALITY and f(row.get("revenue")) is not None
    ]
    total = sum(revenues)
    axis_verified = bool(revenues) and all(
        row.get("quality_status") == "verified"
        for row in candidates
        if f(row.get("revenue")) is not None
    )
    coverage = next(
        (f(row.get("coverage_ratio")) for row in candidates if f(row.get("coverage_ratio")) is not None),
        None,
    )
    ordered = sorted(
        candidates,
        key=lambda row: (
            f(row.get("revenue"))
            if f(row.get("revenue")) is not None
            else abs(f(row.get("profit_loss")) or float("-inf"))
        ),
        reverse=True,
    )
    shown = ordered[:limit]
    remainder = ordered[limit:]

    items: list[dict] = []
    for row in shown:
        revenue_status = str(row.get("quality_status") or "unsafe")
        revenue = f(row.get("revenue")) if revenue_status in _USABLE_QUALITY else None
        profit_status = str(row.get("profit_quality_status") or "unsafe")
        profit = f(row.get("profit_loss")) if profit_status in _USABLE_QUALITY else None

        prior = previous.get(str(row.get("segment_hash") or ""))
        prior_revenue = f(prior.get("revenue")) if prior else None
        prior_profit = f(prior.get("profit_loss")) if prior else None
        # 이익 정의가 해마다 바뀌면 YoY가 사과-오렌지 비교가 된다.
        same_profit = bool(prior and prior.get("profit_measure_kind") == row.get("profit_measure_kind"))

        revenue_yoy = (
            revenue / prior_revenue - 1
            if revenue_status == "verified" and prior
            and prior.get("quality_status") == "verified"
            and revenue is not None and prior_revenue not in (None, 0)
            else None
        )
        profit_yoy = (
            profit / prior_profit - 1
            if profit_status == "verified" and prior
            and prior.get("profit_quality_status") == "verified"
            and same_profit and profit is not None and prior_profit not in (None, 0)
            else None
        )
        items.append({
            "name": str(row.get("display_name") or row.get("member") or "—"),
            "segment_hash": str(row.get("segment_hash") or ""),
            "revenue": revenue,
            "revenue_pct": (
                revenue / total
                if axis_verified and revenue_status == "verified"
                and revenue is not None and total > 0 else None
            ),
            "revenue_yoy": revenue_yoy,
            "profit_loss": profit,
            "profit_margin": (
                profit / revenue if profit is not None and revenue not in (None, 0) else None
            ),
            "profit_measure_kind": row.get("profit_measure_kind"),
            "profit_measure_label": profit_measure_label(row.get("profit_measure_kind")),
            "profit_yoy": profit_yoy,
            "quality_status": revenue_status if revenue is not None else profit_status,
            "profit_quality_status": profit_status,
        })

    # 잘린 세그먼트를 버리면 표시된 비중의 합이 축 합계와 어긋나 오해를 부른다. 남은 것들을
    # 한 줄로 합산해 축 100%를 유지한다. YoY는 구성이 해마다 달라져 의미가 없으므로 내지 않는다.
    if remainder:
        rest_revenue = sum(
            value for value in (
                f(row.get("revenue")) for row in remainder
                if row.get("quality_status") in _USABLE_QUALITY
            ) if value is not None
        )
        rest_profits = [
            value for value in (
                f(row.get("profit_loss")) for row in remainder
                if row.get("profit_quality_status") in _USABLE_QUALITY
            ) if value is not None
        ]
        rest_profit = sum(rest_profits) if rest_profits else None
        items.append({
            "name": f"기타 {len(remainder)}개",
            "segment_hash": "",
            "is_remainder": True,
            "revenue": rest_revenue or None,
            "revenue_pct": rest_revenue / total if total > 0 and rest_revenue else None,
            "revenue_yoy": None,
            "profit_loss": rest_profit,
            "profit_margin": (
                rest_profit / rest_revenue if rest_profit is not None and rest_revenue else None
            ),
            "profit_measure_kind": None,
            "profit_measure_label": "합산",
            "profit_yoy": None,
            "quality_status": "partial",
            "profit_quality_status": "partial",
        })

    return {
        "axis": axis,
        "coverage_ratio": coverage,
        "quality_status": "verified" if axis_verified else "partial",
        "member_count": len(ordered),
        "shown_count": len(shown),
        "rows": items,
    }


def _filing_status(states: dict[tuple[str, str], dict], ticker: str, accession_no: str) -> str:
    """fundamentals.filing_processing의 세그먼트 상태를 카드 상태로 접는다."""
    raw = str((states.get((ticker, accession_no)) or {}).get("status") or "")
    if raw in ("empty", "unsupported"):
        return "unsupported"
    if raw in ("processing", "failed"):
        return raw
    return "parsed" if raw == "parsed" else "processing"


def build(
    rows: list[dict],
    targets: set[tuple[str, str, int, str]],
    filing_states: dict[tuple[str, str], dict] | None = None,
) -> dict[tuple[str, str, int, str], dict]:
    """공시 accession_no에 정확히 연결된 카드용 세그먼트 상태를 만든다."""
    states = filing_states or {}
    # accession 색인은 이번 공시의 축을, 회계기간 색인은 전년 동기 비교분을 찾는다.
    by_period: dict[tuple[str, int, str], list[dict]] = {}
    by_accession: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        try:
            key = (str(row["ticker"]), int(row["fiscal_year"]), str(row["fiscal_period"]))
        except (KeyError, TypeError, ValueError):
            continue
        by_period.setdefault(key, []).append(row)
        accession_no = str(row.get("accession_no") or "")
        if accession_no:
            by_accession.setdefault((str(row["ticker"]), accession_no), []).append(row)

    out: dict[tuple[str, str, int, str], dict] = {}
    for ticker, accession_no, fiscal_year, fiscal_period in targets:
        period_kind = "annual" if fiscal_period == "FY" else "quarter"
        status = _filing_status(states, ticker, accession_no)
        if status in ("processing", "unsupported", "failed"):
            out[(ticker, accession_no, fiscal_year, fiscal_period)] = {"status": status, "axes": []}
            continue

        source = by_accession.get((ticker, accession_no), [])
        current = [
            row for row in source
            if int(row.get("fiscal_year") or 0) == fiscal_year
            and str(row.get("fiscal_period") or "") == fiscal_period
            and row.get("period_kind") == period_kind and _usable(row)
        ]
        if not current:
            out[(ticker, accession_no, fiscal_year, fiscal_period)] = {
                "status": "unsafe" if source else "unsupported",
                "axes": [],
            }
            continue

        previous = {
            str(row.get("segment_hash")): row
            for row in by_period.get((ticker, fiscal_year - 1, fiscal_period), [])
            if row.get("period_kind") == period_kind
            and int(row.get("dimension_count", 1) or 0) == 1
            and _usable(row)
        }

        choices: list[tuple[tuple, str, str, list[dict]]] = []
        for type_index, segment_type in enumerate(SEGMENT_TYPES):
            chosen = _best_axis(current, segment_type)
            if chosen:
                axis, candidates = chosen
                status_rank, distance, negative_count, axis_name = _axis_rank((axis, candidates))
                choices.append((
                    (status_rank, type_index, distance, negative_count, axis_name),
                    segment_type,
                    axis,
                    candidates,
                ))
        # 품질이 좋은 축을 앞에 둔다(첫 축이 카드 제목·상태를 대표한다).
        choices.sort(key=lambda item: item[0])

        axes: list[dict] = []
        for _, segment_type, axis_name, axis_rows in choices:
            summary = _summarize_axis(axis_name, axis_rows, previous, limit=AXIS_LIMIT)
            summary["type"] = segment_type
            summary["type_label"] = SEGMENT_TYPE_LABELS[segment_type]
            axes.append(summary)

        out[(ticker, accession_no, fiscal_year, fiscal_period)] = {
            "status": axes[0]["quality_status"],
            "axes": axes,
            "source_accession": next(
                iter(sorted({str(row.get("accession_no")) for row in current if row.get("accession_no")})),
                None,
            ),
        }
    return out
