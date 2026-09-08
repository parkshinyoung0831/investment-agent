"""파싱한 세그먼트 fact를 영구 저장 가능한 지표 wide 행으로 조립한다."""
from __future__ import annotations

import calendar
import hashlib
from datetime import date

from investment_agent.data.fundamentals.domain.services.classify_dimensions import (
    display_member_name,
    is_aggregate_member,
    local_name,
    segment_dimension_count,
)
from investment_agent.data.fundamentals.domain.taxonomy import segment_concepts as concepts
from investment_agent.data.fundamentals.domain.taxonomy.segment_metrics import (
    FLOW_COLUMNS,
    INSTANT_COLUMNS,
    SEGMENT_WIDE_COLUMNS,
    is_compatible,
)

_QUARTER_PERIODS = {"Q1", "Q2", "Q3", "Q4"}


def _parse_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _date_s(value: str | date | None) -> str | None:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else None


def _sub_months(d: date, months: int) -> date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _period_parts(period_end: str, period_kind: str) -> tuple[int, str, str]:
    year_s, month_s, _ = period_end.split("-")
    year = int(year_s)
    if period_kind == "annual":
        return year, "FY", f"{year}FY"
    quarter = (int(month_s) - 1) // 3 + 1
    return year, f"Q{quarter}", f"{year}Q{quarter}"


def _row_period_kind(fact: dict, filing_period_kind: str) -> str | None:
    if fact["period_kind"] in ("quarter", "annual"):
        return fact["period_kind"]
    if fact["period_kind"] == "instant":
        return filing_period_kind
    return None


def _segment_hash(segment_type: str, axis: str, member: str, dimensions_hash: str) -> str:
    payload = f"{segment_type}|{axis}|{member}|{dimensions_hash}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _is_better(candidate: dict, current: dict | None) -> bool:
    if current is None:
        return True
    candidate_rank = int(candidate.get("_rank") or 1_000_000)
    current_rank = int(current.get("_rank") or 1_000_000)
    if candidate_rank != current_rank:
        return candidate_rank < current_rank
    return (
        str(candidate.get("reported_at") or ""),
        str(candidate.get("accession_no") or ""),
    ) > (
        str(current.get("reported_at") or ""),
        str(current.get("accession_no") or ""),
    )


def _drop_aggregate_rows(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        # 지표별 aggregate/specific 공시 여부가 다르므로 서로의 행을 제거하지 않는다.
        key = (
            row["period_key"], row["segment_type"], row["axis"], row["column_key"]
        )
        groups.setdefault(key, []).append(row)

    kept: list[dict] = []
    for group_rows in groups.values():
        has_specific = any(
            not is_aggregate_member(row.get("raw_member") or row["member"])
            for row in group_rows
        )
        if has_specific:
            kept.extend(
                row for row in group_rows
                if not is_aggregate_member(row.get("raw_member") or row["member"])
            )
        else:
            kept.extend(group_rows)
    return kept


def _init_row(
    cik: str,
    filing: dict,
    fact: dict,
    row_period_kind: str,
) -> dict:
    if fact.get("fiscal_year") and fact.get("fiscal_period"):
        fiscal_year = int(fact["fiscal_year"])
        fiscal_period = str(fact["fiscal_period"])
        period_key = str(fact.get("period_key") or f"{fiscal_year}{fiscal_period}")
    else:
        fiscal_year, fiscal_period, period_key = _period_parts(
            fact["period_end"],
            row_period_kind,
        )
    segment_hash = _segment_hash(
        fact["segment_type"],
        fact["axis"],
        fact["member"],
        fact["dimensions_hash"],
    )
    period_end = _parse_date(fact["period_end"])
    period_start = fact.get("period_start")
    if fact["is_instant"]:
        period_start = None
    return {
        "cik": str(cik).zfill(10),
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "period_key": period_key,
        "period_kind": row_period_kind,
        "period_start": _date_s(period_start),
        "period_end": _date_s(period_end),
        "accession_no": filing["accession_no"],
        "segment_hash": segment_hash,
        "segment_type": fact["segment_type"],
        "axis": fact["axis"],
        "member": fact["member"],
        "raw_axis": fact.get("raw_axis") or fact["axis"],
        "raw_member": fact.get("raw_member") or fact["member"],
        "raw_name": f"{fact.get('raw_axis') or fact['axis']}::{fact.get('raw_member') or fact['member']}",
        "display_name": display_member_name(fact.get("raw_member") or fact["member"]),
        "classification_method": fact.get("classification_method") or "unknown",
        "concept_method": fact.get("concept_method") or "unmapped",
        "metric_methods": {},
        "metric_quality": {},
        "profit_measure_kind": None,
        "profit_measure_label": None,
        "dimensions_hash": fact["dimensions_hash"],
        "dimension_path": fact["dimension_path"],
        "dimensions": fact["dimensions"],
        "normalized_dimensions": fact.get("normalized_dimensions") or {},
        # 원본 차원은 보존하되, 공시 범위 qualifier는 분석 축으로 세지 않는다.
        "dimension_count": segment_dimension_count(fact["dimensions"]),
        # 2차원 교차표(주 축×보조 축)의 보조 축. 1차원 fact는 둘 다 None/depth=1이다.
        "secondary_axis": fact.get("secondary_axis"),
        "secondary_member": fact.get("secondary_member"),
        "depth": int(fact.get("depth") or 1),
        "is_derived": False,
        "quality_status": "partial",
        "quality_reasons": ["quality_not_assessed"],
        "coverage_ratio": None,
        "profit_quality_status": "unsafe",
        "profit_quality_reasons": ["profit_missing"],
        "profit_coverage_ratio": None,
        "assets_quality_status": "unsafe",
        "assets_quality_reasons": ["assets_missing"],
        "assets_coverage_ratio": None,
        "source_concepts": {},
        "source_units": {},
        "source_contexts": {},
        **{column: None for column in SEGMENT_WIDE_COLUMNS},
    }


def _build_wide(
    cik: str,
    filing: dict,
    candidates: list[dict],
    concept_registry: dict[str, str | None] | None = None,
) -> list[dict]:
    """column_key·period_kind가 부여된 candidate fact를 wide 행으로 피벗한다."""
    candidates = _drop_aggregate_rows(candidates)
    groups: dict[tuple, dict] = {}
    selected_facts: dict[tuple, dict] = {}

    for fact in candidates:
        row = _init_row(cik, filing, fact, fact["period_kind"])
        group_key = (
            row["cik"],
            row["fiscal_year"],
            row["fiscal_period"],
            row["segment_hash"],
        )
        out = groups.setdefault(group_key, row)

        column_key = fact["column_key"]
        source = {
            "accession_no": filing["accession_no"],
            # reported_at은 저장하지 않지만 동일 concept 경합 시 최신 공시를 고르는
            # 랭킹 기준으로만 쓴다(filing에서 직접 계산).
            "reported_at": filing["accepted_date"] or filing["report_date"],
            "concept_qname": fact["concept_qname"],
            "context_id": fact["context_id"],
            "unit": fact["unit"],
            "value": fact["value"],
            "_rank": concepts.concept_rank(fact["concept_qname"], concept_registry),
        }
        source_key = (*group_key, column_key)
        if not _is_better(source, selected_facts.get(source_key)):
            continue

        selected_facts[source_key] = source
        out[column_key] = float(fact["value"])
        if column_key in FLOW_COLUMNS and not out.get("period_start"):
            out["period_start"] = _date_s(fact.get("period_start"))
        method = fact.get("concept_method") or "unmapped"
        out["metric_methods"][column_key] = method
        # 이 컬럼은 revenue의 concept 근거를 뜻한다(지표별 근거는 metric_methods).
        if column_key == "revenue":
            out["concept_method"] = method
        if column_key == "profit_loss":
            out["profit_measure_kind"] = fact.get("measure_kind")
            out["profit_measure_label"] = fact.get("measure_label") or "부문이익"
        out["source_concepts"][column_key] = fact["concept_qname"]
        out["source_units"][column_key] = fact["unit"]
        out["source_contexts"][column_key] = fact["context_id"]

    rows = []
    for row in groups.values():
        if not any(row.get(column) is not None for column in SEGMENT_WIDE_COLUMNS):
            continue
        rows.append(row)
    return rows


def to_segment_wide_rows(
    cik: str,
    filing: dict,
    facts: list[dict],
    filing_period_kind: str,
    concept_registry: dict[str, str | None] | None = None,
) -> tuple[list[dict], list[str]]:
    """한 공시의 세그먼트 fact를 적재용 wide 행으로 만든다.

    반환값은 ``(rows, unmapped_concepts)``다. 컬럼으로 매핑되지 않는 concept은
    적재되지 않고 사라지는데, 어떤 개념이 얼마나 빠지는지 알 수 없으면 사전
    (``fundamentals.segment_concept_registry``)을 언제 보강해야 하는지 판단할 수 없다.
    호출측 JSON 로그에서 검증 근거를 확인할 수 있게 한다.
    """
    candidates: list[dict] = []
    unmapped: set[str] = set()
    for fact in facts:
        detail = concepts.resolve_concept_details(
            fact.get("concept_qname"), concept_registry
        )
        column_key = detail["column_key"]
        if column_key is None:
            name = local_name(fact.get("concept_qname"))
            if name:
                unmapped.add(name)
            continue
        if not is_compatible(
            column_key,
            str(fact.get("segment_type") or "unknown"),
            str(fact.get("period_kind") or "other"),
        ):
            continue
        period_kind = _row_period_kind(fact, filing_period_kind)
        if period_kind is None:
            continue
        row = dict(fact)
        row["column_key"] = column_key
        row["concept_method"] = detail["method"]
        row["measure_kind"] = detail.get("measure_kind")
        row["measure_label"] = detail.get("measure_label")
        row["period_kind"] = period_kind
        if not row.get("fiscal_year") or not row.get("fiscal_period"):
            row["period_key"] = _period_parts(fact["period_end"], period_kind)[2]
        candidates.append(row)

    return _build_wide(cik, filing, candidates, concept_registry), sorted(unmapped)


def ytd_flow_rows(
    cik: str,
    filing: dict,
    facts: list[dict],
    filing_period_kind: str,
    concept_registry: dict[str, str | None] | None = None,
) -> list[dict]:
    """YTD(누적) flow fact를 분기 차분용 wide 행으로 모은다.

    적재하지 않고 :func:`derive_ytd_quarters` 입력으로만 쓴다. Q2/Q3 누적값만
    대상이며(Q1 누적은 곧 discrete Q1이라 이미 잡힘), 유량 지표만 차분한다.
    """
    if filing_period_kind != "quarter":
        return []

    candidates: list[dict] = []
    for fact in facts:
        if fact.get("period_kind") != "ytd":
            continue
        if str(fact.get("fiscal_period") or "") not in ("Q2", "Q3"):
            continue
        detail = concepts.resolve_concept_details(
            fact.get("concept_qname"), concept_registry
        )
        column_key = detail["column_key"]
        if column_key not in FLOW_COLUMNS or not is_compatible(
            str(column_key),
            str(fact.get("segment_type") or "unknown"),
            "ytd",
        ):
            continue
        row = dict(fact)
        row["column_key"] = column_key
        row["concept_method"] = detail["method"]
        row["measure_kind"] = detail.get("measure_kind")
        row["measure_label"] = detail.get("measure_label")
        row["period_kind"] = "ytd"
        if not row.get("fiscal_year") or not row.get("fiscal_period"):
            continue
        row["period_key"] = f"{int(row['fiscal_year'])}{row['fiscal_period']}"
        candidates.append(row)

    return _build_wide(cik, filing, candidates, concept_registry)


def derive_q4_rows(annual: list[dict], q1: list[dict], q2: list[dict], q3: list[dict]) -> list[dict]:
    """FY 핵심 지표에서 Q4 유량 지표를 파생한다.

    유량(flow)만 ``FY - (Q1+Q2+Q3)``로 차감한다. 자산은 파생하지 않는다.
    """
    q_by_key: dict[tuple, dict] = {}
    for row in [*q1, *q2, *q3]:
        key = (row["segment_type"], row["segment_hash"], row["fiscal_period"])
        q_by_key[key] = row

    derived: list[dict] = []
    for fy in annual:
        year = int(fy["fiscal_year"])
        q_rows = [
            q_by_key.get((fy["segment_type"], fy["segment_hash"], quarter))
            for quarter in ("Q1", "Q2", "Q3")
        ]
        if not all(q_rows):
            continue

        out = dict(fy)
        out.update(
            {
                "fiscal_period": "Q4",
                "period_key": f"{year}Q4",
                "period_kind": "quarter",
                "period_start": _date_s(_sub_months(_parse_date(fy["period_end"]) or date(year, 12, 31), 3)),
                "is_derived": True,
                "source_concepts": {},
                "source_units": {},
                "source_contexts": {},
                # 잔액(instant)은 차감으로 만들 수 없다. FY 행을 통째로 복사해 왔으므로
                # 여기서 비우지 않으면 같은 period_end의 잔액이 FY와 파생 Q4에 두 번 남는다.
                **{column: None for column in INSTANT_COLUMNS},
            }
        )

        any_value = False
        # flow(유량): Q4 = FY - (Q1+Q2+Q3). 분기값이 하나라도 비면 산출 불가.
        for column in FLOW_COLUMNS:
            annual_value = fy.get(column)
            quarter_values = [row.get(column) for row in q_rows if row]
            if column == "profit_loss" and any(
                row.get("profit_measure_kind") != fy.get("profit_measure_kind")
                for row in q_rows if row
            ):
                out[column] = None
                continue
            if annual_value is None or any(value is None for value in quarter_values):
                out[column] = None
                continue
            out[column] = float(annual_value) - sum(float(value) for value in quarter_values)
            any_value = True

        if any_value:
            derived.append(out)
    return derived


def _segment_key(row: dict) -> tuple:
    return (row["segment_type"], row["segment_hash"])

def derive_ytd_quarters(
    ytd_rows: list[dict],
    grouped_stored: dict[tuple, list[dict]],
) -> list[dict]:
    """YTD 행에서 직전 분기를 빼 discrete Q2/Q3를 파생한다.

    ``grouped_stored``는 ``{(CIK, year, fiscal_period): [stored wide rows]}``로,
    이미 적재된 분기 discrete를 담는다. 같은 세그먼트(segment_type·segment_hash)의
    Q1..Q(n-1)을 빼서 Qn 핵심 유량을 만든다. 실제(non-derived)
    discrete Qn이 이미 있으면 건너뛴다.
    """
    order = {"Q2": 2, "Q3": 3}
    pool: dict[tuple, dict] = {}
    for (cik, year, fiscal_period), rows in grouped_stored.items():
        for row in rows:
            pool[(cik, int(year), str(fiscal_period), _segment_key(row))] = row

    derived: list[dict] = []
    # Q2를 먼저 파생해 풀에 넣어야 Q3가 그 값을 직전분기로 쓸 수 있다.
    for ytd in sorted(ytd_rows, key=lambda r: order.get(str(r.get("fiscal_period")), 9)):
        fiscal_period = str(ytd.get("fiscal_period") or "")
        n = order.get(fiscal_period)
        if n is None:
            continue
        cik = str(ytd["cik"])
        year = int(ytd["fiscal_year"])
        seg_key = _segment_key(ytd)

        existing = pool.get((cik, year, fiscal_period, seg_key))
        if existing is not None and not existing.get("is_derived"):
            continue  # 공시된 실제 discrete가 있으면 파생하지 않는다.

        priors = [pool.get((cik, year, f"Q{k}", seg_key)) for k in range(1, n)]
        if not all(priors):
            continue

        out = dict(ytd)
        out.update(
            {
                "period_kind": "quarter",
                "is_derived": True,
                "source_concepts": {},
                "source_units": {},
                "source_contexts": {},
                "period_start": _date_s(
                    _sub_months(_parse_date(ytd["period_end"]) or date(year, 12, 31), 3)
                ),
                # 위와 같은 이유로 YTD에서 파생한 분기도 잔액을 들고 오지 않는다.
                **{column: None for column in INSTANT_COLUMNS},
            }
        )

        any_value = False
        for column in FLOW_COLUMNS:
            ytd_value = ytd.get(column)
            prior_values = [prior.get(column) for prior in priors]
            if column == "profit_loss" and any(
                prior.get("profit_measure_kind") != ytd.get("profit_measure_kind")
                for prior in priors
            ):
                out[column] = None
                continue
            if ytd_value is None or any(value is None for value in prior_values):
                out[column] = None
                continue
            out[column] = float(ytd_value) - sum(float(value) for value in prior_values)
            any_value = True

        if any_value:
            derived.append(out)
            pool[(cik, year, fiscal_period, seg_key)] = out
    return derived
