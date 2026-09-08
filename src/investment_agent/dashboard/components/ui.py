"""8개 워크스페이스가 공유하는 작은 UI 표현 도우미."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd
import streamlit as st


SOURCE_DB = "DB 저장 데이터"
SOURCE_LIVE = "실시간 조회"
SOURCE_CALC = "화면 계산"
SOURCE_LOCAL = "로컬 읽기"


@dataclass(frozen=True)
class DrilldownItem:
    """요약에서 상세로 진입시키는 읽기 전용 선택 카드."""

    key: str
    label: str
    value: str
    delta: str | None = None
    icon: str = ":material/query_stats:"
    help: str | None = None
    disabled: bool = False


def _select_drilldown(state_key: str, item_key: str) -> None:
    st.session_state[state_key] = item_key


def view_selector(
    label: str,
    options: Iterable[str],
    *,
    key: str,
    default: str,
    format_func: Any = None,
) -> str:
    """선택된 한 뷰만 실행하도록 고정된 단일 선택 컨트롤을 만든다."""

    values = list(options)
    if default not in values:
        raise ValueError("default must be included in options")
    selected = st.segmented_control(
        label,
        values,
        default=default,
        required=True,
        format_func=format_func,
        key=key,
        width="stretch",
        persist_state="page",
    )
    return str(selected or default)


def detail_surface() -> str:
    """상세는 모든 화면에서 반응형 다이얼로그로 연다."""

    return "창"


def detail_layout(surface: str | None = None) -> tuple[Any, Any]:
    """목록 영역만 만든다. 상세는 선택 시 반응형 다이얼로그로 표시한다."""

    return st.container(), None


def open_detail(
    title: str,
    render: Callable[[], None],
    *,
    surface: str | None = None,
    side: Any = None,
    icon: str | None = None,
    width: str = "large",
    on_dismiss: Callable[[], None] | None = None,
) -> None:
    """선택한 상세 하나를 고른 방식으로 펼친다.

    `render`는 인자 없는 렌더 함수다. 어느 방식이든 이 함수 밖에서는 상세를 만들지
    않으므로, 선택 전에는 계산도 렌더도 일어나지 않는다.
    """

    @st.dialog(title, width=width, icon=icon, on_dismiss=on_dismiss or "rerun")
    def _modal() -> None:
        render()

    _modal()


def plot_selection_key(state: Any, field: str = "key") -> str | None:
    """plotly 선택 이벤트에서 우리가 심어 둔 customdata 키 하나만 꺼낸다.

    박스·라쏘로 여러 점이 잡혀도 첫 점만 쓴다 — 이 화면들의 선택은 항상 단일이다.
    """

    selection = getattr(state, "selection", None)
    if selection is None and isinstance(state, Mapping):
        selection = state.get("selection")
    if selection is None:
        return None
    points = getattr(selection, "points", None)
    if points is None and isinstance(selection, Mapping):
        points = selection.get("points")
    for point in list(points or []):
        if not isinstance(point, Mapping):
            continue
        custom = point.get("customdata")
        if isinstance(custom, (list, tuple)) and custom:
            return str(custom[0])
        if isinstance(custom, Mapping) and field in custom:
            return str(custom[field])
        if isinstance(custom, str) and custom:
            return custom
    return None


def page_header(title: str, subtitle: str, *, discord: str) -> None:
    """결론 중심 제목과 보조 맥락을 모든 워크스페이스에서 같은 순서로 그린다."""

    st.title(title)
    st.write(subtitle)
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        st.badge("읽기 전용", icon=":material/visibility:", color="gray")
        st.badge(f"Discord · {discord}", icon=":material/forum:", color="blue")


def source_note(*sources: str, observed_at: Any = None, detail: str | None = None) -> None:
    """카드·표·차트 바로 아래에 출처와 기준 시각을 표시한다."""

    clean = [source for source in sources if source]
    parts = ["출처 · " + " + ".join(clean)] if clean else []
    if observed_at not in (None, ""):
        parts.append(f"기준 {format_time(observed_at)}")
    if detail:
        parts.append(detail)
    st.caption(" · ".join(parts))


def format_time(value: Any) -> str:
    """다양한 DB 날짜 값을 표시용 문자열로 안전하게 바꾼다."""

    if value in (None, ""):
        return "—"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    try:
        parsed = pd.to_datetime(value, utc=True)
        if pd.isna(parsed):
            return "—"
        return parsed.tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M KST")
    except (TypeError, ValueError, OverflowError):
        return str(value)


def display_number(value: Any, *, digits: int = 2, suffix: str = "") -> str:
    """결측을 0으로 바꾸지 않는 숫자 포매터."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(number):
        return "—"
    rendered = f"{number:,.{digits}f}{suffix}"
    return rendered.replace("-", "−", 1) if rendered.startswith("-") else rendered


def display_money(value: Any, *, currency: str = "USD") -> str:
    """결측 계좌 값을 통화 0으로 위장하지 않는 포매터."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(number):
        return "—"
    code = currency.strip().upper()
    if code == "USD":
        rendered = f"${abs(number):,.2f}"
    elif code == "KRW":
        rendered = f"{abs(number):,.0f}원"
    else:
        rendered = f"{code} {abs(number):,.2f}"
    return f"−{rendered}" if number < 0 else rendered


def display_percent(value: Any, *, already_percent: bool = False, signed: bool = False) -> str:
    """비율 또는 퍼센트 값을 결측 보존 상태로 표시한다."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(number):
        return "—"
    if not already_percent:
        number *= 100
    if signed and number > 0:
        return f"+{number:,.2f}%"
    if number < 0:
        return f"−{abs(number):,.2f}%"
    return f"{number:,.2f}%"


def result_payload(result: Any, *, default: Any = None) -> Any:
    """DataResult 구현 세부와 무관하게 payload를 꺼낸다."""

    if result is None:
        return default
    value = getattr(result, "value", None)
    if value is not None:
        return value
    rows = getattr(result, "rows", None)
    return default if rows is None else rows


def result_status(result: Any, *, empty_text: str = "데이터 없음") -> bool:
    """연결/권한/빈 결과를 명시하고 실제 데이터 사용 가능 여부를 반환한다."""

    if result is None:
        st.error(
            "데이터 로더에서 결과를 받지 못했어요. 잠시 뒤 다시 불러와 주세요.",
            icon=":material/error:",
        )
        return False
    status = str(getattr(result, "status", "error"))
    if status == "ok":
        return True
    message = getattr(result, "message", None) or empty_text
    observed_at = getattr(result, "observed_at", None)
    source = str(getattr(result, "source", ""))
    last_label = "마지막 DB 기준 시각" if "DB 저장 데이터" in source else "마지막 조회 기준 시각"
    suffix = f" {last_label}: {format_time(observed_at) if observed_at else '확인 불가'}"
    if status == "empty":
        st.info(f"{empty_text}. {message}{suffix}", icon=":material/inbox:")
    elif status in {"unconfigured", "offline", "blocked"}:
        st.warning(f"{message}{suffix}", icon=":material/warning:")
    else:
        st.error(
            f"데이터를 연결하지 못했어요. {message}{suffix} 설정과 연결 상태를 확인한 뒤 다시 불러와 주세요.",
            icon=":material/cloud_off:",
        )
    return False


def dataframe(rows: Iterable[Mapping[str, Any]] | pd.DataFrame, **kwargs: Any) -> None:
    """행이 있을 때만 표를 그리고 빈 상태는 정확히 설명한다."""

    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))
    if frame.empty:
        st.info("표시할 실제 데이터가 없어요.", icon=":material/inbox:")
        return
    st.dataframe(frame, width="stretch", hide_index=True, **kwargs)


def compact_json(value: Any) -> str:
    """가변 JSON 근거를 짧고 일관되게 표시한다."""

    import json

    if value in (None, "", [], {}):
        return "—"
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def render_source_help() -> None:
    """출처 배지 의미와 실패 정책을 화면 도움말로 설명한다."""

    with st.popover("출처와 안전 경계", icon=":material/database:"):
        st.markdown(
            "- **DB 저장 데이터**: canonical v1 스키마에 저장된 사실\n"
            "- **실시간 조회**: 허용된 외부 공급자의 현재 응답\n"
            "- **화면 계산**: 조회값으로 이 세션 메모리에서만 계산\n"
            "- **로컬 읽기**: 하네스 상태 파일처럼 로컬에 이미 존재하는 운영 사실\n\n"
            "연결에 실패해도 숫자를 0이나 샘플로 바꾸지 않아요. 이 화면은 DB 저장, "
            "Discord 발송, 승인 상태 변경, 브로커 주문을 수행하지 않아요."
        )


def awaiting_message(what: str, *, reason: str, fills_when: str) -> str:
    """비어 있는 화면에 붙일 안내 문구를 만든다.

    빈 화면만으로는 "코드가 죽었다"와 "아직 안 쌓였다"를 구분할 수 없다.
    무엇이 없는지와 언제 채워지는지를 함께 적어 둔다.
    """
    subject = str(what).strip()
    why = str(reason).strip()
    when = str(fills_when).strip()
    if not subject or not why or not when:
        raise ValueError("awaiting_message needs what, reason and fills_when")
    return f"{subject}: {why}. {when}."


def awaiting_data(what: str, *, reason: str, fills_when: str) -> None:
    """`awaiting_message`를 화면에 표시한다."""
    st.info(awaiting_message(what, reason=reason, fills_when=fills_when), icon=":material/schedule:")
