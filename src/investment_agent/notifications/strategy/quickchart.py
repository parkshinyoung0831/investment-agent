"""전략 배분 embed에 붙일 QuickChart 도넛 이미지 URL을 조립한다.

여기서 그림을 그리지 않는다 — Chart.js 설정을 URL에 실어 외부 QuickChart가 렌더한다.
전략 알림만 PNG 캡처 대신 embed를 쓰기 때문에 이 경로가 따로 있다.

색은 palette가 SSOT다(DESIGN-system.md):
- 조각은 Brand Blue 하나의 **농도 단계**로 비중 순서를 표현한다. 두 번째 브랜드 색을
  만들지 않는다.
- 방어자산(단기채·채권)만 중립 회색으로 빼서 "파란 면적 = 위험자산"이 바로 읽히게 한다.
- 범례 마커는 원형(rounded.full), 배경은 어두운 표면이라 embed 안에서 카드처럼 얹힌다.
"""
from __future__ import annotations

from investment_agent.notifications.quickchart import build_quickchart_url
from . import palette
from .format import pct, ticker_label


def allocation_chart_url(
    curr_alloc: dict[str, float],
    *,
    width: int = 400,
    height: int = 240,
    legend: bool = True,
) -> str:
    """배분 비중 도넛 이미지 URL. 비중 내림차순으로 색 농도가 짙은 것부터 놓는다."""
    ordered = sorted(curr_alloc.items(), key=lambda kv: (-kv[1], kv[0]))
    chart = {
        "type": "doughnut",
        "data": {
            # 비중을 범례에 함께 적는다 — 조각 안에 숫자를 넣으면 좁은 칸에서 겹친다.
            "labels": [f"{t}  {ticker_label(t)}  {pct(w)}" for t, w in ordered],
            "datasets": [{
                "data": [round(w * 100, 4) for _, w in ordered],
                "backgroundColor": [
                    palette.segment_color(t, rank) for rank, (t, _) in enumerate(ordered)
                ],
                # 조각 사이를 배경색으로 갈라 얇은 틈을 만든다(테두리 색을 따로 두지 않는다).
                "borderColor": palette.SURFACE_DARK_ELEVATED,
                "borderWidth": 3,
            }],
        },
        "options": {
            "cutout": "62%",
            "layout": {"padding": {"top": 14, "bottom": 14, "left": 14, "right": 6}},
            "plugins": {
                "legend": {
                    "display": legend,
                    "position": "right",
                    "labels": {
                        "color": palette.ON_DARK,
                        "usePointStyle": True,
                        "pointStyle": "circle",
                        "boxWidth": 8,
                        "padding": 13,
                        "font": {"size": 13},
                    },
                },
                "datalabels": {"display": False},
            },
        },
    }
    # Discord는 embed 이미지를 약 400px 폭으로 보여준다. 그 크기로 그리되 픽셀비율을 2로
    # 올려, 축소 없이 선명하게 나오도록 한다(축소되면 범례 글자가 뭉갠다).
    return build_quickchart_url(
        chart,
        width=width,
        height=height,
        background=palette.SURFACE_DARK_ELEVATED,
        device_pixel_ratio=2,
    )
