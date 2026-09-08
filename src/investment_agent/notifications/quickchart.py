"""QuickChart 이미지 URL 조립 공통 헬퍼.

Chart.js 설정 딕셔너리를 외부 QuickChart 렌더러가 처리할 수 있는 URL로 인코딩한다.
DESIGN-system.md의 디자인 원칙에 맞춰 배경색, 픽셀 비율(2x)을 일관되게 적용한다.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

_ENDPOINT = "https://quickchart.io/chart"
_CHART_VERSION = "3"


def build_quickchart_url(
    chart: dict[str, Any],
    *,
    width: int,
    height: int,
    background: str | None = None,
    device_pixel_ratio: int = 2,
) -> str:
    """Chart.js 딕셔너리를 QuickChart URL로 인코딩하여 반환한다."""
    encoded = quote(json.dumps(chart, separators=(",", ":"), ensure_ascii=False), safe="")
    url = f"{_ENDPOINT}?v={_CHART_VERSION}&w={width}&h={height}&devicePixelRatio={device_pixel_ratio}"
    if background:
        url += f"&bkg={quote(background, safe='')}"
    url += f"&c={encoded}"
    return url
