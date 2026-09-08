"""세그먼트 embed에 붙일 QuickChart 이미지 URL을 조립한다.

여기서 그림을 그리지 않는다 — Chart.js 설정을 URL에 실어 외부 QuickChart가 렌더한다.
세그먼트만 PNG 캡처 대신 embed를 쓰기 때문에 이 경로가 따로 있다.

**도넛과 막대는 취향이 아니라 데이터가 고른다.**
도넛은 조각의 합이 전체라는 주장이다. 축이 verified라 비중을 낼 수 있을 때만 정직하다.
partial 축은 합계를 모르므로 도넛을 그리면 없는 사실을 말하게 된다 → 매출 규모를
가로 막대로 세워 크기만 비교한다.

색 규칙은 palette가 SSOT다(DESIGN-system.md):
- 조각·막대는 Brand Blue 하나의 **농도 단계**로 순위를 표현한다. 두 번째 브랜드 색을
  만들지 않는다.
- '기타'처럼 개별 세그먼트가 아닌 묶음만 중립 회색으로 빼서, 파란 면적이 곧 회사가
  이름 붙여 보고한 사업이 되게 한다.
- 색이 구분되지 않아도 정보가 남도록 범례·축 라벨에 수치를 함께 적는다.
"""
from __future__ import annotations

from investment_agent.notifications.quickchart import build_quickchart_url
from investment_agent.notifications.renderers.text import shorten
from investment_agent.notifications.earnings_report import palette

# 순위별 파랑 농도. 하한을 0.46까지만 내린다 — 더 내리면 어두운 배경에 묻힌다.
_BLUE_STEPS = (1.00, 0.86, 0.74, 0.64, 0.56, 0.50, 0.46)
_GREY = "rgba(124, 130, 138, 0.38)"   # 묶음('기타') 전용 중립색
# 범례·축 라벨 폭. 여기는 이미지 안이라 줄바꿈이 없어 자를 수밖에 없다 — 넘치면
# QuickChart가 조각 그림을 밀어내 도넛이 찌그러진다. 온전한 이름은 아래 표가 낸다.
_LEGEND_NAME_WIDTH = 26
_AXIS_NAME_WIDTH = 26


def _blue(rank: int) -> str:
    r, g, b = (int(palette.PRIMARY[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {_BLUE_STEPS[min(rank, len(_BLUE_STEPS) - 1)]:.2f})"


def _color(row: dict, rank: int) -> str:
    return _GREY if row.get("is_remainder") else _blue(rank)


def _url(chart: dict, *, width: int, height: int) -> str:
    return build_quickchart_url(
        chart,
        width=width,
        height=height,
        background=palette.SURFACE_DARK_ELEVATED,
        device_pixel_ratio=2,
    )


def composition_donut(rows: list[dict], *, width: int = 560, height: int = 300) -> str | None:
    """매출 구성 도넛. 가운데가 비어 있어 집중도가 링 두께로 읽힌다.

    비중을 낼 수 있는 행이 둘 미만이면 원 하나가 되어 정보가 없다 → None.
    """
    slices = [
        row for row in rows
        if row.get("revenue_pct") is not None and float(row["revenue_pct"]) > 0
    ]
    if len(slices) < 2:
        return None
    chart = {
        "type": "doughnut",
        "data": {
            # 조각 안에 숫자를 넣으면 좁은 조각에서 겹친다 → 범례에 이름과 비중을 함께 적는다.
            "labels": [
                f"{shorten(str(row.get('name') or '—'), _LEGEND_NAME_WIDTH)}  "
                f"{float(row['revenue_pct']) * 100:.0f}%"
                for row in slices
            ],
            "datasets": [{
                "data": [round(float(row["revenue_pct"]) * 100, 2) for row in slices],
                "backgroundColor": [_color(row, rank) for rank, row in enumerate(slices)],
                # 조각 사이를 배경색으로 갈라 얇은 틈을 만든다.
                "borderColor": palette.SURFACE_DARK_ELEVATED,
                "borderWidth": 3,
            }],
        },
        "options": {
            "cutout": "60%",
            "layout": {"padding": {"top": 14, "bottom": 14, "left": 14, "right": 6}},
            "plugins": {
                "legend": {
                    "display": True,
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


def revenue_bars(rows: list[dict], *, width: int = 560, height: int = 260) -> str | None:
    """매출 규모 가로 막대 — 비중을 낼 수 없는 축(partial)의 대체 그림.

    합계를 모르니 '전체 중 얼마'는 말하지 않고 '서로 얼마나 큰가'만 말한다.
    """
    bars = [row for row in rows if row.get("revenue") is not None]
    if len(bars) < 2:
        return None
    chart = {
        "type": "bar",
        "data": {
            "labels": [shorten(str(row.get("name") or "—"), _AXIS_NAME_WIDTH) for row in bars],
            "datasets": [{
                "data": [round(float(row["revenue"]) / 1e6, 1) for row in bars],
                "backgroundColor": [_color(row, rank) for rank, row in enumerate(bars)],
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
                        "text": "매출 (백만 달러)",
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


def axis_chart(rows: list[dict]) -> str | None:
    """축 하나의 그림 — 비중을 낼 수 있으면 도넛, 아니면 매출 막대."""
    return composition_donut(rows) or revenue_bars(rows)
