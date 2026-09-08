"""퀀트 전략 — 6개 전략의 이번 달 판단을 한눈에 보고, 고른 전략만 파고든다.

**이 화면이 다루는 두 가지 사실을 섞지 않는다.**

- `Research 저장 배분` — 로컬 DuckDB가 실제로 적재한 달의 결과. 운영이 돌린
  것만 있어 기간이 짧다(백필 진행 중).
- `장기 백테스트` — 같은 전략 함수(`investment_agent.research.strategies.strategies`)를 월말마다 다시 돌려
  만든 재현. 월말 종가만 있으면 저장 이력이 닿지 않는 과거까지 이어진다. 결과는
  세션 메모리에만 있고 DB에 저장하지 않는다.

두 사실은 `DB 대조`에서 같은 적용월끼리 맞춰 보고, 어긋난 달만 드러낸다.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from investment_agent.dashboard.components.performance_analysis import drawdown_episodes, drawdown_series, risk_metrics

from investment_agent.dashboard.calculations import (
    build_strategy_returns,
    compare_stored_and_replayed_allocations,
    monthly_close_from_daily,
    monte_carlo_fan,
    monthly_returns_matrix,
    performance_metrics,
    replay_strategy_rules,
)
from investment_agent.reporting.readers.dashboard import load_price_history, load_strategy_data
from investment_agent.dashboard.components.theme import dashboard_palette, plotly_layout
from investment_agent.dashboard.components.ui import (
    SOURCE_CALC,
    SOURCE_DB,
    compact_json,
    dataframe,
    detail_surface,
    display_number,
    display_percent,
    open_detail,
    plot_selection_key,
    result_payload,
    result_status,
    source_note,
    view_selector,
)


_COLORS = dashboard_palette()
PRIMARY = _COLORS.primary
TEXT = _COLORS.text
MUTED = _COLORS.muted
UP = _COLORS.up
DOWN = _COLORS.down
WARNING = _COLORS.warning
CHART_COLORS = _COLORS.categorical
# 재현은 운영 월간 적재와 같은 계산 registry를 쓴다(규칙이 갈라지지 않게).
from investment_agent.reporting.services.strategy_labels import mode_label, strategy_ids, strategy_label, strategy_tickers, ticker_label


_SELECTED_KEY = "quant_selected_strategy"
_MONTH_KEY = "quant_allocation_month"
_REPLAY_STATE_KEY = "quant_replay_result"
_ALL_REPLAY_STATE_KEY = "quant_all_replay_result"
_SIMULATION_STATE_KEY = "quant_simulation_result"
_MONTE_CARLO_MIN_OBSERVATIONS = 12
_BENCHMARK = "SPY"
_CARD_COLUMNS = 3

_DETAIL_VIEWS = ("장기 백테스트", "DB 적재 구간", "월별 판단", "DB 대조", "미래 경로 추정")

# 이름만 보고 무엇인지 모르면 쓸 수 없는 화면이 된다. 각 보기 첫 줄에 정의를 둔다.
_GLOSSARY = {
    "장기 백테스트": (
        "월말 종가로 **전략 룰을 과거부터 다시 돌린** 결과입니다. DB에 적재되지 않은 "
        "기간까지 이어집니다. 월말 M까지의 가격만 보고 배분을 정하고 수익률은 다음 달 "
        "M+1로만 매깁니다(미래를 보지 않음). 실제 운영 기록이 아니라 화면 계산입니다."
    ),
    "DB 적재 구간": (
        "Research DuckDB에 **실제로 적재된 적용월** 사이의 성과입니다. 운영이 "
        "돌린 기록 그대로이며, 백필이 진행될수록 구간이 길어집니다."
    ),
    "월별 판단": (
        "달마다 어떤 모드로 무엇을 담았는지 나열합니다. 위는 재현 결과, 아래는 DB에 "
        "적재된 실제 기록입니다."
    ),
    "DB 대조": (
        "같은 적용월에서 **저장된 배분과 재현한 배분이 같은지** 맞춰 봅니다. 다르면 "
        "가격 소스 재조정이나 적재 시점 차이를 의심해야 합니다."
    ),
    "미래 경로 추정": (
        "과거 **실제 월수익률을 무작위로 다시 뽑아(bootstrap)** 향후 경로의 분포를 "
        "그립니다. 예측이나 보장이 아니라 '지금까지의 변동폭이 이어진다면'이라는 가정의 "
        "산포도입니다."
    ),
}


def _allocation_items(allocation: Any) -> list[tuple[str, float]]:
    """저장·재현 배분에서 유한한 양수 비중만 큰 순서로 뽑는다."""

    if not isinstance(allocation, Mapping):
        return []
    items: list[tuple[str, float]] = []
    for symbol, raw_weight in allocation.items():
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError, OverflowError):
            continue
        name = str(symbol).upper().strip()
        if name and math.isfinite(weight) and weight > 0.0:
            items.append((name, weight))
    return sorted(items, key=lambda item: -item[1])


def _asset_label(symbol: str) -> str:
    korean = ticker_label(symbol)
    return f"{symbol} {korean}" if korean else symbol


def _mode_label(mode: Any) -> str:
    return mode_label(mode)


def _allocation_text(allocation: Any) -> str:
    items = _allocation_items(allocation)
    return _allocation_summary(items)


def _is_equal_weight_allocation(items: list[tuple[str, float]]) -> bool:
    """두 자산 이상이 같은 비중이면 반복되는 퍼센트 표기를 생략한다."""

    weights = [weight for _symbol, weight in items]
    return len(weights) > 1 and max(weights) - min(weights) < 1e-9


def _allocation_summary(items: list[tuple[str, float]], *, bold: bool = False) -> str:
    """균등 배분은 티커만, 비균등 배분은 티커와 비중을 함께 보여준다."""

    if not items:
        return "—"
    show_weights = not _is_equal_weight_allocation(items)
    return " · ".join(
        f"**{symbol}** {weight:.0%}" if bold and show_weights
        else f"**{symbol}**" if bold
        else f"{symbol} {weight:.0%}" if show_weights
        else symbol
        for symbol, weight in items
    )


def _assets_for_allocations(rows: list[dict[str, Any]], *, include_benchmark: bool) -> list[str]:
    assets: set[str] = set()
    for row in rows:
        for symbol, _weight in _allocation_items(row.get("weights")):
            if symbol != "CASH":
                assets.add(symbol)
    if include_benchmark:
        assets.add(_BENCHMARK)
    return sorted(assets)


def _strategy_returns(rows: list[dict[str, Any]], prices: Any) -> pd.Series:
    frame = build_strategy_returns(rows, prices)
    if isinstance(frame, pd.Series):
        return frame.dropna().astype(float)
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        return frame.iloc[:, 0].dropna().astype(float)
    return pd.Series(dtype="float64")


def _select_strategy(strategy_id: str) -> None:
    st.session_state[_SELECTED_KEY] = (
        None if st.session_state.get(_SELECTED_KEY) == strategy_id else strategy_id
    )


def _metric_row(specs: tuple[tuple[str, str, str | None], ...]) -> None:
    with st.container(horizontal=True, gap="small"):
        for label, value, delta in specs:
            st.metric(label, value, delta, border=True)


def _render_allocation_bar(items: list[tuple[str, float]], *, key: str) -> None:
    """이번 달 배분을 가로 막대 하나로 보여준다(자산이 1~5개라 도넛보다 읽기 쉽다)."""

    if not items:
        st.caption("표시할 실제 비중이 없습니다.")
        return
    figure = go.Figure()
    palette = (PRIMARY, TEXT, MUTED, UP, WARNING)
    show_weights = not _is_equal_weight_allocation(items)
    for index, (symbol, weight) in enumerate(items):
        figure.add_trace(
            go.Bar(
                x=[weight],
                y=["배분"],
                orientation="h",
                name=_asset_label(symbol),
                marker_color=palette[index % len(palette)],
                text=f"{symbol} {weight * 100:.0f}%" if show_weights else symbol,
                textposition="inside",
                insidetextanchor="middle",
                textfont={"size": 11},
                hovertemplate=f"{_asset_label(symbol)} %{{x:.1%}}<extra></extra>",
            )
        )
    layout = plotly_layout(height=64)
    layout["margin"] = {"l": 0, "r": 0, "t": 0, "b": 0}
    # 공통 레이아웃의 축 설정을 그대로 두면 update_layout이 중복 인자로 실패한다.
    layout["xaxis"] = {"visible": False, "range": [0, 1]}
    layout["yaxis"] = {"visible": False}
    figure.update_layout(**layout, barmode="stack", showlegend=False)
    st.plotly_chart(
        figure, width="stretch", config={"displaylogo": False, "staticPlot": True}, key=key
    )


def _render_strategy_card(
    strategy_id: str,
    *,
    name: str,
    latest: dict[str, Any] | None,
    allocation_count: int,
    selected: bool,
) -> None:
    """전략 하나의 '이번 달 판단'을 카드로 그린다."""

    meta = strategy_label(strategy_id)
    items = _allocation_items((latest or {}).get("weights"))
    with st.container(border=True, key=f"quant_card_{strategy_id}"):
        title, badge = st.columns([3, 2], vertical_alignment="center")
        title.markdown(f"**{meta.name if meta else name}**")
        badge.badge(_mode_label((latest or {}).get("mode")), color="primary")
        st.caption(meta.description if meta else (name or strategy_id))
        if latest is None:
            st.info("적재된 배분이 없습니다.")
        else:
            _render_allocation_bar(items, key=f"quant_alloc_{strategy_id}")
            st.markdown(_allocation_summary(items, bold=True))
            st.caption(
                f"적용 {latest.get('apply_date') or '—'} · 결정 {latest.get('decision_date') or '—'} · "
                f"적재 {allocation_count}개월"
            )
        st.button(
            "닫기" if selected else "상세 · 백테스트",
            key=f"quant_open_{strategy_id}",
            type="primary" if selected else "tertiary",
            icon=":material/close:" if selected else ":material/arrow_forward:",
            width="stretch",
            on_click=_select_strategy,
            args=(strategy_id,),
        )


def _comparison_chart(
    comparison: pd.DataFrame,
    *,
    strategy_name: str,
    observed_at: Any,
    detail: str,
    sources: tuple[str, ...],
) -> None:
    cumulative = (1.0 + comparison).cumprod() - 1.0
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(x=cumulative.index, y=cumulative["전략"], name=strategy_name,
                   line={"color": PRIMARY, "width": 3})
    )
    figure.add_trace(
        go.Scatter(x=cumulative.index, y=cumulative[_BENCHMARK], name=_BENCHMARK,
                   line={"color": TEXT, "width": 2})
    )
    figure.update_layout(**plotly_layout(height=430), yaxis_tickformat=".0%")
    st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
    source_note(*sources, observed_at=observed_at, detail=detail)

    strategy_metrics = performance_metrics(comparison["전략"])
    benchmark_metrics = performance_metrics(comparison[_BENCHMARK])
    _metric_row(
        tuple(
            (label, display_percent(strategy_metrics.get(key)),
             f"{_BENCHMARK} {display_percent(benchmark_metrics.get(key))}")
            for label, key in (
                ("CAGR", "cagr"),
                ("최대 낙폭", "max_drawdown"),
                ("연환산 변동성", "annualized_volatility"),
                ("누적 수익률", "total_return"),
            )
        )
    )
    source_note(SOURCE_CALC, detail="월간 수익률 기준 · 거래비용·세금·슬리피지 미반영")
    _render_risk_analysis(comparison, strategy_name=strategy_name)


def _render_risk_analysis(comparison: pd.DataFrame, *, strategy_name: str) -> None:
    """수익 곡선과 같은 표본에서 손실 깊이·회복과 위험 조정 성과를 확인한다."""
    st.markdown("##### 위험과 회복")
    risk = risk_metrics(comparison["전략"])
    baseline = risk_metrics(comparison[_BENCHMARK])
    _metric_row(tuple(
        (label, display_percent(risk[name]) if name == "hit_rate" else display_number(risk[name]),
         f"{_BENCHMARK} " + (display_percent(baseline[name]) if name == "hit_rate" else display_number(baseline[name])))
        for label, name in (("Sharpe", "sharpe"), ("Sortino", "sortino"), ("Calmar", "calmar"), ("수익 월 비율", "hit_rate"))
    ))
    st.caption("관측된 월 수익률 기준 · 무위험수익률 연 0% 가정 · 12개 관측 미만 또는 분모가 0이면 —로 표시해요. 수익 월은 수익률 > 0인 달이에요.")
    figure = go.Figure()
    for column, label, color in (("전략", strategy_name, PRIMARY), (_BENCHMARK, _BENCHMARK, TEXT)):
        depths = drawdown_series(comparison[column])
        figure.add_trace(go.Scatter(x=depths.index, y=depths, mode="lines", name=label,
                                   line={"color": color, "width": 2},
                                   hovertemplate="%{x|%Y-%m} · 고점 대비 %{y:.2%}<extra>%{fullData.name}</extra>"))
    figure.update_layout(**plotly_layout(height=270), yaxis_tickformat=".0%", yaxis_title="고점 대비 낙폭")
    st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
    episodes = drawdown_episodes(comparison["전략"])
    if episodes:
        def period_label(value: Any) -> str:
            return pd.Timestamp(value).strftime("%Y-%m") if value is not None else "시작 자산"
        dataframe([{"고점": period_label(row["peak"]), "저점": period_label(row["trough"]),
                    "회복": period_label(row["recovery"]) if row["is_recovered"] else "미회복",
                    "낙폭": row["depth"], "관측 구간 수": row["periods"]}
                   for row in episodes],
                  column_config={"낙폭": st.column_config.NumberColumn(format="percent")})
        st.caption("깊은 낙폭 최대 5개 · 시작 자산은 첫 수익률 적용 전 자산이에요. 기간은 관측 구간 수이며 누락된 달이나 회복 날짜를 추정하지 않아요.")
    else:
        st.caption("관측 구간에서 고점 아래로 내려간 기록이 없어요.")


def _render_monthly_returns_matrix(
    returns_series: pd.Series,
    *,
    title: str = ":material/calendar_month: 연도별 · 월별 수익률 매트릭스",
    key: str = "",
) -> None:
    """월별 수익률을 연도 x 월 매트릭스 표로 렌더링한다."""
    matrix = monthly_returns_matrix(returns_series)
    if matrix.empty:
        return
    st.space("medium")
    st.markdown(f"##### {title}")

    formatted_rows = []
    for yr in matrix.index:
        row_dict: dict[str, Any] = {"연도": str(yr)}
        for col in matrix.columns:
            val = matrix.loc[yr, col]
            if pd.isna(val) or val is None:
                row_dict[col] = "—"
            else:
                pct = float(val) * 100
                sign = "+" if pct > 0 else ""
                row_dict[col] = f"{sign}{pct:.1f}%"
        formatted_rows.append(row_dict)

    dataframe(formatted_rows, key=f"quant_monthly_matrix_{key}" if key else None)
    source_note(SOURCE_CALC, detail="월간 복리 기준 · YTD는 해당 연도 누적 복리 수익률")


def _run_replay(strategy_id: str) -> dict[str, Any] | None:
    """월말 종가를 한 번 받아 룰을 다시 돌린다. 실패는 화면 상태로만 남긴다."""

    with st.spinner("전략 유니버스의 월말 종가를 조회하고 룰을 다시 돌리고 있습니다…"):
        price_result = load_price_history(strategy_tickers(), period="max")
    if not result_status(price_result, empty_text="월말 종가를 확인할 수 없습니다"):
        return None
    replay = replay_strategy_rules(
        strategy_id,
        monthly_close_from_daily(result_payload(price_result, default=None)),
    )
    if not replay.get("months"):
        st.info("룰을 재현할 만한 연속 월말 종가가 부족합니다. 임의 값으로 채우지 않습니다.")
        return None
    return {
        "strategy_id": strategy_id,
        "replay": replay,
        "observed_at": getattr(price_result, "observed_at", None),
    }


def _stored_replay(strategy_id: str) -> dict[str, Any] | None:
    stored = st.session_state.get(_REPLAY_STATE_KEY)
    if isinstance(stored, dict) and stored.get("strategy_id") == strategy_id:
        return stored
    return None


def _render_long_backtest(strategy_id: str, strategy_name: str) -> None:
    st.caption(_GLOSSARY["장기 백테스트"])
    stored = _stored_replay(strategy_id)
    if stored is None:
        st.session_state.pop(_REPLAY_STATE_KEY, None)

    if st.button(
        "장기 백테스트 실행",
        key=f"quant_replay_run__{strategy_id}",
        type="primary",
        icon=":material/play_arrow:",
        width="content",
    ):
        stored = _run_replay(strategy_id)
        if stored is not None:
            st.session_state[_REPLAY_STATE_KEY] = stored

    if stored is None:
        st.info("실행 버튼을 누르면 그때 저장된 월말 종가를 조회합니다. 그 전에는 조회가 없습니다.")
        return

    replay = stored["replay"]
    months = list(replay.get("months") or [])
    returns = replay.get("returns")
    benchmark = replay.get("benchmark_returns")
    if not isinstance(returns, pd.Series):
        returns = pd.Series(dtype="float64")
    if not isinstance(benchmark, pd.Series):
        benchmark = pd.Series(dtype="float64")

    _metric_row(
        (
            ("재현 시작", str(months[0].get("apply_month")) if months else "—", None),
            ("재현 끝", str(months[-1].get("apply_month")) if months else "—", None),
            ("결정 월", f"{int(replay.get('decision_count', 0))}개", None),
            ("실현 월", f"{len(returns)}개", None),
        )
    )
    if replay.get("universe_missing"):
        st.warning(
            "월말 종가에서 빠진 전략 자산: " + ", ".join(replay["universe_missing"])
            + " · 해당 달은 0으로 채우지 않고 제외했습니다."
        )
    comparison = pd.concat(
        [returns.rename("전략"), benchmark.rename(_BENCHMARK)], axis=1, join="inner"
    ).dropna()
    if comparison.empty:
        st.info("재현 수익률과 벤치마크가 겹치는 달이 없어 곡선을 만들지 않습니다.")
    else:
        _comparison_chart(
            comparison,
            strategy_name=f"{strategy_name} · 재현",
            observed_at=comparison.index.max(),
            detail="월 1회 리밸런싱 가정 · CASH 0% · 저장된 운영 기록이 아님",
            sources=(SOURCE_DB, SOURCE_CALC),
        )
        _render_monthly_returns_matrix(
            comparison["전략"],
            title=f":material/calendar_month: {strategy_name} (재현) · 연도별 / 월별 수익률",
            key=f"replay_{strategy_id}",
        )
    skipped = list(replay.get("skipped") or [])
    if skipped:
        with st.expander(f"데이터 부족으로 제외된 달 {len(skipped)}개", icon=":material/info:"):
            dataframe(
                [{"결정 월말": row.get("decision_month"), "사유": row.get("reason")}
                 for row in reversed(skipped)],
                key=f"quant_replay_skipped:{strategy_id}",
            )


def _render_db_period(strategy_id: str, strategy_name: str, allocations: list[dict[str, Any]]) -> None:
    st.caption(_GLOSSARY["DB 적재 구간"])
    _metric_row(
        (
            ("적재 개월", f"{len(allocations)}개월", None),
            ("첫 적용월", str(allocations[0].get("apply_date")) if allocations else "—", None),
            ("최근 적용월", str(allocations[-1].get("apply_date")) if allocations else "—", None),
            ("성과 계산", "가능" if len(allocations) >= 2 else "불가 (2개월 필요)", None),
        )
    )
    if len(allocations) < 2:
        st.info(
            "적재된 적용월이 두 개 미만이라 이 구간의 성과를 만들지 않습니다. "
            "긴 기간은 `장기 백테스트`에서 확인하세요."
        )
        return
    assets = _assets_for_allocations(allocations, include_benchmark=True)
    # 전략이 벤치마크와 같은 자산만 담는 달도 있다(예: SPY 100%). 그때도 성과는 만들 수 있다.
    if _BENCHMARK not in assets:
        st.info("벤치마크 가격을 조회할 수 없어 성과를 계산하지 않습니다.")
        return
    with st.spinner("적재 구간의 전략 자산과 벤치마크 가격을 조회하고 있습니다…"):
        price_result = load_price_history(assets, period="10y")
    if not result_status(price_result, empty_text="적재 구간 성과에 필요한 가격이 없습니다"):
        return
    if getattr(price_result, "message", None):
        st.warning(str(price_result.message))
    # DataFrame payload에 `or {}`를 쓰면 truthiness 평가에서 예외가 난다.
    prices = result_payload(price_result, default=None)
    strategy_returns = _strategy_returns(allocations, {} if prices is None else prices)
    benchmark_returns = _strategy_returns(
        [{**row, "strategy_id": "BENCHMARK", "weights": {_BENCHMARK: 1.0}} for row in allocations],
        {} if prices is None else prices,
    )
    comparison = pd.concat(
        [strategy_returns.rename("전략"), benchmark_returns.rename(_BENCHMARK)],
        axis=1, join="inner",
    ).dropna()
    if comparison.empty:
        st.info("적용일과 실제 가격을 정렬할 수 없어 성과 차트를 만들지 않습니다.")
        return
    _comparison_chart(
        comparison,
        strategy_name=strategy_name,
        observed_at=comparison.index.max(),
        detail="적재된 적용일 사이 buy-and-hold · CASH 0%",
        sources=(SOURCE_DB, SOURCE_CALC),
    )
    _render_monthly_returns_matrix(
        comparison["전략"],
        title=f":material/calendar_month: {strategy_name} (DB 적재) · 연도별 / 월별 수익률",
        key=f"db_{strategy_id}",
    )


def _render_monthly_decisions(strategy_id: str, allocations: list[dict[str, Any]]) -> None:
    st.caption(_GLOSSARY["월별 판단"])
    stored = _stored_replay(strategy_id)
    if stored:
        months = list(stored["replay"].get("months") or [])
        dataframe(
            [
                {
                    "결정 월말": row.get("decision_month"),
                    "적용월": row.get("apply_month"),
                    "모드": _mode_label(row.get("mode")),
                    "배분": _allocation_text(row.get("weights")),
                    "다음 달 실현": row.get("realized_return"),
                    f"{_BENCHMARK} 실현": row.get("benchmark_return"),
                    "제외 사유": row.get("skip_reason") or "—",
                }
                for row in reversed(months)
            ],
            key=f"quant_months:{strategy_id}",
            column_config={
                "다음 달 실현": st.column_config.NumberColumn(format="percent"),
                f"{_BENCHMARK} 실현": st.column_config.NumberColumn(format="percent"),
            },
        )
        source_note(SOURCE_DB, SOURCE_CALC, detail="저장 가격 재현 결과 · 운영 적재 기록이 아님")
    else:
        st.info("`장기 백테스트`를 먼저 실행하면 재현된 월별 판단이 여기에 채워집니다.")

    st.markdown("##### DB 적재 배분")
    if not allocations:
        st.info("적재된 배분 행이 없습니다.")
        return
    dataframe(
        [
            {
                "결정일": row.get("decision_date"),
                "적용일": row.get("apply_date"),
                "모드": _mode_label(row.get("mode")),
                "배분": _allocation_text(row.get("weights")),
                "신호": compact_json(row.get("signals")),
            }
            for row in reversed(allocations)
        ],
        key=f"quant_stored:{strategy_id}",
    )
    source_note(SOURCE_DB, observed_at=allocations[-1].get("apply_date"))


def _render_drift(strategy_id: str, allocations: list[dict[str, Any]]) -> None:
    st.caption(_GLOSSARY["DB 대조"])
    stored = _stored_replay(strategy_id)
    if not stored:
        st.info("`장기 백테스트`를 먼저 실행해야 대조할 재현 배분이 생깁니다.")
        return
    rows = compare_stored_and_replayed_allocations(allocations, stored["replay"])
    matched = [row for row in rows if row["상태"] == "일치"]
    mismatched = [row for row in rows if row["상태"] == "불일치"]
    replay_only = [row for row in rows if row["상태"].startswith("DB 미적재")]
    _metric_row(
        (
            ("일치", f"{len(matched)}개월", None),
            ("불일치", f"{len(mismatched)}개월", None),
            ("DB 미적재", f"{len(replay_only)}개월", None),
            ("DB 적재", f"{len(allocations)}개월", None),
        )
    )
    if mismatched:
        st.error("같은 적용월에서 저장 배분과 재현 배분이 다릅니다. 가격 재조정·적재 시점을 확인하세요.")
    elif matched:
        st.success("적재된 모든 적용월에서 재현 배분이 일치합니다.")
    else:
        st.info("겹치는 적용월이 없어 대조할 수 없습니다.")
    dataframe(
        [
            {**row, "DB 배분": compact_json(row.get("DB 배분")), "재현 배분": compact_json(row.get("재현 배분"))}
            for row in reversed(rows)
        ],
        key=f"quant_drift:{strategy_id}",
    )
    source_note(SOURCE_DB, SOURCE_CALC, detail="적용월 기준 · 1e-6 절대오차")


def _render_simulation(strategy_id: str, allocations: list[dict[str, Any]]) -> None:
    st.caption(_GLOSSARY["미래 경로 추정"])
    basis = view_selector(
        "표본 출처",
        ("장기 백테스트 수익률", "DB 적재 구간 수익률"),
        key=f"quant_simulation_basis:{strategy_id}",
        default="장기 백테스트 수익률",
    )
    run = st.button(
        "경로 추정 실행",
        key=f"quant_simulation_run__{strategy_id}__{basis}",
        type="primary",
        icon=":material/play_arrow:",
        width="content",
    )
    signature = (strategy_id, basis, len(allocations))
    stored = st.session_state.get(_SIMULATION_STATE_KEY)
    if not isinstance(stored, dict) or stored.get("signature") != signature:
        stored = None
        st.session_state.pop(_SIMULATION_STATE_KEY, None)

    failed = False
    if run:
        observed_at: Any = None
        returns: pd.Series = pd.Series(dtype="float64")
        if basis == "장기 백테스트 수익률":
            replay_state = _run_replay(strategy_id)
            if replay_state is None:
                return
            st.session_state[_REPLAY_STATE_KEY] = replay_state
            candidate = replay_state["replay"].get("returns")
            returns = candidate if isinstance(candidate, pd.Series) else returns
            observed_at = replay_state.get("observed_at")
        else:
            if len(allocations) < 2:
                st.info("적재된 적용월이 두 개 미만입니다.")
                return
            assets = _assets_for_allocations(allocations, include_benchmark=False)
            if not assets:
                st.info("조회 가능한 전략 자산이 없습니다.")
                return
            with st.spinner("적재 구간 가격을 조회하고 있습니다…"):
                price_result = load_price_history(assets, period="10y")
            if not result_status(price_result, empty_text="필요한 가격이 없습니다"):
                return
            payload_prices = result_payload(price_result, default=None)
            returns = _strategy_returns(
                allocations, {} if payload_prices is None else payload_prices
            )
            observed_at = getattr(price_result, "observed_at", None)

        if len(returns) < _MONTE_CARLO_MIN_OBSERVATIONS:
            st.info(
                f"실제 월수익률 표본이 {len(returns)}개입니다. "
                f"{_MONTE_CARLO_MIN_OBSERVATIONS}개월 미만은 재배열하지 않습니다."
            )
            failed = True
        else:
            fan = monte_carlo_fan(returns)
            if not isinstance(fan, pd.DataFrame) or fan.empty:
                st.info("표본이 충분하지 않아 경로 분포를 만들지 않습니다.")
                failed = True
            else:
                stored = {
                    "signature": signature,
                    "fan": fan,
                    "observed_at": observed_at,
                    "sample_size": len(returns),
                    "basis": basis,
                }
                st.session_state[_SIMULATION_STATE_KEY] = stored

    if stored is not None:
        fan = stored["fan"]
        figure = go.Figure()
        for column, label, color, width in (
            ("p10", "하위 10%", DOWN, 1),
            ("p25", "하위 25%", MUTED, 1),
            ("p50", "중앙", PRIMARY, 3),
            ("p75", "상위 25%", MUTED, 1),
            ("p90", "상위 10%", UP, 1),
        ):
            if column in fan:
                figure.add_trace(
                    go.Scatter(x=fan.index, y=fan[column] - 1.0, name=label,
                               line={"color": color, "width": width})
                )
        figure.update_layout(
            **plotly_layout(height=430),
            xaxis_title="향후 개월",
            yaxis_title="누적 수익률",
            yaxis_tickformat=".0%",
        )
        st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
        source_note(
            SOURCE_DB, SOURCE_CALC,
            observed_at=stored.get("observed_at"),
            detail=(
                f"{stored.get('basis')} 표본 {stored.get('sample_size')}개월을 고정 seed로 "
                "재배열 · 예측·보장 아님"
            ),
        )
    elif not failed:
        st.info("실행 버튼을 누르기 전에는 저장 데이터 조회도 계산도 하지 않습니다.")


def _render_all_backtest(strategies: list[dict[str, Any]]) -> None:
    """등록된 전략 전부를 한 번에 재현해 같은 축에서 비교한다."""

    st.caption(
        "월말 종가를 **한 번만** 내려받아 등록된 전략 전부를 같은 기간·같은 규칙으로 "
        "재현합니다. 결과는 세션 메모리에만 남습니다."
    )
    run = st.button(
        "전체 백테스트 실행",
        key="quant_all_replay_run",
        type="primary",
        icon=":material/play_arrow:",
        width="content",
    )
    stored = st.session_state.get(_ALL_REPLAY_STATE_KEY)

    if run:
        with st.spinner("월말 종가를 조회하고 전략 전체를 재현하고 있습니다…"):
            price_result = load_price_history(strategy_tickers(), period="max")
        if not result_status(price_result, empty_text="월말 종가를 확인할 수 없습니다"):
            return
        frame = monthly_close_from_daily(result_payload(price_result, default=None))
        replays: dict[str, Any] = {}
        for row in strategies:
            strategy_id = str(row.get("id"))
            if strategy_id not in strategy_ids():
                continue
            replay = replay_strategy_rules(strategy_id, frame)
            if replay.get("months"):
                replays[strategy_id] = replay
        if not replays:
            st.info("재현 가능한 전략이 없습니다.")
            return
        stored = {"replays": replays, "observed_at": getattr(price_result, "observed_at", None)}
        st.session_state[_ALL_REPLAY_STATE_KEY] = stored

    if not isinstance(stored, dict):
        st.info("아직 실행하지 않았습니다. 실행 전에는 저장 데이터 조회가 없습니다.")
        return

    replays = stored["replays"]
    benchmark = next(
        (
            replay["benchmark_returns"]
            for replay in replays.values()
            if isinstance(replay.get("benchmark_returns"), pd.Series)
            and not replay["benchmark_returns"].empty
        ),
        pd.Series(dtype="float64"),
    )

    curves: dict[str, pd.Series] = {}
    summary: list[dict[str, Any]] = []
    for strategy_id, replay in replays.items():
        returns = replay.get("returns")
        if not isinstance(returns, pd.Series) or returns.empty:
            continue
        curves[strategy_id] = returns
        metrics = performance_metrics(returns)
        latest = replay.get("latest") or {}
        meta = strategy_label(strategy_id)
        summary.append(
            {
                "전략": meta.name if meta else strategy_id,
                "재현 개월": len(returns),
                "CAGR": metrics.get("cagr"),
                "최대 낙폭": metrics.get("max_drawdown"),
                "연환산 변동성": metrics.get("annualized_volatility"),
                "누적 수익률": metrics.get("total_return"),
                "이번 달 모드": _mode_label(latest.get("mode")),
                "이번 달 배분": _allocation_text(latest.get("weights")),
            }
        )
    if not summary:
        st.info("비교할 재현 수익률이 없습니다.")
        return

    if not benchmark.empty:
        metrics = performance_metrics(benchmark)
        summary.append(
            {
                "전략": f"{_BENCHMARK} (벤치마크)",
                "재현 개월": len(benchmark),
                "CAGR": metrics.get("cagr"),
                "최대 낙폭": metrics.get("max_drawdown"),
                "연환산 변동성": metrics.get("annualized_volatility"),
                "누적 수익률": metrics.get("total_return"),
                "이번 달 모드": "—",
                "이번 달 배분": f"{_BENCHMARK} 100%",
            }
        )

    figure = go.Figure()
    palette = CHART_COLORS
    for index, (strategy_id, returns) in enumerate(sorted(curves.items())):
        meta = strategy_label(strategy_id)
        cumulative = (1.0 + returns).cumprod() - 1.0
        figure.add_trace(
            go.Scatter(
                x=cumulative.index, y=cumulative,
                name=meta.name if meta else strategy_id,
                line={"color": palette[index % len(palette)], "width": 2},
                customdata=[[strategy_id]] * len(cumulative),
                hovertemplate="%{y:.1%}<extra></extra>",
            )
        )
    if not benchmark.empty:
        cumulative = (1.0 + benchmark).cumprod() - 1.0
        figure.add_trace(
            go.Scatter(x=cumulative.index, y=cumulative, name=_BENCHMARK,
                       line={"color": TEXT, "width": 2, "dash": "dot"})
        )
    figure.update_layout(**plotly_layout(height=460), yaxis_tickformat=".0%")
    state = st.plotly_chart(
        figure,
        width="stretch",
        config={"displaylogo": False},
        key="quant_all_curve",
        on_select="rerun",
        selection_mode="points",
    )
    picked = plot_selection_key(state)
    if picked and picked in strategy_ids() and st.session_state.get(_SELECTED_KEY) != picked:
        st.session_state[_SELECTED_KEY] = picked
        st.rerun()
    st.caption("곡선의 점을 클릭하면 그 전략의 상세가 열립니다.")
    source_note(
        SOURCE_DB, SOURCE_CALC,
        observed_at=stored.get("observed_at"),
        detail="전 전략 동일 기간·동일 규칙 재현 · 거래비용·세금 미반영",
    )
    dataframe(
        sorted(summary, key=lambda row: -(row["CAGR"] if row["CAGR"] is not None else -9.9)),
        key="quant_all_summary",
        column_config={
            "CAGR": st.column_config.NumberColumn(format="percent"),
            "최대 낙폭": st.column_config.NumberColumn(format="percent"),
            "연환산 변동성": st.column_config.NumberColumn(format="percent"),
            "누적 수익률": st.column_config.NumberColumn(format="percent"),
        },
    )
    source_note(SOURCE_CALC, detail="정렬 기준 CAGR · 결측은 빈 셀로 유지")


def _render_selected_strategy_detail(
    strategy_id: str,
    meta_row: dict[str, Any],
    allocations: list[dict[str, Any]],
) -> None:
    """카드에서 고른 전략의 근거만 상세 화면에 렌더링한다."""

    catalog = strategy_label(strategy_id)
    st.caption(
        f"{catalog.description if catalog else ''} · "
        f"출처 {meta_row.get('description') or '—'}"
    )
    if strategy_id not in strategy_ids():
        st.warning(
            f"`{strategy_id}`는 계산 함수가 등록되지 않은 전략입니다. 저장된 배분만 볼 수 있습니다. "
            f"재현 가능한 전략 · {', '.join(strategy_ids())}"
        )
        _render_monthly_decisions(strategy_id, allocations)
        return

    detail_view = view_selector(
        "상세 보기",
        _DETAIL_VIEWS,
        key=f"quant_detail_view:{strategy_id}",
        default="장기 백테스트",
    )
    name = str(meta_row.get("name") or strategy_id)
    if detail_view == "장기 백테스트":
        _render_long_backtest(strategy_id, name)
    elif detail_view == "DB 적재 구간":
        _render_db_period(strategy_id, name, allocations)
    elif detail_view == "월별 판단":
        _render_monthly_decisions(strategy_id, allocations)
    elif detail_view == "DB 대조":
        _render_drift(strategy_id, allocations)
    else:
        _render_simulation(strategy_id, allocations)


def _select_allocation_month(month: str) -> None:
    """월 이동 버튼은 적재된 적용월 하나만 선택한다."""

    st.session_state[_MONTH_KEY] = month


def _month_heading(month: str) -> str:
    """적용월 ISO 문자열을 화면에서 읽기 쉬운 월 제목으로 바꾼다."""

    try:
        parsed = date.fromisoformat(month)
    except ValueError:
        return "적재된 전략 판단"
    return f"{parsed.year}년 {parsed.month}월 전략 판단"


st.badge("전략 워크스페이스", icon=":material/monitoring:", color="primary")
st.title("퀀트 전략 연구소")

strategy_result = load_strategy_data()
payload = result_payload(strategy_result, default={}) or {}
strategies = list(payload.get("strategies", []))
allocations = list(payload.get("allocations", []))
if not result_status(strategy_result, empty_text="저장된 전략 또는 배분이 없습니다") or not strategies:
    st.stop()

by_strategy: dict[str, list[dict[str, Any]]] = {}
for row in allocations:
    by_strategy.setdefault(str(row.get("strategy_id")), []).append(row)
for rows in by_strategy.values():
    rows.sort(key=lambda row: str(row.get("apply_date") or ""))

available_months = sorted({
    str(row.get("apply_date") or "")[:10]
    for row in allocations
    if str(row.get("apply_date") or "")[:10]
})
latest_month = available_months[-1] if available_months else ""
if st.session_state.get(_MONTH_KEY) not in available_months:
    st.session_state[_MONTH_KEY] = latest_month
selected_month = str(st.session_state.get(_MONTH_KEY) or "")
selected_month_index = available_months.index(selected_month) if selected_month in available_months else -1

previous_month = available_months[selected_month_index - 1] if selected_month_index > 0 else None
next_month = (
    available_months[selected_month_index + 1]
    if 0 <= selected_month_index < len(available_months) - 1
    else None
)
previous, current, next_ = st.columns(3, vertical_alignment="center")
with previous:
    st.button(
        "이전 달",
        key="quant_previous_month",
        icon=":material/chevron_left:",
        disabled=previous_month is None,
        on_click=_select_allocation_month,
        args=(previous_month,) if previous_month else (),
    )
with current:
    st.button(
        "이번 달",
        key="quant_current_month",
        icon=":material/today:",
        disabled=not latest_month or selected_month == latest_month,
        on_click=_select_allocation_month,
        args=(latest_month,) if latest_month else (),
    )
with next_:
    st.button(
        "다음 달",
        key="quant_next_month",
        icon=":material/chevron_right:",
        icon_position="right",
        disabled=next_month is None,
        on_click=_select_allocation_month,
        args=(next_month,) if next_month else (),
    )

st.markdown(f"### {_month_heading(selected_month)}")

st.html("""
    <style>
    /* OSS 운영 대시보드처럼 카드 안의 상태·배분·행동 순서를 고정한다. */
    div[class*="st-key-quant_card_"] {
        border-radius: 16px !important;
        border-color: var(--color-border-default, var(--border-color)) !important;
        background: var(--color-bg-surface, var(--background-color)) !important;
        box-shadow: none !important;
    }
    div[class*="st-key-quant_card_"] [data-testid="stCaptionContainer"] {
        color: var(--color-text-secondary, var(--text-color)) !important;
        min-height: 2.8em;
    }
    div[class*="st-key-quant_card_"] [data-testid="stPlotlyChart"] {
        background: var(--color-bg-subtle, var(--secondary-background-color));
        border-radius: 10px;
        padding: 4px 8px 0;
    }
    div[class*="st-key-quant_card_"] [data-testid="stButton"] {
        border-top: 1px solid var(--color-border-default, var(--border-color));
        margin-top: 4px;
        padding-top: 8px;
    }
    div[class*="st-key-quant_card_"] [data-testid="stButton"] > button {
        justify-content: space-between;
    }

    /* 한 컨테이너 안에서 카드가 연속으로 흐르도록 해 빈 칸 없이 재배치한다. */
    div[class*="st-key-quant_strategy_grid"] {
        display: grid !important;
        grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
        gap: 16px !important;
    }
    div[class*="st-key-quant_strategy_grid"] > [data-testid="stLayoutWrapper"] {
        width: auto !important;
        min-width: 0 !important;
    }

    /* 사이드바가 열린 중간 폭에서는 카드 두 장씩 읽기 좋게 배치한다. */
    @media (min-width: 641px) and (max-width: 1160px) {
        div[class*="st-key-quant_strategy_grid"] {
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
        }
    }
    @media (max-width: 640px) {
        div[class*="st-key-quant_strategy_grid"] {
            grid-template-columns: minmax(0, 1fr) !important;
        }
    }
    </style>
""")

selected_id = st.session_state.get(_SELECTED_KEY)
with st.container(
    horizontal=True,
    wrap=True,
    vertical_alignment="top",
    gap="small",
    key="quant_strategy_grid",
):
    for row in strategies:
        strategy_id = str(row.get("id"))
        rows = by_strategy.get(strategy_id, [])
        selected_allocation = next(
            (item for item in reversed(rows) if str(item.get("apply_date") or "")[:10] == selected_month),
            None,
        )
        with st.container(key=f"quant_strategy_slot_{strategy_id}"):
            _render_strategy_card(
                strategy_id,
                name=str(row.get("name") or strategy_id),
                latest=selected_allocation,
                allocation_count=len(rows),
                selected=selected_id == strategy_id,
            )
source_note(SOURCE_DB, observed_at=getattr(strategy_result, "observed_at", None))

st.space("large")
st.markdown("### 전체 백테스트")
_render_all_backtest(strategies)

# 카드 버튼의 콜백은 이번 실행에서 선택값을 갱신할 수 있으므로, 상세를 열기 직전에 다시 읽는다.
selected_id = st.session_state.get(_SELECTED_KEY)
if selected_id:
    meta_row = next((row for row in strategies if str(row.get("id")) == selected_id), None)
    if meta_row is not None:
        selected_allocations = by_strategy.get(selected_id, [])
        catalog = strategy_label(selected_id)
        open_detail(
            f"{catalog.name if catalog else meta_row.get('name') or selected_id} 상세",
            lambda: _render_selected_strategy_detail(selected_id, meta_row, selected_allocations),
            surface=detail_surface(),
            icon=":material/query_stats:",
            width="large",
            on_dismiss=lambda: st.session_state.pop(_SELECTED_KEY, None),
        )
