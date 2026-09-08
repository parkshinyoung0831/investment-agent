"""거장 13F embed에 붙일 QuickChart 이미지 URL을 조립한다.

여기서 그림을 그리지 않는다 — Chart.js 설정을 URL에 실어 외부 QuickChart가 렌더한다.
색 규칙은 palette가 SSOT다(DESIGN-system.md):

- 조각·막대는 Brand Blue 하나의 **농도 단계**로 순위를 표현한다. 두 번째 브랜드 색을
  만들지 않는다.
- '기타'처럼 개별 판단이 아닌 묶음만 중립 회색으로 빼서, 파란 면적이 곧 확신 있는
  포지션이 되게 한다.
- 색이 구분되지 않아도 정보가 남도록 라벨에 수치를 함께 적는다.
"""
from __future__ import annotations

from investment_agent.notifications.quickchart import build_quickchart_url
from investment_agent.notifications.renderers.text import clip as _clip
from . import format as fmt
from . import palette

# 순위별 파랑 농도. 하한을 0.34까지만 내린다 — 더 내리면 어두운 배경에 묻힌다.
_BLUE_STEPS = (1.00, 0.80, 0.64, 0.50, 0.40, 0.34)
# 도넛은 썸네일(80px)로도 붙는다. 그 크기에서 옅은 파랑은 배경에 묻히고 밝은 회색만
# 도드라져 "파란 면적 = 집중도"가 거꾸로 읽힌다. 그래서 파랑은 높게 유지하고
# '기타' 회색은 배경 쪽으로 물러나게 둔다.
_DONUT_BLUE_STEPS = (1.00, 0.86, 0.74, 0.64, 0.56, 0.50)
_GREY = "rgba(124, 130, 138, 0.38)"   # 묶음('기타') 전용 중립색


def _blue(rank: int, steps: tuple[float, ...] = _BLUE_STEPS) -> str:
    r, g, b = (int(palette.PRIMARY[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {steps[min(rank, len(steps) - 1)]:.2f})"


def _url(chart: dict, *, width: int, height: int) -> str:
    return build_quickchart_url(
        chart,
        width=width,
        height=height,
        background=palette.SURFACE_DARK_ELEVATED,
        device_pixel_ratio=2,
    )


def portfolio_donut(
    rows: list[dict],
    *,
    width: int = 400,
    height: int = 240,
    legend: bool = True,
) -> str | None:
    """Top 보유 + '기타' 도넛. 가운데가 비어 있어 집중도가 링 두께로 읽힌다.

    범례를 켜면 조각마다 종목과 비중이 붙는다 — 색만으로는 어느 조각이 무엇인지
    알 수 없고, 색 대비가 약한 환경에서는 그림이 아무것도 말해 주지 못한다.
    """
    slices = [row for row in rows if fmt.number(row.get("value")) > 0]
    if len(slices) < 2:
        return None
    colors = [
        _GREY if str(row.get("label")) == "기타" else _blue(rank, _DONUT_BLUE_STEPS)
        for rank, row in enumerate(slices)
    ]
    # 범례는 티커가 아니라 회사 이름으로 읽는다(한글 우선, 없으면 영문). 티커만 있으면
    # 그걸 쓴다 — CUSIP만 온 행은 이름이 비어 있을 수 있다.
    labels = [
        " ".join(part for part in (
            _clip(str(row.get("name") or row.get("label") or ""), 16),
            str(row.get("pct") or ""),
        ) if part)
        for row in slices
    ]
    chart = {
        "type": "doughnut",
        "data": {
            "labels": labels,
            "datasets": [{
                "data": [round(fmt.number(row.get("value")) * 100, 4) for row in slices],
                "backgroundColor": colors,
                # 조각 사이를 배경색으로 갈라 얇은 틈을 만든다.
                "borderColor": palette.SURFACE_DARK_ELEVATED,
                "borderWidth": 3,
            }],
        },
        "options": {
            "cutout": "62%",
            "layout": {"padding": {"top": 12, "bottom": 12, "left": 12, "right": 6}},
            "plugins": {
                "legend": {
                    "display": legend,
                    "position": "right",
                    "labels": {
                        "color": palette.ON_DARK,
                        "usePointStyle": True,
                        "pointStyle": "circle",
                        "boxWidth": 8,
                        "padding": 12,
                        "font": {"size": 13},
                    },
                },
                "datalabels": {"display": False},
            },
        },
    }
    return _url(chart, width=width, height=height)


def co_held_bars(rows: list[dict], *, width: int = 400, height: int = 200) -> str | None:
    """여럿이 함께 든 종목의 평균 비중 가로 막대.

    매트릭스는 '이번 분기에 움직인' 종목을 보여주고, 이 막대는 '이미 얼마나 크게 들고
    있는지'를 보여준다 — 둘은 다른 질문에 답한다.
    """
    if not rows:
        return None
    labels = [f"{row['ticker']} · {row['manager_count']}명" for row in rows]
    values = [round(fmt.number(str(row["avg_weight"]).rstrip("%")), 2) for row in rows]
    # 길이는 이미 비중을 나타낸다. 색은 다른 축 — 몇 명이 들었나(합의의 넓이)를 맡는다.
    # 둘을 같은 것에 쓰면 가장 긴 막대가 가장 옅어 보이는 식으로 거꾸로 읽힌다.
    counts = [int(row.get("manager_count") or 0) for row in rows]
    widest = max(counts, default=0)
    colors = [_blue(max(0, widest - count)) for count in counts]
    chart = {
        "type": "bar",
        "data": {
            "labels": labels,
            "datasets": [{
                "data": values,
                "backgroundColor": colors,
                "borderWidth": 0,
                "borderRadius": 3,
            }],
        },
        "options": {
            "indexAxis": "y",
            "layout": {"padding": {"top": 6, "bottom": 6, "left": 6, "right": 14}},
            "plugins": {"legend": {"display": False}, "datalabels": {"display": False}},
            "scales": {
                "x": {
                    # 단위는 축 제목으로 단다. ticks.callback은 JS 함수라 설정이 JSON이
                    # 아니게 되고, 그러면 검증도 못 하고 인코딩도 깨지기 쉽다.
                    "title": {
                        "display": True,
                        "text": "평균 비중 (%)",
                        "color": palette.MUTED_SOFT,
                        "font": {"size": 11},
                    },
                    "grid": {"color": "rgba(255,255,255,0.06)", "drawBorder": False},
                    "ticks": {"color": palette.MUTED_SOFT, "font": {"size": 11}},
                },
                "y": {
                    "grid": {"display": False, "drawBorder": False},
                    "ticks": {"color": palette.ON_DARK, "font": {"size": 12}},
                },
            },
        },
    }
    return _url(chart, width=width, height=height)


