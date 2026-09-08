"""기업 재무 유스케이스 계층.

외부 데이터 공급자와 저장소 구현은 ``infrastructure``에, 순수 계산 규칙은
``domain``에 둔다. 이 패키지는 두 계층을 업무 단위로 조합한다.

과거 ``ports``/``builders`` 하위 패키지가 갖던 재수출을 이 파일로 합쳤다
(``use_cases``는 재수출이 없었다). 모듈 파일은 모두 이 패키지 바로 아래
평탄한 구조로 있다.
"""
from __future__ import annotations

from investment_agent.data.fundamentals.domain.normalization import (
    CompanyFinancialBatch,
    build_company_financials,
)
from .filing_sources import (
    CompanyFilingSource,
    EarningsFilingSource,
    SegmentBulkFilingSource,
    SegmentFilingSource,
)
from .market_sources import (
    ConsensusSource,
    PressReleaseDocument,
    PressReleaseSource,
    ReportedEarningsSource,
)
from .repositories import (
    CompanyFinancialRepository,
    EarningsEventRepository,
    ExpectationsRepository,
    SegmentMetricRepository,
)
from .earnings_estimates import ConsensusBatch, build_earnings_estimates
from .earnings_results import build_earnings_results
from .historical_earnings_estimates import build_historical_eps_estimates
from .segment_metrics import SegmentMetricBatch, build_segment_metrics

__all__ = [
    "CompanyFilingSource",
    "CompanyFinancialBatch",
    "CompanyFinancialRepository",
    "ConsensusBatch",
    "ConsensusSource",
    "EarningsEventRepository",
    "EarningsFilingSource",
    "ExpectationsRepository",
    "PressReleaseDocument",
    "PressReleaseSource",
    "ReportedEarningsSource",
    "SegmentBulkFilingSource",
    "SegmentFilingSource",
    "SegmentMetricBatch",
    "SegmentMetricRepository",
    "build_company_financials",
    "build_earnings_estimates",
    "build_earnings_results",
    "build_historical_eps_estimates",
    "build_segment_metrics",
]
