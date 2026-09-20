"""체결 결과를 PnL·모듈별 attribution으로 평가하는 거래 성과 계층."""
from __future__ import annotations

from investment_agent.trading.performance.attribution import (
    AttributionReport,
    build_attribution_report,
)

__all__ = [
    "AttributionReport",
    "build_attribution_report",
]
