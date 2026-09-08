"""날짜 범위를 일요일 시작 격자로 표현하는 읽기 전용 캘린더."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


# Python의 weekday()는 월요일이 0이지만, 금융 일정의 월간 달력은 일요일을 첫 열로 둔다.
WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")
CALENDAR_WEEKDAYS = ("일", "월", "화", "수", "목", "금", "토")
DAY_CELL_MIN_HEIGHT = 270
DEFAULT_EVENT_LIMIT = 3
NARROW_EVENT_LIMIT = 2
COMPACT_CELL_WIDTH = 150
# 국기 SVG는 화면 전체가 공유하므로 dashboard 뿌리에 있다 — components 옆이 아니다.
# 이 경로가 어긋나면 st.image가 MediaFileStorageError로 캘린더를 통째로 죽인다.
_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
COUNTRY_FLAG_ASSETS = {
    "US": _ASSET_DIR / "flag-us.svg",
    "KR": _ASSET_DIR / "flag-kr.svg",
}
CATEGORY_COLORS = {
    "inflation": "#fb923c",
    "labor": "#60a5fa",
    "growth_consumption": "#4ade80",
    "policy_housing": "#c084fc",
    "liquidity_trade_energy": "#facc15",
}


@dataclass(frozen=True)
class CalendarEvent:
    """출처별 사실을 유지한 날짜 셀의 최소 표시 계약."""

    key: str
    day: date
    title: str
    country: str = ""
    category: str = ""
    time_label: str = "시각 미정"
    status: str = "예정"
    caption: str = ""
    expected_label: str = "예상"
    expected_value: str = "—"
    actual_value: str = "—"


def calendar_weeks(start: date, end: date) -> list[tuple[date, ...]]:
    """[start, end)를 포함하는 일~토 주차를 반환한다. 경계 밖 날짜도 유지한다."""
    if end <= start:
        return []
    if (end - start).days > 62:
        raise ValueError("캘린더는 한 번에 62일 이하만 표시해요.")
    cursor = start - timedelta(days=(start.weekday() + 1) % 7)
    weeks = []
    while cursor < end:
        weeks.append(tuple(cursor + timedelta(days=offset) for offset in range(7)))
        cursor += timedelta(days=7)
    return weeks


def _day_heading(day: date, *, in_window: bool, include_weekday: bool = True) -> str:
    """주말은 색·요일 텍스트를 함께 써서 색각 차이에도 구분한다."""
    label = f"{day.month}/{day.day}"
    if include_weekday:
        label = f"{label} {WEEKDAYS[day.weekday()]}"
    if day.weekday() == 6:
        return f":red[**{label}**]" if in_window else f":red[{label}]"
    if day.weekday() == 5:
        return f":blue[**{label}**]" if in_window else f":blue[{label}]"
    return f"**{label}**" if in_window else label


def render_calendar_grid(
    events: Sequence[CalendarEvent],
    *,
    start: date,
    end: date,
    today: date,
    key: str,
    on_select: Callable[[str], None],
    selected: str | None = None,
    is_available: bool = True,
    is_month: bool = False,
) -> None:
    """네이티브 버튼으로 키보드 탐색과 rerun을 유지하는 일요일 시작 달력이다."""
    import streamlit as st

    by_day: dict[date, list[CalendarEvent]] = {}
    unique = {event.key: event for event in events}
    grid_days = {day for week in calendar_weeks(start, end) for day in week}
    for event in sorted(unique.values(), key=lambda item: (item.day, item.time_label, item.key)):
        if event.day in grid_days:
            by_day.setdefault(event.day, []).append(event)
    # 일정명 자체가 상세를 여는 네이티브 버튼이다. 기본 가운데 정렬만 왼쪽으로 바꿔
    # 긴 지표명이 값보다 먼저 읽히게 하며, 색·테마·상태 모양은 건드리지 않는다.
    st.html(f"""
        <style>
        div[class*="st-key-{key}_detail_"] button {{
            justify-content: flex-start !important;
            text-align: left !important;
        }}
        div[class*="st-key-{key}_detail_"] button > div {{
            width: 100% !important;
            justify-content: flex-start !important;
            text-align: left !important;
        }}
        div[class*="st-key-{key}_detail_"] button p {{ text-align: left !important; }}
        div[class*="st-key-{key}_flag_"] img {{
            border-radius: 3px;
            object-fit: cover;
        }}
        div[class*="st-key-{key}_day_"] {{
            container-type: inline-size;
            container-name: calendar-day;
            min-height: {DAY_CELL_MIN_HEIGHT}px;
        }}
        div[class*="st-key-{key}_header_"] p {{ white-space: nowrap; }}
        div[class*="st-key-{key}_header_"] [data-testid="stHorizontalBlock"] {{
            width: 100% !important;
            justify-content: center !important;
            align-items: center !important;
            gap: 10px !important;
            user-select: none !important;
            -webkit-user-select: none !important;
            -webkit-user-drag: none !important;
        }}
        div[class*="st-key-{key}_weekday_header"] {{ user-select: none; }}
        div[class*="st-key-{key}_weekday_header"] [data-testid="stHorizontalBlock"] {{
            display: grid !important;
            grid-template-columns: repeat(7, minmax(0, 1fr));
            gap: 8px;
            width: 100%;
        }}
        div[class*="st-key-{key}_weekday_header"] [data-testid="stColumn"] {{
            width: auto !important;
            min-width: 0 !important;
        }}
        div[class*="st-key-{key}_mobile_day_heading_"] {{ display: none; }}
        div[class*="st-key-{key}_values_"] {{ flex-wrap: nowrap; gap: 8px; }}
        div[class*="st-key-{key}_values_"] p {{ white-space: nowrap; }}
        div[class*="st-key-{key}_values_"] > div {{ width: fit-content; flex: 0 0 auto; }}
        div:has(> div[class*="st-key-{key}_narrow_"]) {{ display: none; }}
        @container calendar-day (max-width: {COMPACT_CELL_WIDTH}px) {{
            div:has(> div[class*="st-key-{key}_wide_"]) {{ display: none; }}
            div:has(> div[class*="st-key-{key}_narrow_"]) {{ display: flex; }}
            div[class*="st-key-{key}_values_"] {{
                flex-direction: column; align-items: flex-end; gap: 4px;
            }}
        }}
        @media (max-width: 768px) {{
            /* 세로 카드에서는 7열 기준선 대신 카드 안에서 요일까지 함께 읽는다. */
            div[class*="st-key-{key}_weekday_header"] {{ display: none !important; }}
            div[class*="st-key-{key}_desktop_day_heading_"] {{ display: none !important; }}
            div[class*="st-key-{key}_mobile_day_heading_"] {{ display: block !important; }}
            /* 제목과 국기는 같은 줄에 유지하고, 국기는 항상 카드 오른쪽에 둔다. */
            div[class*="st-key-{key}_event_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {{
                display: grid !important;
                grid-template-columns: minmax(0, 1fr) auto !important;
                align-items: center !important;
                gap: 6px !important;
            }}
            div[class*="st-key-{key}_event_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
                width: auto !important;
                min-width: 0 !important;
            }}
            div[class*="st-key-{key}_flag_"] {{
                width: 24px !important;
                justify-self: end !important;
            }}
            div[class*="st-key-{key}_flag_"] img {{
                display: block !important;
                margin-left: auto !important;
            }}
            div[class*="st-key-{key}_event_"] button {{
                min-width: 0 !important;
                overflow: hidden !important;
                text-overflow: ellipsis !important;
            }}
            /* 작은 화면에서는 한 주를 세로 목록으로 읽어 각 지표의 터치 영역을 확보한다. */
            div[class*="st-key-{key}_week_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(7)) {{
                display: grid !important;
                grid-template-columns: minmax(0, 1fr) !important;
                gap: 8px !important;
            }}
            div[class*="st-key-{key}_week_"] [data-testid="stColumn"] {{
                width: 100% !important;
                min-width: 0 !important;
                flex: none !important;
            }}
            div[class*="st-key-{key}_week_"] [data-testid="stColumn"] > [data-testid="stVerticalBlock"] {{
                height: auto !important;
            }}
            div[class*="st-key-{key}_day_"] {{
                min-height: 0 !important;
                height: auto !important;
            }}
            div[class*="st-key-{key}_day_"] [data-testid="stVerticalBlock"] {{
                height: auto !important;
            }}
        }}
        </style>
    """)
    with st.container(key=f"{key}_weekday_header"):
        weekday_columns = st.columns(7, gap="xsmall", wrap=True)
        for label, column in zip(CALENDAR_WEEKDAYS, weekday_columns):
            with column:
                if label == "일":
                    st.markdown(":red[**일요일**]", text_alignment="center")
                elif label == "토":
                    st.markdown(":blue[**토요일**]", text_alignment="center")
                else:
                    st.markdown(f"**{label}요일**", text_alignment="center")
    for week in calendar_weeks(start, end):
        week_cells = []
        for day in week:
            in_window = start <= day < end
            day_events = by_day.get(day, [])
            expanded_key = f"{key}_expanded_{day.isoformat()}"
            is_expanded = bool(st.session_state.get(expanded_key, False))
            week_cells.append((day, in_window, day_events, expanded_key, is_expanded))
        # 한 주는 한 행으로 읽힌다. 일정이 많은 날짜가 있더라도 기본 상태에서는
        # 같은 행의 일곱 칸 높이를 맞춰 날짜의 리듬을 유지한다.
        with st.container(key=f"{key}_week_{week[0].isoformat()}"):
            columns = st.columns(7, gap="xsmall", wrap=True)
            for cell, column in zip(week_cells, columns):
                day, in_window, day_events, expanded_key, is_expanded = cell
                with column.container(border=True, height="stretch", gap="xsmall", key=f"{key}_day_{day.isoformat()}"):
                    heading = f"{day.month}/{day.day} {WEEKDAYS[day.weekday()]}"
                    with st.container(
                        horizontal=True,
                        horizontal_alignment="center",
                        vertical_alignment="center",
                        wrap=False,
                        key=f"{key}_header_{day.isoformat()}",
                        gap="xsmall",
                    ):
                        # 날짜·요일을 먼저 읽고 건수는 카드 끝에서 빠르게 비교한다.
                        with st.container(
                            key=f"{key}_desktop_day_heading_{day.isoformat()}",
                            width="content",
                        ):
                            st.markdown(
                                _day_heading(day, in_window=in_window, include_weekday=False),
                                width="content",
                                text_alignment="center",
                            )
                        with st.container(
                            key=f"{key}_mobile_day_heading_{day.isoformat()}",
                            width="content",
                        ):
                            st.markdown(
                                _day_heading(day, in_window=in_window),
                                width="content",
                                text_alignment="center",
                            )
                        if is_available:
                            st.caption(
                                f"{len(day_events)}건",
                                width="content",
                                text_alignment="center",
                            )
                    if day == today and is_available:
                        st.caption(":material/today: 오늘", text_alignment="center")
                    if not is_available:
                        st.caption("일정 확인 불가")
                        continue
                    if not day_events:
                        st.caption("발표 없음")
                        continue
                    def event_button(event: CalendarEvent) -> None:
                        title = event.title.removeprefix("미국 ").removeprefix("한국 ")
                        title = title.replace("소비자물가지수", "CPI").replace("생산자물가지수", "PPI")
                        country_flag = COUNTRY_FLAG_ASSETS.get(event.country.upper())
                        category_color = CATEGORY_COLORS.get(event.category, "#e5e7eb")
                        event_key = event.key.replace(":", "-")
                        st.html(f"""
                            <style>
                            div[class*="st-key-{key}_event_{event_key}"] button p {{
                                color: {category_color} !important;
                            }}
                            </style>
                        """)
                        with st.container(gap=None, key=f"{key}_event_{event.key}"):
                            if country_flag is None:
                                st.button(
                                    title,
                                    key=f"{key}_detail_{event.key}",
                                    help=f"{event.title}\n\n{event.time_label} · {event.status} · {event.caption}",
                                    type="primary" if selected == event.key else "tertiary",
                                    width="stretch",
                                    wrap=False,
                                    on_click=on_select,
                                    args=(event.key,),
                                )
                            else:
                                title_column, flag_column = st.columns([6, 1], gap="xsmall", vertical_alignment="center")
                                with title_column:
                                    st.button(
                                        title,
                                        key=f"{key}_detail_{event.key}",
                                        help=f"{event.title}\n\n{event.time_label} · {event.status} · {event.caption}",
                                        type="primary" if selected == event.key else "tertiary",
                                        width="stretch",
                                        wrap=False,
                                        on_click=on_select,
                                        args=(event.key,),
                                    )
                                with flag_column.container(key=f"{key}_flag_{event.key}"):
                                    st.image(country_flag, width=18)
                            with st.container(horizontal=True, horizontal_alignment="right", gap="small", key=f"{key}_values_{event.key}"):
                                st.caption(f"{event.expected_label} {event.expected_value}")
                                st.caption(f"실제 {event.actual_value}")
                    visible_events = day_events if is_expanded else day_events[:DEFAULT_EVENT_LIMIT]
                    for index, event in enumerate(visible_events):
                        # 세 번째 일정과 더보기 개수는 같은 너비 조건으로 함께 전환한다.
                        if not is_expanded and index == NARROW_EVENT_LIMIT:
                            with st.container(key=f"{key}_wide_event_{day.isoformat()}"):
                                event_button(event)
                        else:
                            event_button(event)
                    if len(day_events) > NARROW_EVENT_LIMIT:
                        def toggle_day(state_key: str, expanded: bool) -> None:
                            st.session_state[state_key] = not expanded

                        def toggle_button(limit: int, suffix: str = "") -> None:
                            st.button(
                                "접기" if is_expanded else f"+{len(day_events) - limit}건",
                                key=f"{key}_toggle_{day.isoformat()}{suffix}",
                                help=f"{heading}의 전체 일정을 {'접습니다' if is_expanded else '펼칩니다'}",
                                type="tertiary",
                                icon=":material/expand_less:" if is_expanded else ":material/expand_more:",
                                icon_position="right",
                                width="content",
                                on_click=toggle_day,
                                args=(expanded_key, is_expanded),
                            )
                        if is_expanded:
                            with st.container(horizontal_alignment="right"):
                                toggle_button(DEFAULT_EVENT_LIMIT)
                        else:
                            if len(day_events) > DEFAULT_EVENT_LIMIT:
                                with st.container(horizontal_alignment="right", key=f"{key}_wide_toggle_{day.isoformat()}"):
                                    toggle_button(DEFAULT_EVENT_LIMIT)
                            with st.container(horizontal_alignment="right", key=f"{key}_narrow_toggle_{day.isoformat()}"):
                                toggle_button(NARROW_EVENT_LIMIT, "_narrow")
