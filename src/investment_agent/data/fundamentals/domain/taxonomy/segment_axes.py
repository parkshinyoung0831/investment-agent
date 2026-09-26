"""세그먼트 축 분류에 사용하는 표준 축."""
from __future__ import annotations

PRODUCT_AXES: tuple[str, ...] = (
    "srt:ProductOrServiceAxis",
    "us-gaap:ProductOrServiceAxis",
)

GEOGRAPHIC_AXES: tuple[str, ...] = (
    "srt:StatementGeographicalAxis",
    "us-gaap:StatementGeographicalAxis",
)
