"""원시 매크로 관측치에 붙일 표시 메타데이터 읽기 계약."""
from __future__ import annotations

from typing import Any

from investment_agent.data.macro.domain.catalog import MARKET_INDICATOR_CATALOG


def market_metadata_by_series() -> dict[str, dict[str, Any]]:
    """대시보드·알림이 공통 카탈로그 메타데이터를 series_id로 조회한다."""

    return {
        str(item["series_id"]): dict(item)
        for item in MARKET_INDICATOR_CATALOG
    }


__all__ = ["market_metadata_by_series"]
