"""ATLAS 홈 — 시장 상태, 일정, 신호와 전략 배분을 한 화면에 모은다."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import pandas as pd
import streamlit as st

from investment_agent.dashboard.calculations import (
    finite_number,
    macro_alert_counts,
    macro_change,
    macro_indicator_rows,
    macro_regime,
    macro_value_text,
    today_kst,
)
from investment_agent.reporting.readers.dashboard import load_econ_upcoming, load_macro_window
from investment_agent.reporting.readers.dashboard import load_price_history, load_strategy_data
from investment_agent.dashboard.components.ui import display_number, format_time, result_payload
from investment_agent.reporting.services.strategy_labels import mode_label, strategy_label


# (가격 저장소 ticker, 표시명, 매크로 series_id).
# 첫 칸이 None인 것은 가격 저장소가 담지 않는 지표다 — VIX와 원/달러는 종목이 아니라
# macro 관측이다. 이 둘을 가격 조회에 섞으면 reader가 종목 코드 형식 검사에서 질의
# **전체**를 blocked로 돌려보내고, 그러면 SPY·QQQ 카드까지 함께 조용히 빈다.
_MARKETS: tuple[tuple[str | None, str, str], ...] = (
    ("SPY", "S&P 500", "SPY"),
    ("QQQ", "나스닥 100", "QQQ"),
    (None, "변동성", "VIX"),
    (None, "달러/원", "USDKRW"),
)
_PRICE_TICKERS = tuple(ticker for ticker, _, _ in _MARKETS if ticker)
_TIER_ORDER = {"alert": 0, "caution": 1, "watch": 2, "": 3}
_TIER_LABEL = {"alert": "위험", "caution": "주의", "watch": "관심", "": "일반"}
_COUNTRY = {"US": "미국", "KR": "한국"}


def _close_prices(value: Any) -> pd.DataFrame:
    """저장 가격 응답에서 종가만 꺼내고, 해석할 수 없으면 빈 표를 반환한다."""

    if not isinstance(value, pd.DataFrame) or value.empty:
        return pd.DataFrame()
    frame = value.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        if "Close" not in frame.columns.get_level_values(0):
            return pd.DataFrame()
        close = frame.xs("Close", axis=1, level=0)
    elif "Close" in frame.columns:
        close = frame[["Close"]].rename(columns={"Close": "SPY"})
    else:
        return pd.DataFrame()
    close.columns = [str(column).upper() for column in close.columns]
    return close.apply(pd.to_numeric, errors="coerce").dropna(how="all")


def _tier_key(value: Any) -> str:
    text = str(value or "")
    return next((key for key in ("alert", "caution", "watch") if key in text), "")


def _market_value(value: Any) -> str:
    """저장 종가는 달러 표기다 — 이 경로에 오는 것은 가격 저장소의 종목뿐이다."""
    number = finite_number(value)
    return "—" if number is None else f"${number:,.2f}"


def _market_snapshot(
    close: pd.DataFrame,
    indicators: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """저장 종가를 우선하고, 없는 종목만 저장 매크로 값으로 보완한다."""

    stored = {str(row.get("series_id")): row for row in indicators}
    cards: list[dict[str, Any]] = []
    for price_ticker, label, stored_id in _MARKETS:
        series = (
            close[price_ticker].dropna()
            if price_ticker and price_ticker in close.columns
            else pd.Series(dtype="float64")
        )
        if not series.empty:
            latest = finite_number(series.iloc[-1])
            previous = finite_number(series.iloc[-2]) if len(series) >= 2 else None
            change_pct = (
                (latest / previous - 1.0) * 100.0
                if latest is not None and previous not in (None, 0.0)
                else None
            )
            cards.append(
                {
                    "label": f"{label} · {stored_id}",
                    "value": _market_value(latest),
                    "delta": f"{change_pct:+.2f}%" if change_pct is not None else None,
                    "spark": series.tail(20).tolist(),
                    "source": "저장 가격",
                    "inverse": stored_id == "VIX",
                }
            )
            continue

        row = stored.get(stored_id)
        change = macro_change(row) if row else {"text": "—"}
        cards.append(
            {
                "label": f"{label} · {stored_id}",
                "value": macro_value_text(row) if row else "—",
                "delta": change.get("text") if change.get("text") != "—" else None,
                "spark": list((row or {}).get("spark") or []),
                "source": "저장 관측" if row else "연결 대기",
                "inverse": stored_id == "VIX",
            }
        )
    return cards


def _relative_performance(
    close: pd.DataFrame,
    indicators: list[dict[str, Any]],
) -> pd.DataFrame:
    """SPY·QQQ의 시작값을 100으로 맞춘 비교 시계열을 만든다."""

    usable = close[[column for column in ("SPY", "QQQ") if column in close]].dropna(how="all")
    if usable.shape[1] < 2:
        stored = {str(row.get("series_id")): row for row in indicators}
        series: dict[str, pd.Series] = {}
        for symbol in ("SPY", "QQQ"):
            row = stored.get(symbol)
            values = (row or {}).get("series")
            if isinstance(values, pd.Series) and not values.empty:
                series[symbol] = pd.to_numeric(values, errors="coerce").dropna().tail(40)
        usable = pd.DataFrame(series).dropna(how="all")
    if usable.empty:
        return usable
    base = usable.apply(lambda column: column.dropna().iloc[0] if column.notna().any() else None)
    base = pd.to_numeric(base, errors="coerce").replace(0, pd.NA)
    return usable.divide(base, axis=1).multiply(100.0).dropna(how="all")


def _expected_value(row: Mapping[str, Any]) -> str:
    key = next(
        (
            field
            for field in ("survey_value", "nowcast_value", "own_model_value")
            if row.get(field) is not None
        ),
        None,
    )
    if key is None:
        return "—"
    suffix = "%" if str(row.get("unit") or "") in {"percent", "percent_annualized", "rate"} else ""
    return display_number(row.get(key), digits=2, suffix=suffix)


def _econ_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    unique: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: str(item.get("scheduled_at") or "")):
        key = str(row.get("event_key") or row.get("series_id") or "")
        if key and key not in unique:
            unique[key] = row
    records: list[dict[str, str]] = []
    for row in list(unique.values())[:5]:
        moment = pd.to_datetime(row.get("scheduled_at"), utc=True, errors="coerce")
        when = moment.tz_convert("Asia/Seoul").strftime("%m/%d %H:%M") if pd.notna(moment) else "—"
        records.append(
            {
                "일정": when,
                "국가": _COUNTRY.get(str(row.get("country") or "").upper(), str(row.get("country") or "—")),
                "지표": str(row.get("series_name_ko") or row.get("series_id") or "—"),
                "예상": _expected_value(row),
            }
        )
    return pd.DataFrame(records)


def _allocation_text(weights: Any) -> str:
    if not isinstance(weights, Mapping):
        return "—"
    items: list[tuple[str, float]] = []
    for symbol, value in weights.items():
        weight = finite_number(value)
        if str(symbol).strip() and weight is not None and weight > 0:
            items.append((str(symbol).upper(), weight))
    items.sort(key=lambda item: -item[1])
    if not items:
        return "—"
    equal = len(items) > 1 and max(weight for _, weight in items) - min(weight for _, weight in items) < 1e-9
    if equal:
        return " · ".join(symbol for symbol, _ in items) + f" (각 {items[0][1]:.0%})"
    return " · ".join(f"{symbol} {weight:.0%}" for symbol, weight in items)


def _mode_text(value: Any) -> str:
    label = mode_label(value)
    return re.sub(r"^[^A-Za-z0-9가-힣]+", "", label).strip()


def _strategy_table(payload: Mapping[str, Any]) -> pd.DataFrame:
    allocations = [row for row in payload.get("allocations", []) if isinstance(row, Mapping)]
    latest: dict[str, Mapping[str, Any]] = {}
    for row in allocations:
        strategy_id = str(row.get("strategy_id") or "")
        current = latest.get(strategy_id)
        if strategy_id and (
            current is None or str(row.get("apply_date") or "") > str(current.get("apply_date") or "")
        ):
            latest[strategy_id] = row
    records: list[dict[str, str]] = []
    for strategy_id, row in sorted(latest.items(), key=lambda item: item[0]):
        meta = strategy_label(strategy_id)
        records.append(
            {
                "전략": meta.name if meta else strategy_id.upper(),
                "판단": _mode_text(row.get("mode")),
                "배분": _allocation_text(row.get("weights")),
                "적용월": str(row.get("apply_date") or "—"),
            }
        )
    return pd.DataFrame(records)


def _signal_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    ranked = sorted(
        rows,
        key=lambda row: (
            _TIER_ORDER[_tier_key(row.get("tier"))],
            -abs(finite_number(macro_change(row).get("delta")) or 0.0),
        ),
    )
    records = [
        {
            "등급": _TIER_LABEL[_tier_key(row.get("tier"))],
            "신호": str(row.get("name_ko") or row.get("series_id") or "—"),
            "현재": macro_value_text(row),
            "변화": macro_change(row).get("text") or "—",
        }
        for row in ranked[:6]
    ]
    return pd.DataFrame(records)


def _page_link(page: str, label: str) -> None:
    """내비게이션 밖의 단독 AppTest에서도 홈 내용은 끝까지 렌더링한다."""

    try:
        st.page_link(page, label=label, icon=":material/arrow_forward:")
    except (KeyError, ValueError):
        st.caption(label)


macro_result = load_macro_window("all")
econ_result = load_econ_upcoming(14)
strategy_result = load_strategy_data()
price_result = load_price_history(_PRICE_TICKERS, period="1mo")

macro_rows = list(result_payload(macro_result, default=[]) or [])
indicators = macro_indicator_rows(macro_rows)
econ_rows = list(result_payload(econ_result, default=[]) or [])
strategy_payload = result_payload(strategy_result, default={}) or {}
close = _close_prices(result_payload(price_result, default=None))
snapshot = _market_snapshot(close, indicators)
regime = macro_regime(indicators)
counts = macro_alert_counts(indicators)

header_left, header_right = st.columns([5, 2], vertical_alignment="bottom")
with header_left:
    st.title("마켓 커맨드 센터")
    st.caption(f"{today_kst().isoformat()} · 시장, 일정, 신호, 전략을 한 화면에서 확인합니다.")
with header_right:
    if getattr(price_result, "status", "error") == "ok" and not close.empty:
        st.badge("저장 가격 · 최근 종가", icon=":material/database:", color="primary")
        st.caption(format_time(getattr(price_result, "observed_at", None)))
    else:
        st.badge("저장 관측 기준", icon=":material/database:", color="gray")
        st.caption(format_time(getattr(macro_result, "observed_at", None)))

with st.container(horizontal=True, key="home_market_strip"):
    for card in snapshot:
        st.metric(
            card["label"],
            card["value"],
            card["delta"],
            delta_color="inverse" if card["inverse"] else "normal",
            chart_data=card["spark"] or None,
            chart_type="line",
            border=True,
            help=f"{card['source']} 기준",
        )

with st.container(key="home_overview_grid"):
    market_column, regime_column = st.columns([1.65, 1], gap="medium")
    with market_column:
        with st.container(border=True):
            st.subheader("미국 주식 1개월 상대성과")
            relative = _relative_performance(close, indicators)
            if relative.empty or relative.shape[1] < 2:
                st.info("SPY와 QQQ의 비교 가능한 가격 구간을 기다리고 있습니다.", icon=":material/query_stats:")
            else:
                st.line_chart(
                    relative,
                    color=["#2F81F7", "#94A3B8"],
                    height=320,
                    x_label="기준일",
                    y_label="시작값 = 100",
                )
            _page_link("app_pages/macro.py", "전체 시장 지표")

    with regime_column:
        with st.container(border=True, height="stretch"):
            st.subheader("시장 레짐")
            tone = str(regime.get("tone") or "flat")
            st.badge(
                str(regime.get("verdict") or "판단 불가"),
                icon=":material/radar:",
                color={"up": "green", "down": "red"}.get(tone, "gray"),
            )
            st.metric(
                "판단 근거",
                f"{regime.get('evaluated', 0)}개",
                f"위험 {counts['alert']} · 주의 {counts['caution']} · 관심 {counts['watch']}",
                delta_color="off",
            )
            support = list(regime.get("supporting") or [])
            oppose = list(regime.get("opposing") or [])
            st.markdown("**우세 근거**")
            st.write(" · ".join(support[:3]) if support else "확인 가능한 우세 근거가 없습니다.")
            st.markdown("**반대 신호**")
            st.write(" · ".join(oppose[:3]) if oppose else "확인 가능한 반대 신호가 없습니다.")

with st.container(key="home_action_grid"):
    schedule_column, signal_column = st.columns(2, gap="medium")
    with schedule_column:
        with st.container(border=True, height="stretch"):
            st.subheader("앞으로 14일 주요 발표")
            schedule = _econ_table(econ_rows)
            if schedule.empty:
                st.info("확인 가능한 경제지표 일정이 없습니다.", icon=":material/event_busy:")
            else:
                st.dataframe(schedule, hide_index=True, width="stretch", height=246)
            _page_link("app_pages/econ_calendar.py", "경제 캘린더")

    with signal_column:
        with st.container(border=True, height="stretch"):
            st.subheader("시장 신호 레이더")
            signals = _signal_table(indicators)
            if signals.empty:
                st.info("계산 가능한 시장 신호가 없습니다.", icon=":material/radar:")
            else:
                st.dataframe(signals, hide_index=True, width="stretch", height=246)
            _page_link("app_pages/macro.py", "신호 전체 보기")

with st.container(border=True):
    st.subheader("이번 달 퀀트 포지셔닝")
    strategy_table = _strategy_table(strategy_payload if isinstance(strategy_payload, Mapping) else {})
    if strategy_table.empty:
        st.info("저장된 최신 전략 배분이 없습니다.", icon=":material/account_tree:")
    else:
        st.dataframe(strategy_table, hide_index=True, width="stretch", height=246)
    _page_link("app_pages/quant.py", "전략 상세와 백테스트")
