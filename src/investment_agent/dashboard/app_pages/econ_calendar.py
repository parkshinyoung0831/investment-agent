"""지표 발표 센터 — ECON event의 schedule, forecast, first actual, revision을 읽기 전용으로 표시한다."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from investment_agent.dashboard.calculations import today_kst
from investment_agent.dashboard.components.calendar_grid import CalendarEvent, calendar_weeks, render_calendar_grid
from investment_agent.reporting.readers.dashboard import (
    load_econ_calendar_window,
    load_econ_detail,
    load_econ_recent_results,
    load_econ_series,
    load_econ_series_history,
    load_econ_upcoming,
)
from investment_agent.dashboard.components.theme import dashboard_palette, plotly_layout
from investment_agent.dashboard.components.ui import (
    SOURCE_DB,
    dataframe,
    display_number,
    format_time,
    result_payload,
    result_status,
    source_note,
    view_selector,
)

_COLORS = dashboard_palette()
_SELECTED_KEY = "econ_selected_event_key"
_VIEW_KEY = "econ_release_center_view"
_WEEK_KEY = "econ_release_week_offset"
_MONTH_KEY = "econ_release_month_offset"
_VIEWS = ("주간 캘린더", "월간 캘린더", "지표별 이력")
_CATEGORY = {
    "inflation": "물가",
    "labor": "고용",
    "growth_consumption": "성장·소비",
    "policy_housing": "정책·주택",
    "liquidity_trade_energy": "유동성·무역·에너지",
}


def _query_ready(result: Any) -> bool:
    """정상 빈 조회는 0건이고 연결 실패는 확인 불가다."""
    return getattr(result, "status", "error") in {"ok", "empty"}


def _as_date(value: Any) -> date | None:
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(parsed) else parsed.tz_convert("Asia/Seoul").date()


def _number(row: dict[str, Any], key: str) -> str:
    unit = str(row.get("unit") or "")
    suffix = "%" if unit in {"percent", "percent_annualized", "rate"} else ""
    return display_number(row.get(key), digits=2, suffix=suffix)


def _expected_number(row: dict[str, Any]) -> str:
    """발표 전 기준값을 우선하고, 없을 때 현재 예상값을 보조로 표시한다."""
    keys = (
        (
            "closing_survey_value", "closing_nowcast_value", "closing_own_model_value",
            "survey_value", "nowcast_value", "own_model_value",
        )
        if row.get("latest_actual_value") is not None
        else ("survey_value", "nowcast_value", "own_model_value")
    )
    for key in keys:
        if row.get(key) is not None:
            return _number(row, key)
    return "—"


def _revision_number(row: dict[str, Any]) -> str:
    """개정은 최초값 대비 변화폭이므로 비율 지표에서 %p로 표시한다."""
    value = row.get("revision")
    if value is None:
        return "—"
    rendered = _number(row, "revision")
    return rendered.replace("%", "%p") if rendered != "—" else rendered


def _korean_time(value: Any) -> str:
    return format_time(value) if value else "—"


def _country_emoji(value: Any) -> str:
    return {"US": "🇺🇸", "KR": "🇰🇷"}.get(str(value or "").upper(), "🌐")


def _schedule_description(row: dict[str, Any]) -> str:
    confidence = str(row.get("schedule_confidence") or "").lower()
    precision = str(row.get("first_actual_precision") or "").lower()
    confidence_label = {
        "rule": "일정 규칙", "official": "공식 일정", "estimated": "예상 일정", "exact": "정확한 시각",
        "date_only": "날짜만 확인",
    }.get(confidence, confidence)
    precision_label = {"date_only": "날짜만 확인", "exact": "정확한 시각", "collector_seen": "수집 시각 기준"}.get(precision)
    labels = [item for item in (confidence_label, precision_label) if item]
    return " · ".join(dict.fromkeys(labels)) or "—"


def _set_selected(event_key: str) -> None:
    st.session_state[_SELECTED_KEY] = event_key


def _event_card(row: dict[str, Any], *, show_button: bool = True) -> None:
    """상회/하회를 투자 긍정·부정 색으로 해석하지 않는 compact event card."""
    event_key = str(row["event_key"])
    with st.container(border=True):
        st.markdown(f"**{row.get('series_name_ko') or row['series_id']} · {row.get('measure_name_ko') or row.get('measure_id')}**")
        st.caption(
            f"{_country_emoji(row.get('country'))} · {_CATEGORY.get(str(row.get('category')), str(row.get('category') or '—'))} · "
            f"{_korean_time(row.get('scheduled_at'))} · {_schedule_description(row)}"
        )
        actual = row.get("latest_actual_value")
        if actual is None:
            cols = st.columns(3)
            cols[0].metric("시장 예상", _number(row, "survey_value"))
            cols[1].metric("현재 추정", _number(row, "nowcast_value"))
            cols[2].metric("자체 모델", _number(row, "own_model_value"))
        else:
            cols = st.columns(4)
            actual_value = row.get("first_actual_value")
            if actual_value is None:
                actual_value = row.get("latest_actual_value")
            cols[0].metric("실제값", _number({**row, "actual_value": actual_value}, "actual_value"))
            expected_value = _expected_number(row)
            cols[1].metric("예상값", expected_value)
            cols[2].metric("서프라이즈", _number(row, "market_surprise"))
            revision_value = _revision_number(row)
            cols[3].metric("개정폭", "개정 없음" if revision_value in {"0.00%p", "0.00"} else revision_value)
            if row.get("is_surprise_eligible") is False:
                st.caption("원자료 계산값과 공식 헤드라인 정의가 검증되지 않아 시장 서프라이즈는 표시하지 않아요.")
        if show_button:
            st.button("상세", key=f"econ_detail_{event_key}", on_click=_set_selected, args=(event_key,))


def _window_for_week(today: date) -> tuple[datetime, datetime, str]:
    offset = int(st.session_state.get(_WEEK_KEY, 0))
    sunday = today - timedelta(days=(today.weekday() + 1) % 7) + timedelta(days=7 * offset)
    start = datetime.combine(sunday, datetime.min.time(), tzinfo=ZoneInfo("Asia/Seoul"))
    # 달력 주의 기준인 일요일을 그 달의 첫 일요일과 비교해 주차를 계산한다.
    first_sunday = date(sunday.year, sunday.month, 1)
    first_sunday -= timedelta(days=(first_sunday.weekday() + 1) % 7)
    week_number = ((sunday - first_sunday).days // 7) + 1
    return start, start + timedelta(days=7), f"{sunday.year}년 {sunday.month}월 {week_number}주차"


def _window_for_month(today: date) -> tuple[datetime, datetime, str]:
    offset = int(st.session_state.get(_MONTH_KEY, 0))
    month_index = today.year * 12 + today.month - 1 + offset
    year, zero_month = divmod(month_index, 12)
    start_day = date(year, zero_month + 1, 1)
    end_day = date(year, zero_month + 1, calendar.monthrange(year, zero_month + 1)[1]) + timedelta(days=1)
    return (
        datetime.combine(start_day, datetime.min.time(), tzinfo=ZoneInfo("Asia/Seoul")),
        datetime.combine(end_day, datetime.min.time(), tzinfo=ZoneInfo("Asia/Seoul")),
        f"{year}년 {zero_month + 1}월",
    )


def _calendar_query_window(start: datetime, end: datetime, *, is_month: bool) -> tuple[datetime, datetime]:
    """월간 격자의 앞·뒤 달 날짜까지 함께 조회해 실제 일정은 숨기지 않는다."""
    if not is_month:
        return start, end
    weeks = calendar_weeks(start.date(), end.date())
    return (
        datetime.combine(weeks[0][0], datetime.min.time(), tzinfo=start.tzinfo),
        datetime.combine(weeks[-1][-1] + timedelta(days=1), datetime.min.time(), tzinfo=end.tzinfo),
    )


def _render_calendar(
    rows: list[dict[str, Any]], *, start: datetime, end: datetime, title: str,
    is_month: bool = False, is_available: bool = True,
) -> list[dict[str, Any]]:
    st.subheader(title)
    # Calendar의 grain은 family release 하나다. DB function은 primary measure만
    # 반환하지만, future view 변경/partial fixture가 같은 release를 중복해도 UI
    # widget key 충돌이나 여러 카드 표시로 이어지지 않게 방어한다.
    event_rows = {
        str(row["event_key"]): row
        for row in rows
        if row.get("event_key")
    }
    visible = list(event_rows.values())
    grid_days = {grid_day for week in calendar_weeks(start.date(), end.date()) for grid_day in week}
    events = []
    for row in visible:
        day = _as_date(row.get("scheduled_at"))
        if day is None or day not in grid_days:
            continue
        timestamp = pd.to_datetime(row["scheduled_at"], utc=True).tz_convert("Asia/Seoul")
        confidence = str(row.get("schedule_confidence") or "미확인")
        if row.get("survey_value") is not None:
            expected_key = "survey_value"
        elif row.get("nowcast_value") is not None:
            expected_key = "nowcast_value"
        elif row.get("own_model_value") is not None:
            expected_key = "own_model_value"
        else:
            expected_key = "survey_value"
        events.append(CalendarEvent(
            key=str(row["event_key"]), day=day,
            title=str(row.get("series_name_ko") or row.get("series_id") or "지표"),
            country=str(row.get("country") or ""),
            category=str(row.get("category") or ""),
            time_label=timestamp.strftime("%H:%M") if confidence == "exact" else "시각 미정",
            status="발표됨" if row.get("latest_actual_value") is not None else "예정",
            caption=f"{row.get('country') or '—'} · " + {"exact": "확정 시각", "rule": "규칙 기반 예상", "date_only": "날짜만 확인"}.get(confidence, "일정 확정도 미확인"),
            expected_label="예상",
            expected_value=_number(row, expected_key),
            actual_value=_number(row, "first_actual_value" if row.get("first_actual_value") is not None else "latest_actual_value"),
        ))
    visible_keys = {event.key for event in events}
    if st.session_state.get(_SELECTED_KEY) not in visible_keys:
        st.session_state.pop(_SELECTED_KEY, None)
    # 넓은 화면은 상단 요일 기준선, 좁은 화면은 카드 안 요일을 사용한다.
    render_calendar_grid(events, start=start.date(), end=end.date(), today=today_kst(),
                         key="econ", on_select=_set_selected,
                         selected=st.session_state.get(_SELECTED_KEY),
                         is_month=is_month, is_available=is_available)
    return [row for row in visible if str(row["event_key"]) in visible_keys]


def _render_detail(event_key: str) -> None:
    detail = load_econ_detail(event_key)
    if not result_status(detail, empty_text="이 발표의 forecast·actual 이력이 없습니다"):
        return
    payload = result_payload(detail, default={})
    forecasts = list(payload.get("forecasts") or [])
    actuals = list(payload.get("actuals") or [])
    st.markdown("#### 값 이력")
    st.caption(f"발표 · {event_key}")
    # 작은 모달에서는 두 표를 나란히 두면 열이 지나치게 좁아진다.
    # 세로로 쌓아 모바일에서도 각 열을 읽고 가로 스크롤할 수 있게 한다.
    st.markdown("##### 예상값 이력")
    if forecasts:
        frame = pd.DataFrame(forecasts)
        dataframe(frame[["measure_id", "forecast_kind", "source", "value", "as_of", "collected_at"]])
    else:
        st.caption("—")
    st.markdown("##### 실제값·개정 이력")
    if actuals:
        frame = pd.DataFrame(actuals)
        dataframe(frame[["measure_id", "value", "effective_at", "collected_at", "time_precision"]])
    else:
        st.caption("—")
    source_note(SOURCE_DB, detail="원출처 시각과 실제 수집 시각을 구분합니다. 과거 빈티지는 나중에 수집될 수 있습니다.")


@st.dialog("발표 상세", width="small")
def _show_selected_dialog(event_key: str, row: dict[str, Any]) -> None:
    """선택한 발표를 캘린더 아래에 추가하지 않고 작은 모달로 표시한다."""
    # 닫기 버튼을 먼저 처리해야 모달 fragment가 다시 그려질 때도
    # 상세 조회를 한 번 더 호출하지 않고 즉시 종료할 수 있다.
    if st.button("닫기", key="econ_close_detail", width="content"):
        st.session_state.pop(_SELECTED_KEY, None)
        st.rerun()
    _event_card(row, show_button=False)
    _render_detail(event_key)


def _render_series_history() -> None:
    master = load_econ_series()
    if not result_status(master, empty_text="ECON master가 없습니다"):
        return
    payload = result_payload(master, default={})
    series = list(payload.get("series") or [])
    enabled = [row for row in series if row.get("is_enabled")]
    if not enabled:
        st.info("활성 ECON family가 없습니다.")
        return
    ids = [str(row["series_id"]) for row in enabled]
    selected = st.selectbox(
        "경제지표 선택", ids,
        format_func=lambda sid: next(
            (f"{row.get('name_ko')} ({sid})" for row in enabled if row["series_id"] == sid), sid
        ),
        key="econ_series_history_id",
    )
    history_result = load_econ_series_history(selected)
    if not result_status(history_result, empty_text="이 family의 history가 없습니다"):
        return
    rows = result_payload(history_result, default=[])
    if not rows:
        return
    frame = pd.DataFrame(rows)
    frame["ref_period"] = pd.to_datetime(frame["ref_period"])
    chart = go.Figure()
    chart.add_trace(go.Scatter(
        x=frame["ref_period"], y=frame["latest_actual_value"], mode="lines+markers",
        name="최신 실제값", line={"color": _COLORS.primary},
        customdata=frame[["measure_name_ko", "unit"]].to_numpy(),
        hovertemplate="%{x|%Y-%m} · %{y:.3f}<extra>%{customdata[0]}</extra>",
    ))
    chart.update_layout(**plotly_layout(height=360), title=str(frame.iloc[-1].get("measure_name_ko") or selected))
    st.plotly_chart(chart, width="stretch")
    history_columns = {
        "ref_period": "기준 기간",
        "measure_name_ko": "지표명",
        "latest_actual_value": "최신 실제값",
        "survey_value": "시장 예상",
        "nowcast_value": "현재 추정",
        "own_model_value": "자체 모델 예상",
        "market_surprise": "시장 서프라이즈",
        "model_error": "모델 오차",
        "revision": "개정",
    }
    dataframe(
        frame[list(history_columns)].sort_values("ref_period", ascending=False).rename(columns=history_columns)
    )


st.title(":material/calendar_month: 경제 지표 캘린더")
st.html("""
    <style>
    @media (max-width: 768px) {
        /* 모바일에서는 세 가지 핵심 보기만 2×2로 배치해 터치 폭을 확보한다. */
        [data-testid="stSegmentedControl"] {
            display: grid !important;
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
            gap: 0 !important;
        }
        [data-testid="stSegmentedControl"] > div {
            display: contents !important;
        }
        [data-testid="stSegmentedControl"] button {
            width: 100% !important;
            min-height: 40px !important;
        }
        /* 요약 수치는 라벨을 짧게 유지해 2×2 비교가 빠르게 되도록 한다. */
        div[class*="st-key-econ_summary_metrics"] [data-testid="stMetricValue"] {
            font-size: 1.35rem !important;
        }
    }
    </style>
""")
view = view_selector("보기", _VIEWS, key=_VIEW_KEY, default="주간 캘린더")
today = today_kst()

upcoming_result = load_econ_upcoming(30)
recent_result = load_econ_recent_results(45)
upcoming = result_payload(upcoming_result, default=[]) if result_status(upcoming_result, empty_text="향후 발표 일정 없음") else []
recent = result_payload(recent_result, default=[]) if result_status(recent_result, empty_text="최근 발표 결과 없음") else []
# 조회 함수나 캐시의 반환 순서와 무관하게 화면에서도 카드에 표시하는 발표 시각 최신순을 보장한다.
recent.sort(key=lambda row: (str(row.get("scheduled_at") or row.get("first_actual_at") or ""), str(row.get("event_key") or "")), reverse=True)

with st.container(key="econ_summary_metrics"):
    metrics = st.columns(4)
metrics[0].metric("향후 30일", len(upcoming) if _query_ready(upcoming_result) else "—", help="향후 30일 안에 예정된 경제지표 발표 건수예요.")
metrics[1].metric("최근 45일 최초 발표", len(recent) if _query_ready(recent_result) else "—", help="최근 45일에 처음 보관한 실제 발표값이 있는 지표 건수예요.")
metrics[2].metric("시장 예상 보유", sum(row.get("survey_value") is not None for row in upcoming + recent) if _query_ready(upcoming_result) and _query_ready(recent_result) else "—", help="향후·최근 발표 중 시장 예상값을 보관한 건수예요.")
metrics[3].metric("개정 관측", sum(row.get("revision") not in (None, 0) for row in recent) if _query_ready(recent_result) else "—", help="최근 45일 발표 가운데 최초 발표값과 이후 값이 달라진 건수예요.")

visible_rows = recent
if view in {"주간 캘린더", "월간 캘린더"}:
    st.html("""
        <style>
        @media (max-width: 768px) {
            div[class*="st-key-econ_calendar_navigation"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {
                display: grid !important;
                grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
                gap: 8px !important;
                width: 100% !important;
            }
            div[class*="st-key-econ_calendar_navigation"] [data-testid="stColumn"] {
                width: auto !important;
                min-width: 0 !important;
            }
            div[class*="st-key-econ_calendar_navigation"] button {
                font-size: 0.82rem !important;
                padding: 0.35rem 0.55rem !important;
                white-space: nowrap !important;
            }
        }
        </style>
    """)
    with st.container(key="econ_calendar_navigation"):
        controls = st.columns(3, gap="small")
    if view == "주간 캘린더":
        with controls[0]:
            if st.button("이전 주", key="econ_previous_week"):
                st.session_state[_WEEK_KEY] = int(st.session_state.get(_WEEK_KEY, 0)) - 1
        with controls[1]:
            with st.container(horizontal_alignment="center"):
                if st.button("이번 주", key="econ_this_week"):
                    st.session_state[_WEEK_KEY] = 0
        with controls[2]:
            with st.container(horizontal_alignment="right"):
                if st.button("다음 주", key="econ_next_week"):
                    st.session_state[_WEEK_KEY] = int(st.session_state.get(_WEEK_KEY, 0)) + 1
        start, end, title = _window_for_week(today)
    else:
        with controls[0]:
            if st.button("이전 달", key="econ_previous_month"):
                st.session_state[_MONTH_KEY] = int(st.session_state.get(_MONTH_KEY, 0)) - 1
        with controls[1]:
            with st.container(horizontal_alignment="center"):
                if st.button("이번 달", key="econ_this_month"):
                    st.session_state[_MONTH_KEY] = 0
        with controls[2]:
            with st.container(horizontal_alignment="right"):
                if st.button("다음 달", key="econ_next_month"):
                    st.session_state[_MONTH_KEY] = int(st.session_state.get(_MONTH_KEY, 0)) + 1
        start, end, title = _window_for_month(today)
    query_start, query_end = _calendar_query_window(start, end, is_month=view == "월간 캘린더")
    window_result = load_econ_calendar_window(query_start.isoformat(), query_end.isoformat())
    rows = result_payload(window_result, default=[]) if result_status(window_result, empty_text="선택 기간 발표 없음") else []
    visible_rows = _render_calendar(rows, start=start, end=end, title=title,
                                    is_month=view == "월간 캘린더",
                                    is_available=_query_ready(window_result))
else:
    _render_series_history()

selected = st.session_state.get(_SELECTED_KEY)
selected_row = next((row for row in visible_rows if row.get("event_key") == selected), None)
if selected_row and view != "지표별 이력":
    _show_selected_dialog(str(selected), selected_row)
