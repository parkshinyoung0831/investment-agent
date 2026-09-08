"""세그먼트 축 분류에 사용하는 표준 축과 정책 버전."""
from __future__ import annotations

# 세그먼트 매핑 정책 세대. 기업 전체 재무의 정책 버전과 같은 규칙으로 움직인다
# (`filing_processing.mapping_version`에 남고, 두 계열은 `content_type`으로 갈린다).
SEGMENT_MAPPING_VERSION = "v1"

PRODUCT_AXES: tuple[str, ...] = (
    "srt:ProductOrServiceAxis",
    "us-gaap:ProductOrServiceAxis",
)

GEOGRAPHIC_AXES: tuple[str, ...] = (
    "srt:StatementGeographicalAxis",
    "us-gaap:StatementGeographicalAxis",
)
