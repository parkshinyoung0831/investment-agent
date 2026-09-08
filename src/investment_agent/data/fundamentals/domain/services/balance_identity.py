"""자본 범위를 구분해 회계항등식의 비부채 청구권을 계산한다."""
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
    """총자산에서 총부채를 제외한 청구권 합계를 계산한다."""
    common_equity = row.get("common_equity")
    if common_equity is None:
        return None
    scope = str(row.get("common_equity_scope") or UNKNOWN)
    claims = common_equity + (row.get("mezzanine_equity") or 0)
    if scope != STOCKHOLDERS_INCLUDING_NCI:
        claims += row.get("minority_interest_balance") or 0
    if scope == COMMON:
        claims += row.get("preferred_stock") or 0
    return claims
