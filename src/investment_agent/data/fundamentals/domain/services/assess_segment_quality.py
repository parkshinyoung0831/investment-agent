"""세그먼트 지표별 신뢰도를 독립적으로 판정하는 순수 규칙."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from itertools import combinations
from typing import Any

from investment_agent.data.fundamentals.domain.taxonomy.segment_metrics import (
    SEGMENT_METRICS,
    SEGMENT_WIDE_COLUMNS,
)

_KNOWN_TYPES = {"business", "product", "geographic"}
_VERIFIED_MIN = 0.85
_VERIFIED_MAX = 1.15
_PARTIAL_MIN = 0.50
_PARTIAL_MAX = 1.50
_PROFIT_COMPANY_COLUMNS = {
    "gross_profit": "gross_profit",
    "operating_income": "operating_income_loss",
    "pretax_income": "pretax_income_loss",
    "net_income": "net_income",
}


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _company_row(value: Mapping[str, Any] | None) -> dict[str, float]:
    """회사 지표 dict에서 숫자로 해석 가능한 값만 추린다."""

    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): number
        for key, raw in value.items()
        if (number := _number(raw)) is not None
    }


def _metric_method(row: dict, metric: str) -> str:
    methods = row.get("metric_methods") or {}
    if metric in methods:
        return str(methods[metric])
    if metric == "revenue":
        return str(row.get("concept_method") or "unmapped")
    return "unmapped"


def _base_quality(row: dict, metric: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    status = "verified"
    if str(row.get("segment_type")) not in _KNOWN_TYPES:
        status = "unsafe"
        reasons.append("unknown_axis")
    dimension_count = int(row.get("dimension_count") or 0)
    if dimension_count == 2:
        # 2차원(주 축×보조 축)은 분류기가 보조 축까지 명시적으로 뽑아냈을 때만
        # 계층 자식으로 인정한다 — 그 외 cross-tab은 unsafe로 처리한다.
        if not (row.get("secondary_axis") and row.get("secondary_member")):
            status = "unsafe"
            reasons.append("cross_dimension")
    elif dimension_count != 1:
        status = "unsafe"
        reasons.append("cross_dimension")
    if _number(row.get(metric)) is None:
        status = "unsafe"
        reasons.append(f"{metric}_missing")

    classification = str(row.get("classification_method") or "unknown")
    if status != "unsafe" and classification == "heuristic":
        status = "partial"
        reasons.append("heuristic_classification")
    elif status != "unsafe" and classification == "unknown":
        status = "unsafe"
        reasons.append("unknown_classification")

    method = _metric_method(row, metric)
    if status != "unsafe" and method == "candidate":
        status = "partial"
        reasons.append("candidate_concept")
    elif status != "unsafe" and method not in {"override", "edgartools"}:
        status = "unsafe"
        reasons.append("unmapped_concept")
    return status, reasons


def _reference_column(row: dict, metric: str) -> str | None:
    if metric == "profit_loss":
        return _PROFIT_COMPANY_COLUMNS.get(str(row.get("profit_measure_kind") or ""))
    spec = SEGMENT_METRICS[metric]
    return spec.company_column


def _is_subset_sum(candidate_value: float, others: list[tuple[int, float]]) -> bool:
    """후보 금액이 남은 항목 둘 이상의 합과 1% 이내로 일치하는지 본다."""
    tolerance = max(abs(candidate_value) * 0.01, 1.0)
    for size in range(2, len(others) + 1):
        for subset in combinations(others, size):
            if abs(sum(value for _, value in subset) - candidate_value) <= tolerance:
                return True
    return False


# 한 축에서 걷어낼 수 있는 롤업 단계 수. 테슬라 제품 축처럼 3단계(전체 합계 →
# 사업 소계 → 판매/리스 구분)까지 겹치는 사례가 있어 한 번만 빼서는 부족하다.
_MAX_AGGREGATE_REMOVALS = 4


def _overlapping_revenue_aggregates(
    group: list[dict], reference: float | None,
) -> set[int]:
    """부모 합계와 자식 항목이 함께 공시된 경우 수학적으로 확인된 부모만 찾는다.

    오탐을 막기 위해 단일축 양수 매출이 3~12개이고, 전체 합계가 회사 매출의
    150%를 넘으며, 후보가 다른 둘 이상의 합과 1% 이내로 일치하는 경우만 본다.

    롤업이 여러 단계로 겹치면 하나만 빼서는 커버리지가 정상 범위로 돌아오지
    않는다(TSLA 제품 축: 2.82배 → 하나 제거해도 1.84배). 그래서 한 단계씩
    반복해 걷어내고, **최종 커버리지가 정상 범위에 들어올 때만** 결과를
    채택한다. 중간에 멈추면 축 전체가 unsafe로 떨어져 카드에서 사라진다.
    """
    if reference in (None, 0):
        return set()
    eligible = [
        (index, value)
        for index, row in enumerate(group)
        if int(row.get("dimension_count") or 0) == 1
        and (value := _number(row.get("revenue"))) is not None
        and value > 0
    ]
    if not 3 <= len(eligible) <= 12:
        return set()
    total = sum(value for _, value in eligible)
    if total / reference <= _PARTIAL_MAX:
        return set()

    removed: set[int] = set()
    remaining = list(eligible)
    for _ in range(_MAX_AGGREGATE_REMOVALS):
        # 정상 범위에 들어왔다고 멈추면 남은 롤업이 이중 계상된 채로 끝난다.
        # 커버리지가 1.0에 더 가까워질 때만 계속 걷어낸다.
        current_score = abs(total / reference - 1.0)
        best: tuple[float, int, float] | None = None
        for candidate_index, candidate_value in remaining:
            others = [
                (index, value) for index, value in remaining if index != candidate_index
            ]
            if not _is_subset_sum(candidate_value, others):
                continue
            reduced_coverage = (total - candidate_value) / reference
            # 지나치게 깎아 실제 세그먼트까지 지우는 것은 막는다.
            if reduced_coverage < _PARTIAL_MIN:
                continue
            score = abs(reduced_coverage - 1.0)
            if score >= current_score:
                continue
            if best is None or score < best[0]:
                best = (score, candidate_index, candidate_value)
        if best is None:
            break
        _, index, value = best
        removed.add(index)
        remaining = [(i, v) for i, v in remaining if i != index]
        total -= value

    if not removed or not (_PARTIAL_MIN <= total / reference <= _PARTIAL_MAX):
        return set()
    return removed


def assess_rows(
    rows: list[dict],
    company_metrics: dict[tuple[str, int, str], Any],
) -> list[dict]:
    """축별 합계를 회사 재무와 대조하고 지표별 품질 판정을 부착한다.

    ``metric_quality``는 적재 직전 메모리에서만 사용한다. 영구 저장에는 각 핵심
    지표의 상태와 커버리지 비율만 남긴다.
    """
    assessed = [dict(row) for row in rows]
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in assessed:
        key = (
            str(row.get("cik")), int(row.get("fiscal_year")),
            str(row.get("fiscal_period")), str(row.get("period_kind")),
            str(row.get("segment_type")), str(row.get("axis")),
        )
        groups[key].append(row)

    for key, group in groups.items():
        cik, fiscal_year, fiscal_period, _, _, _ = key
        company = _company_row(company_metrics.get((cik, fiscal_year, fiscal_period)))
        profit_kinds = {
            str(row.get("profit_measure_kind"))
            for row in group
            if row.get("profit_loss") is not None and row.get("profit_measure_kind")
        }

        for metric in SEGMENT_WIDE_COLUMNS:
            excluded = (
                _overlapping_revenue_aggregates(
                    group, _number(company.get("revenue"))
                )
                if metric == "revenue" else set()
            )
            contributors = [
                _number(row.get(metric)) or 0.0
                for index, row in enumerate(group)
                if int(row.get("dimension_count") or 0) == 1
                and index not in excluded
            ]
            total = sum(contributors)
            sample = next((row for row in group if row.get(metric) is not None), None)
            reference_column = _reference_column(sample, metric) if sample else None
            reference = _number(company.get(reference_column)) if reference_column else None
            # 합계는 1차원 행만 더한다. cross-tab(2차원)만 있는 group은 더할 것이
            # 없어 total이 0이 되는데, 그건 "커버리지가 0"이 아니라 "잴 수 없다"는
            # 뜻이다. 0을 그대로 쓰면 segment_metrics_coverage_check(> 0)에 걸려
            # 그 배치가 통째로 실패한다.
            if not contributors or reference in (None, 0):
                coverage = None
            else:
                coverage = total / reference
                # 기여 행이 있어도 합이 0이면(전부 0을 보고한 분기) 비율은 0이 된다.
                # 스키마는 양수만 커버리지로 받는다 — 0은 "커버리지 없음"이고 그건
                # NULL이 표현한다. quality_status가 문제 자체는 따로 기록한다.
                if coverage <= 0:
                    coverage = None

            # 2차원 자식(주 축 멤버가 같은 cross-tab 행들)의 합을 그 멤버의 1차원
            # 부모 값과 대조한다. 부모·자식은 이미 같은 (segment_type, axis) group
            # 안에 있다 — 주 축이 곧 이 group의 axis이기 때문이다.
            parent_values: dict[str, float] = {}
            child_sums: dict[str, float] = defaultdict(float)
            child_present: dict[str, bool] = defaultdict(bool)
            for row in group:
                value = _number(row.get(metric))
                if value is None:
                    continue
                member = str(row.get("member"))
                if int(row.get("dimension_count") or 0) == 1:
                    parent_values[member] = value
                elif row.get("secondary_axis") and row.get("secondary_member"):
                    child_sums[member] += value
                    child_present[member] = True

            for index, row in enumerate(group):
                status, reasons = _base_quality(row, metric)
                if index in excluded and status != "unsafe":
                    status = "unsafe"
                    reasons.append("overlapping_aggregate")
                if (
                    metric == "profit_loss"
                    and status != "unsafe"
                    and len(profit_kinds) > 1
                ):
                    status = "unsafe"
                    reasons.append("mixed_profit_definitions")

                dimension_count = int(row.get("dimension_count") or 0)
                if status != "unsafe" and dimension_count == 2:
                    member = str(row.get("member"))
                    parent_value = parent_values.get(member)
                    if parent_value is None:
                        status = "partial"
                        reasons.append("no_dimensional_parent")
                    else:
                        cross_ratio = (
                            child_sums[member] / parent_value
                            if child_present.get(member) and parent_value
                            else None
                        )
                        if cross_ratio is None or not (
                            _VERIFIED_MIN <= cross_ratio <= _VERIFIED_MAX
                        ):
                            reasons.append("cross_dimension_sum_mismatch")
                            status = (
                                "partial"
                                if cross_ratio is not None
                                and _PARTIAL_MIN <= cross_ratio <= _PARTIAL_MAX
                                else "unsafe"
                            )
                elif status != "unsafe":
                    if reference is None:
                        status = "partial"
                        reasons.append("company_metric_missing")
                    elif coverage is None:
                        # reference == 0 — 분모가 0이라 커버리지 비율을 낼 수 없다.
                        # 아래 비교로 흘려보내면 float/None 비교로 터지므로 여기서 끊는다.
                        status = "partial"
                        reasons.append("company_metric_zero")
                    elif not (_VERIFIED_MIN <= coverage <= _VERIFIED_MAX):
                        reasons.append("coverage_outside_verified_range")
                        status = (
                            "partial"
                            if _PARTIAL_MIN <= coverage <= _PARTIAL_MAX
                            else "unsafe"
                        )
                quality = dict(row.get("metric_quality") or {})
                quality[metric] = {
                    "status": status,
                    # 커버리지는 "1차원 분할이 전사 합계를 얼마나 덮는가"라는 group
                    # 단위 값이다. cross-tab 자식 행은 그 분할 *안*의 조각이라 개별
                    # 커버리지가 없고, 등급도 부모 대비 합(cross_ratio)으로 정한다.
                    # 그런 행에 group 값을 붙이면 등급과 커버리지가 서로 다른 근거를
                    # 가리켜, segment_metrics_coverage_check가 매일 실패한다.
                    "coverage_ratio": (
                        coverage if int(row.get("dimension_count") or 0) == 1 else None
                    ),
                    "reasons": reasons,
                    "company_column": reference_column,
                }
                row["metric_quality"] = quality

        for row in group:
            revenue_q = row["metric_quality"]["revenue"]
            row["quality_status"] = revenue_q["status"]
            row["quality_reasons"] = revenue_q["reasons"]
            row["coverage_ratio"] = revenue_q["coverage_ratio"]

            profit_q = row["metric_quality"]["profit_loss"]
            row["profit_quality_status"] = profit_q["status"]
            row["profit_quality_reasons"] = profit_q["reasons"]
            row["profit_coverage_ratio"] = profit_q["coverage_ratio"]

            asset_q = row["metric_quality"]["assets"]
            row["assets_quality_status"] = asset_q["status"]
            row["assets_quality_reasons"] = asset_q["reasons"]
            row["assets_coverage_ratio"] = asset_q["coverage_ratio"]
    return assessed
