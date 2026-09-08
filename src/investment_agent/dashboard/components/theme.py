"""대시보드 차트가 공유하는 라이트·다크 시맨틱 토큰."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import streamlit as st


ThemeName = Literal["light", "dark"]


@dataclass(frozen=True)
class DashboardPalette:
    """차트와 네이티브 UI가 같은 의미로 쓰는 테마별 색 묶음."""

    name: ThemeName
    background: str
    surface: str
    surface_subtle: str
    surface_elevated: str
    border: str
    border_strong: str
    primary: str
    text: str
    secondary_text: str
    muted: str
    up: str
    down: str
    warning: str
    status_success: str
    status_danger: str
    categorical: tuple[str, ...]


_LIGHT = DashboardPalette(
    name="light",
    background="#F9FAFB",
    surface="#FFFFFF",
    surface_subtle="#F2F4F6",
    surface_elevated="#FFFFFF",
    border="#E5E8EB",
    border_strong="#B0B8C1",
    primary="#3182F6",
    text="#191F28",
    secondary_text="#4E5968",
    muted="#6B7684",
    up="#00875A",
    down="#CF202F",
    warning="#B54708",
    status_success="#00773A",
    status_danger="#D22030",
    categorical=("#3182F6", "#191F28", "#8B95A1", "#64A8FF", "#B0B8C1", "#1B64DA"),
)

_DARK = DashboardPalette(
    name="dark",
    background="#101318",
    surface="#171B22",
    surface_subtle="#202630",
    surface_elevated="#252D38",
    border="#333D4B",
    border_strong="#4E5968",
    primary="#3182F6",
    text="#F2F4F6",
    secondary_text="#B0B8C1",
    muted="#8B95A1",
    up="#05B169",
    down="#FF6673",
    warning="#FFB454",
    status_success="#4FD18B",
    status_danger="#F04452",
    categorical=("#64A8FF", "#F2F4F6", "#8B95A1", "#3182F6", "#B0B8C1", "#1B64DA"),
)


def theme_name() -> ThemeName:
    """현재 Streamlit 테마를 반환하고 테스트 환경에서는 다크를 기본으로 한다."""

    try:
        return "light" if st.context.theme.type == "light" else "dark"
    except (AttributeError, RuntimeError):
        return "dark"


def dashboard_palette(theme: ThemeName | None = None) -> DashboardPalette:
    """현재 또는 명시한 테마의 시맨틱 색을 반환한다."""

    return _LIGHT if (theme or theme_name()) == "light" else _DARK


def plotly_layout(*, height: int = 420, theme: ThemeName | None = None) -> dict[str, object]:
    """모든 Plotly 차트에 공통인 여백·서체·표면·축 스타일을 반환한다."""

    colors = dashboard_palette(theme)
    axis = {
        "gridcolor": colors.border,
        "zerolinecolor": colors.border_strong,
        "linecolor": "rgba(0,0,0,0)",
        "tickfont": {"color": colors.muted},
        "title": {"font": {"color": colors.secondary_text}},
        "automargin": True,
    }
    return {
        "height": height,
        "margin": {"l": 20, "r": 20, "t": 40, "b": 20},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {
            "color": colors.text,
            "family": "Pretendard Variable, Pretendard, Noto Sans KR, sans-serif",
            "size": 13,
        },
        "colorway": list(colors.categorical),
        "hoverlabel": {
            "bgcolor": colors.surface_elevated,
            "bordercolor": colors.border,
            "font": {"color": colors.text, "family": "JetBrains Mono, monospace"},
        },
        "legend": {
            "orientation": "h",
            "y": 1.08,
            "x": 0,
            "font": {"color": colors.secondary_text},
        },
        "xaxis": dict(axis),
        "yaxis": dict(axis),
    }
