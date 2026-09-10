"""매크로 시황 — 시장 레짐과 전 지표를 한 화면에서 읽고, 고른 지표만 파고든다.

Discord `#오늘의-시장` 코어 카드와 **같은 지표 집합·같은 계산·같은 임계 규칙**을 쓴다
(`investment_agent.reporting.macro`의 순수 함수). 카드가 지면 때문에 접는 것 — 전 구간 시계열, 파생지표
원값, 임계 판정 근거 — 을 화면에서 펼친다.

경제지표 발표는 스키마가 분리돼 있으므로 `지표 발표` 페이지에서 따로 다룬다.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from investment_agent.dashboard.calculations import (
    finite_number,
    fear_greed_scale,
    macro_alert_counts,
    macro_change,
    macro_indicator_rows,
    macro_regime,
    macro_sections,
    macro_value_text,
)
from investment_agent.reporting.readers.dashboard import load_macro_window
from investment_agent.dashboard.components.theme import dashboard_palette, plotly_layout
from investment_agent.dashboard.components.ui import (
    SOURCE_CALC,
    SOURCE_DB,
    dataframe,
    detail_layout,
    detail_surface,
    display_number,
    format_time,
    open_detail,
    plot_selection_key,
    page_header,
    result_payload,
    result_status,
    source_note,
    view_selector,
)


_COLORS = dashboard_palette()
PRIMARY = _COLORS.primary
TEXT = _COLORS.text
MUTED = _COLORS.muted
BORDER = _COLORS.border
UP = _COLORS.up
DOWN = _COLORS.down
WARNING = _COLORS.warning
from investment_agent.reporting.services.macro.constants import INVERSE_SERIES


_SELECTED_KEY = "macro_selected_series"
_FILTER_KEY = "macro_alert_filter"
_COLUMNS = 4

# 등급 표시. 색은 텍스트·점에만 쓰고 배경은 칠하지 않는다(DESIGN-system.md 규칙).
_TIER_TEXT = {"alert": "red", "caution": "orange", "watch": "green"}
_TIER_LABEL = {"alert": "위험", "caution": "주의", "watch": "관심"}
# 오르는 게 좋은지 나쁜지가 지표마다 다른 종류는 델타에 색을 입히지 않는다.
_NEUTRAL_KINDS = frozenset({"rate", "spread", "flow", "ratio"})
_FILTERS = ("전체", "위험", "주의", "관심")

# 카드 안의 별도 "상세" 버튼은 없애고, 접근 가능한 네이티브 버튼을 카드 전체에
# 투명하게 덮는다. 그러면 카드·수치·스파크라인 어디를 눌러도 같은 선택 이벤트가 난다.
st.html(
    """
    <style>
    div[class*="st-key-macro_card_"]:not([class*="st-key-macro_card_grid_"]) {
        position: relative !important;
        isolation: isolate;
        cursor: pointer;
    }
    div[class*="st-key-macro_card_"]:not([class*="st-key-macro_card_grid_"]) > div {
        position: relative;
    }
    div[class*="st-key-macro_card_"]:not([class*="st-key-macro_card_grid_"]) [class*="st-key-macro_open_"] {
        position: static !important;
    }
    div[class*="st-key-macro_card_"]:not([class*="st-key-macro_card_grid_"]) [data-testid="stButton"] {
        position: absolute !important;
        inset: 0;
        z-index: 1000 !important;
        display: block !important;
        width: 100% !important;
        height: 100% !important;
        margin: 0 !important;
        pointer-events: auto !important;
    }
    div[class*="st-key-macro_card_"]:not([class*="st-key-macro_card_grid_"]) [data-testid="stButton"] > button {
        position: absolute !important;
        inset: 0 !important;
        width: 100% !important;
        height: 100% !important;
        min-height: 0 !important;
        display: block !important;
        opacity: 0 !important;
        border: 0 !important;
        background: transparent !important;
        cursor: pointer;
    }
    div[class*="st-key-macro_card_"]:not([class*="st-key-macro_card_grid_"]) [data-testid="stButton"] > button:focus-visible {
        opacity: 0 !important;
        outline: 2px solid var(--color-primary, #4b9cff) !important;
        outline-offset: -2px;
    }
    .macro-fear-greed {
        display: grid;
        gap: 0.45rem;
        margin: 0.35rem 0 0.15rem;
    }
    .macro-fear-greed__label {
        color: var(--text-color, #f3f4f6);
        font-size: 0.9rem;
        font-weight: 600;
    }
    .macro-fear-greed__track {
        position: relative;
        height: 0.65rem;
        border-radius: 999px;
        background: linear-gradient(
            to right,
            #c84d59 0% 25%,
            #d89035 25% 45%,
            #858b96 45% 55%,
            #3aa86e 55% 75%,
            #1db477 75% 100%
        );
    }
    .macro-fear-greed__line {
        position: absolute;
        top: -0.25rem;
        width: 1px;
        height: 1.15rem;
        background: rgba(255, 255, 255, 0.82);
        box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.2);
    }
    .macro-fear-greed__marker {
        position: absolute;
        top: -0.35rem;
        width: 3px;
        height: 1.35rem;
        border-radius: 999px;
        background: #ffffff;
        box-shadow: 0 0 0 2px rgba(0, 0, 0, 0.45);
        transform: translateX(-50%);
    }
    </style>
    """
)


def _tier_key(tier: Any) -> str:
    text = str(tier or "")
    for key in _TIER_LABEL:
        if key in text:
            return key
    return ""


def _delta_color(row: dict[str, Any]) -> str:
    if str(row.get("series_id")) in INVERSE_SERIES:
        return "inverse"
    if str(row.get("series_kind")) in _NEUTRAL_KINDS:
        return "off"
    return "normal"


def _select(series_id: str) -> None:
    """같은 카드를 다시 누르면 상세를 닫는다(선택 토글)."""
    st.session_state[_SELECTED_KEY] = (
        None if st.session_state.get(_SELECTED_KEY) == series_id else series_id
    )


def _spark_frame(row: dict[str, Any]) -> pd.DataFrame | None:
    values = [
        value
        for value in (finite_number(item) for item in (row.get("spark") or []))
        if value is not None
    ]
    return pd.DataFrame({"v": values}) if len(values) >= 2 else None


def _render_card(row: dict[str, Any], *, selected: bool) -> None:
    """지표 하나를 카드로 그린다 — 값·변화·스파크라인·보조태그·기준일·등급."""

    series_id = str(row["series_id"])
    tier = _tier_key(row.get("tier"))
    change = macro_change(row)
    freshness = row.get("freshness") or {}
    stale = str(freshness.get("state") or "") == "stale"

    with st.container(border=True, key=f"macro_card_{series_id}"):
        name = str(row.get("name_ko") or series_id)
        label = f"{name} :{_TIER_TEXT[tier]}[●]" if tier else name
        st.metric(
            label,
            macro_value_text(row),
            change["text"] if change["text"] != "—" else None,
            delta_color=_delta_color(row),
            chart_data=_spark_frame(row),
            chart_type="area",
            help=str(row.get("reason") or "") or None,
        )
        tags = " · ".join(row.get("tags") or [])
        st.caption(tags if tags else "특이 신호 없음")
        as_of = str(freshness.get("obs_date") or row.get("obs_date") or "—")
        st.caption(
            f"기준 {as_of}"
            + (f" · :orange[{freshness.get('age_days')}일 지연]" if stale else "")
        )
        st.button(
            f"{name} 상세 닫기" if selected else f"{name} 상세 열기",
            key=f"macro_open_{series_id}",
            type="tertiary",
            width="stretch",
            on_click=_select,
            args=(series_id,),
        )


def _render_grid(rows: list[dict[str, Any]], *, selected_id: str | None) -> None:
    for start in range(0, len(rows), _COLUMNS):
        chunk = rows[start:start + _COLUMNS]
        row_key = "_".join(str(row.get("series_id") or start) for row in chunk)
        with st.container(key=f"macro_card_grid_{row_key}"):
            columns = st.columns(_COLUMNS, gap="small")
            for column, row in zip(columns, chunk):
                with column:
                    _render_card(row, selected=selected_id == row["series_id"])


def _metric_table(row: dict[str, Any]) -> list[dict[str, Any]]:
    """카드가 보조태그로 줄여 쓰는 파생지표의 원값을 전부 편다."""

    labels = {
        "z": "변동 z (수익률 기준)",
        "level_z": "레벨 z (값 기준)",
        "percentile": "역사 백분위 (%)",
        "ma50": "50일 이동평균",
        "ma200": "200일 이동평균",
        "high_52w": "52주 고점",
        "low_52w": "52주 저점",
        "drawdown": "52주 고점 대비",
        "rebound": "52주 저점 대비",
    }
    metrics = row.get("metrics") or {}
    previous = row.get("prev_metrics") or {}
    output: list[dict[str, Any]] = []
    for key, label in labels.items():
        value = finite_number(metrics.get(key))
        if value is None:
            continue
        output.append({"지표": label, "현재": value, "직전 관측": finite_number(previous.get(key))})
    return output


def _map_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """지표 지도용 표. 계산되지 않은 값은 지어내지 않고 그 축에서 제외한다."""

    records: list[dict[str, Any]] = []
    for row in rows:
        metrics = row.get("metrics") or {}
        current = finite_number(row.get("curr"))
        previous = finite_number(row.get("prev_value"))
        change_pct = (
            (current / previous - 1.0) * 100.0
            if current is not None and previous not in (None, 0.0)
            else None
        )
        records.append(
            {
                "series_id": str(row["series_id"]),
                "name": str(row.get("name_ko") or row["series_id"]),
                "tier": _tier_key(row.get("tier")),
                "change_pct": change_pct,
                "drawdown": finite_number(metrics.get("drawdown")),
                "rebound": finite_number(metrics.get("rebound")),
                "reason": str(row.get("reason") or ""),
                "value": macro_value_text(row),
            }
        )
    return pd.DataFrame(records)


def _tier_color(tier: str) -> str:
    return {"alert": DOWN, "caution": WARNING, "watch": UP}.get(tier, PRIMARY)


def _render_change_map(frame: pd.DataFrame, *, key: str) -> str | None:
    """오늘 움직임 순위. 모든 지표가 갖는 값이라 전 지표를 한 축에 세울 수 있다."""

    usable = frame.dropna(subset=["change_pct"]).sort_values("change_pct")
    if usable.empty:
        st.info("직전 관측이 있어 변화율을 계산할 수 있는 지표가 없습니다.")
        return None
    figure = go.Figure(
        go.Bar(
            x=usable["change_pct"],
            y=usable["name"],
            orientation="h",
            marker_color=[_tier_color(tier) for tier in usable["tier"]],
            customdata=usable[["series_id"]].to_numpy(),
            hovertemplate="%{y} %{x:+.2f}%<extra></extra>",
        )
    )
    figure.update_layout(
        **plotly_layout(height=max(360, 22 * len(usable))),
        xaxis_title="직전 관측 대비 변화율 (%)",
        bargap=0.35,
    )
    state = st.plotly_chart(
        figure,
        width="stretch",
        config={"displaylogo": False},
        key=key,
        on_select="rerun",
        selection_mode="points",
    )
    return plot_selection_key(state)


def _render_range_map(frame: pd.DataFrame, *, key: str) -> str | None:
    """52주 범위 안에서의 위치. 고저가 계산된 지표만 올린다."""

    usable = frame.dropna(subset=["drawdown", "rebound"])
    if usable.empty:
        st.info(
            "52주 고저가 계산된 지표가 없습니다. 금리·스프레드는 bp 기준이라 이 지도에 "
            "올리지 않습니다."
        )
        return None
    figure = go.Figure(
        go.Scatter(
            x=usable["rebound"],
            y=usable["drawdown"],
            mode="markers+text",
            text=usable["name"],
            textposition="top center",
            textfont={"size": 10, "color": MUTED},
            marker={
                "size": 13,
                "color": [_tier_color(tier) for tier in usable["tier"]],
                "line": {"width": 1, "color": BORDER},
            },
            customdata=usable[["series_id"]].to_numpy(),
            hovertemplate="%{text}<br>저점 대비 %{x:+.1f}%<br>고점 대비 %{y:+.1f}%<extra></extra>",
        )
    )
    figure.update_layout(
        **plotly_layout(height=520),
        xaxis_title="52주 저점 대비 (%)",
        yaxis_title="52주 고점 대비 (%)",
    )
    state = st.plotly_chart(
        figure,
        width="stretch",
        config={"displaylogo": False},
        key=key,
        on_select="rerun",
        selection_mode="points",
    )
    return plot_selection_key(state)


def _render_detail(row: dict[str, Any]) -> None:
    """선택한 지표 하나만 전 구간 시계열·파생 지표·원자료로 펼친다."""

    series = row.get("series")
    series_id = str(row["series_id"])
    tier = _tier_key(row.get("tier"))

    if detail_surface() != "창":
        heading, close = st.columns([5, 1], vertical_alignment="center")
        heading.markdown(f"**{row.get('name_ko') or series_id} · {series_id}**")
        close.button(
            "닫기",
            key=f"macro_detail_close:{series_id}",
            icon=":material/close:",
            type="tertiary",
            width="stretch",
            on_click=_select,
            args=(series_id,),
        )

    if tier:
        st.warning(
            f"{_TIER_LABEL[tier]} 판정 · {row.get('reason') or '사유 없음'}",
            icon=":material/error:" if tier == "alert" else ":material/warning:",
        )
    else:
        st.caption("현재 임계 판정에 걸린 항목이 없습니다.")

    change = macro_change(row)
    with st.container(horizontal=True, gap="small"):
        st.metric("현재값", macro_value_text(row), change["text"], border=True,
                  delta_color=_delta_color(row))
        st.metric("직전 관측", display_number(row.get("prev_value")), border=True)
        st.metric("관측 수", f"{row.get('observations') or 0}개", border=True)
        st.metric("기준일", str(row.get("obs_date") or "—"), border=True)
    source_note(
        SOURCE_DB,
        SOURCE_CALC,
        observed_at=row.get("obs_date"),
        detail=(
            f"{row.get('category') or '미분류'} · {row.get('series_kind') or '—'} · "
            f"{row.get('frequency') or '—'} · 단위 {row.get('unit') or '—'}"
        ),
    )

    if not isinstance(series, pd.Series) or series.empty:
        st.info("전 구간 시계열을 만들 실제 관측값이 없습니다.")
        return

    detail_view = view_selector(
        "상세 보기",
        ("추세", "파생 지표"),
        key=f"macro_detail_view:{series_id}",
        default="추세",
    )

    if detail_view == "추세":
        figure = go.Figure()
        figure.add_trace(
            go.Scatter(
                x=series.index,
                y=series.to_numpy(),
                name=str(row.get("name_ko") or series_id),
                mode="lines",
                line={"color": PRIMARY, "width": 2},
            )
        )
        metrics = row.get("metrics") or {}
        for key, label, color, dash in (
            ("ma50", "50일선", MUTED, "dot"),
            ("ma200", "200일선", TEXT, "dot"),
            ("high_52w", "52주 고점", BORDER, "dash"),
            ("low_52w", "52주 저점", BORDER, "dash"),
        ):
            level = finite_number(metrics.get(key))
            if level is not None:
                figure.add_hline(y=level, line_dash=dash, line_color=color, annotation_text=label)
        figure.update_layout(**plotly_layout(height=440))
        st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
        source_note(
            SOURCE_DB, SOURCE_CALC,
            observed_at=row.get("obs_date"),
            detail="reporting.macro_observations 최근 400일 · 기준선은 화면에서 계산",
        )
    else:
        table = _metric_table(row)
        if table:
            dataframe(table, key=f"macro_metric_table:{series_id}")
            st.caption(
                "z는 수익률 기준 365일 rolling, 레벨 z는 값 자체 기준입니다. "
                "지표 종류마다 계산되는 항목이 다르며, 계산되지 않은 항목은 표시하지 않습니다."
            )
        else:
            st.info("이 지표 종류에는 계산되는 파생 지표가 없습니다.")
        source_note(SOURCE_CALC, detail="reporting.macro.metrics 계산")


page_header(
    "시장 환경",
    discord=None,
    show_badges=False,
)

window_result = load_macro_window("all")
if not result_status(window_result, empty_text="저장된 매크로 관측값이 없습니다"):
    st.stop()

raw_rows = result_payload(window_result, default=None)
if raw_rows is None:
    raw_rows = window_result.rows
indicators = macro_indicator_rows(raw_rows)
if not indicators:
    st.info("계산 가능한 매크로 지표가 없습니다. 임의 값을 만들지 않습니다.")
    st.stop()

by_series = {str(row["series_id"]): row for row in indicators}
regime = macro_regime(indicators)
counts = macro_alert_counts(indicators)
selected_id = st.session_state.get(_SELECTED_KEY)

# ── 레짐 요약 ─────────────────────────────────────────────────────────────
with st.container(key="macro_overview_grid"):
    regime_column, sentiment_column = st.columns([3, 2], gap="medium")
with regime_column.container(border=True):
    tone = {"up": "green", "down": "red"}.get(regime["tone"], "gray")
    st.markdown(f"#### 시장 레짐 · :{tone}[{regime['verdict']}]")
    st.caption(f"핵심 지표 {regime['evaluated']}개 · 우호 신호와 경계 신호를 함께 반영합니다")
    if regime["supporting"]:
        st.markdown(":green[**위험 선호 근거**] · " + " · ".join(regime["supporting"]))
    if regime["opposing"]:
        st.markdown(":red[**반대 신호**] · " + " · ".join(regime["opposing"]))
    if not regime["supporting"] and not regime["opposing"]:
        st.info("레짐 판정에 쓸 수 있는 지표가 없습니다.")

with sentiment_column.container(border=True):
    fear_greed = by_series.get("FEAR_GREED")
    vix = by_series.get("VIX")
    with st.container(horizontal=True, gap="small"):
        if fear_greed:
            st.metric(
                "공포·탐욕",
                macro_value_text(fear_greed),
                macro_change(fear_greed)["text"],
                chart_data=_spark_frame(fear_greed),
                chart_type="area",
                border=True,
            )
        if vix:
            st.metric(
                "VIX",
                macro_value_text(vix),
                macro_change(vix)["text"],
                delta_color="inverse",
                chart_data=_spark_frame(vix),
                chart_type="area",
                border=True,
            )
    if fear_greed:
        scale = fear_greed_scale(fear_greed.get("curr"))
        if scale is not None:
            value = float(scale["value"])
            position = float(scale["normalized"]) * 100
            st.html(
                f"""
                <div class="macro-fear-greed" role="meter" aria-valuemin="0"
                     aria-valuemax="100" aria-valuenow="{value:.1f}"
                     aria-valuetext="{scale['label']}">
                    <div class="macro-fear-greed__label">
                        {scale['label']} · {value:.1f}/100
                    </div>
                    <div class="macro-fear-greed__track">
                        <span class="macro-fear-greed__line" style="left: 25%"></span>
                        <span class="macro-fear-greed__line" style="left: 45%"></span>
                        <span class="macro-fear-greed__line" style="left: 55%"></span>
                        <span class="macro-fear-greed__line" style="left: 75%"></span>
                        <span class="macro-fear-greed__marker" style="left: {position:.2f}%"></span>
                    </div>
                </div>
                """
            )
    if not fear_greed and not vix:
        st.info("심리 지표의 저장 관측값이 없습니다.")

# ── 경보 필터 ─────────────────────────────────────────────────────────────
alert_filter = view_selector(
    "경보 필터",
    _FILTERS,
    key=_FILTER_KEY,
    default="전체",
    format_func=lambda name: {
        "전체": f"전체 {len(indicators)}",
        "위험": f"🔴 위험 {counts['alert']}",
        "주의": f"🟡 주의 {counts['caution']}",
        "관심": f"🟢 관심 {counts['watch']}",
    }[name],
)
st.caption("임계 판정은 Discord 감시 알림과 같은 규칙입니다. 필터를 바꿔도 새로 조회하지 않습니다.")

listing_mode = view_selector(
    "목록 방식",
    ("카드", "오늘 움직임", "52주 위치"),
    key="macro_listing_mode",
    default="카드",
    format_func=lambda name: {
        "카드": "카드 그리드",
        "오늘 움직임": "지도 · 오늘 움직임",
        "52주 위치": "지도 · 52주 위치",
    }[name],
)
st.caption(
    "지도에서는 **점이나 막대를 클릭**하면 그 지표가 선택됩니다. "
    "선택한 지표의 전체 정보가 창으로 열립니다."
)

surface = detail_surface()
listing, side = detail_layout(surface)

wanted_tier = {"위험": "alert", "주의": "caution", "관심": "watch"}.get(alert_filter)
visible_rows = (
    [row for row in indicators if _tier_key(row.get("tier")) == wanted_tier]
    if wanted_tier
    else list(indicators)
)

with listing:
    if listing_mode != "카드":
        if not visible_rows:
            st.success(f"현재 {alert_filter} 등급에 해당하는 지표가 없습니다.")
        else:
            frame = _map_frame(visible_rows)
            picked = (
                _render_change_map(frame, key="macro_change_map")
                if listing_mode == "오늘 움직임"
                else _render_range_map(frame, key="macro_range_map")
            )
            if picked and picked in by_series and picked != selected_id:
                st.session_state[_SELECTED_KEY] = picked
                selected_id = picked
            source_note(
                SOURCE_DB,
                SOURCE_CALC,
                observed_at=getattr(window_result, "observed_at", None),
                detail="점 색은 경보 등급 · 클릭하면 그 지표만 펼칩니다",
            )
    elif wanted_tier:
        if not visible_rows:
            st.success(f"현재 {alert_filter} 등급에 해당하는 지표가 없습니다.")
        else:
            st.markdown(f"##### {alert_filter} 등급 {len(visible_rows)}개")
            _render_grid(visible_rows, selected_id=selected_id)
    else:
        sections = macro_sections(indicators)
        covered = {row["series_id"] for section in sections for row in section["rows"]}
        for section in sections:
            header, count = st.columns([4, 1], vertical_alignment="bottom")
            header.markdown(f"##### {section['icon']} {section['name']}")
            count.caption(f"{len(section['rows'])}개 지표")
            _render_grid(section["rows"], selected_id=selected_id)

        remaining = [row for row in indicators if row["series_id"] not in covered]
        if remaining:
            alerting = sum(1 for row in remaining if _tier_key(row.get("tier")))
            with st.expander(
                f"감시 지표 {len(remaining)}개 · 임계 통과 {alerting}개 · 통과 시에만 Discord 발송",
                icon=":material/radar:",
                expanded=bool(selected_id and selected_id not in covered),
            ):
                _render_grid(remaining, selected_id=selected_id)

# ── 선택한 지표 상세 ─────────────────────────────────────────────────────
if selected_id and selected_id in by_series:
    selected_row = by_series[selected_id]
    open_detail(
        f"{selected_row.get('name_ko') or selected_id} · {selected_id}",
        lambda: _render_detail(selected_row),
        surface=surface,
        side=side,
        icon=":material/query_stats:",
        on_dismiss=lambda: st.session_state.update({_SELECTED_KEY: None}),
    )
else:
    with (side if side is not None else st.container()):
        st.caption(
            "카드나 그래프를 클릭하면 해당 지표 하나만 펼칩니다. "
            "누르기 전에는 계산하지 않습니다."
        )
        st.caption(f"마지막 관측 기준 · {format_time(getattr(window_result, 'observed_at', None))}")
