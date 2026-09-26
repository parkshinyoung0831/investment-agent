"""자본 태그의 포함 범위를 식별하고 회계항등식의 비부채 청구권을 계산한다."""
from __future__ import annotations

from typing import Any

COMMON = "common"
STOCKHOLDERS = "stockholders"
STOCKHOLDERS_INCLUDING_NCI = "stockholders_including_nci"
UNKNOWN = "unknown"

_SCOPE_BY_TAG = {
    "CommonStockholdersEquity": COMMON,
    "StockholdersEquity": STOCKHOLDERS,
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": (
        STOCKHOLDERS_INCLUDING_NCI
    ),
    "PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest": (
        STOCKHOLDERS_INCLUDING_NCI
    ),
    "LimitedLiabilityCompanyLlcMembersEquityIncludingPortionAttributableToNoncontrollingInterest": (
        STOCKHOLDERS_INCLUDING_NCI
    ),
}


def source_scope(row: dict) -> str:
    """선택된 common_equity 태그의 포함 범위를 반환한다."""
    manifest = (row.get("source_manifest") or {}).get("common_equity") or {}
    return _SCOPE_BY_TAG.get(str(manifest.get("raw_tag") or ""), UNKNOWN)


def non_liability_claims(row: dict) -> Any | None:
    """총자산에서 총부채를 제외한 청구권 합계를 계산한다.

    `common_equity`는 보통주 자본으로 정의가 고정돼 있어(우선주·비지배지분 제외) 나머지
    청구권을 모두 더한다. 모르는 구성요소는 0으로 본다 — 보고하지 않은 계정은 대개 없는 것이다.
    """
    common_equity = row.get("common_equity")
    if common_equity is None:
        return None
    return (
        common_equity
        + (row.get("preferred_stock") or 0)
        + (row.get("minority_interest_balance") or 0)
        + (row.get("mezzanine_equity") or 0)
    )


def total_book_equity(row: dict) -> Any | None:
    """장부상 자본 총계 = 보통주 자본 + 우선주 + 비지배지분(영구 자본 전체).

    부채와 견주는 비율(Altman Z의 자본/부채)은 보통주 몫만이 아니라 영구 자본 전체를 본다.
    """
    common_equity = row.get("common_equity")
    if common_equity is None:
        return None
    return (
        common_equity
        + (row.get("preferred_stock") or 0)
        + (row.get("minority_interest_balance") or 0)
    )


def consolidated_net_income(row: dict) -> Any | None:
    """연결 순이익 = 모회사 귀속 순이익 + 비지배지분 순이익.

    현금흐름표의 영업현금흐름은 연결 순이익에서 출발한다. 발생액·현금전환 브릿지처럼 영업현금흐름과
    맞대는 계산은 모회사 귀속분이 아니라 이 값을 써야 비지배지분 몫이 '운전자본'으로 새지 않는다.
    """
    net_income = row.get("net_income")
    if net_income is None:
        return None
    return net_income + (row.get("minority_interest_income") or 0)
