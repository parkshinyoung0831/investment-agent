"""execution이 저장한 계좌·보유 스냅샷을 표시하는 읽기 전용 포트폴리오 화면."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go
import streamlit as st

from investment_agent.dashboard.calculations import (
    covariance_to_correlation,
    rebalance_portfolio,
)
from investment_agent.dashboard.db import load_latest_account_snapshot, load_latest_target
from investment_agent.dashboard.components.theme import dashboard_palette, plotly_layout
from investment_agent.dashboard.components.ui import (
    SOURCE_CALC,
    SOURCE_DB,
    compact_json,
    dataframe,
    display_number,
    display_money,
    display_percent,
    result_payload,
    result_status,
    source_note,
    view_selector,
)


_COLORS = dashboard_palette()
PRIMARY = _COLORS.primary
MUTED = _COLORS.muted

st.html("""
<style>
div[class*="st-key-portfolio_summary_metrics"] [data-testid="stMetricValue"] {
    font-size: 1.15rem !important;
}
div[class*="st-key-portfolio_summary_metrics"] [data-testid="stMetricLabel"] {
    font-size: .82rem !important;
}
</style>
""")


def _first_number(mapping: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = mapping.get(key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            continue
    return None


def _normalise_holding(row: dict[str, Any]) -> dict[str, Any] | None:
    ticker = str(row.get("ticker") or "").upper()
    if not ticker and row.get("security_id") is not None:
        ticker = f"SECURITY:{row['security_id']}"
    if not ticker:
        return None
    quantity = _first_number(row, ("quantity",))
    price = _first_number(row, ("market_price",))
    market_value = _first_number(row, ("market_value",))
    if market_value is None and quantity is not None and price is not None:
        market_value = quantity * price
    return {
        "ticker": ticker,
        "quantity": quantity,
        "price": price,
        "market_value": market_value,
        "weight": _first_number(row, ("weight",)),
    }


def _account_values(account: dict[str, Any]) -> dict[str, Any]:
    raw_holdings = account.get("holdings") or account.get("positions") or account.get("items") or []
    holdings = [
        item
        for row in raw_holdings
        if isinstance(row, dict)
        if (item := _normalise_holding(row))
    ]
    cash = _first_number(account, ("cash",))
    market_values = [row["market_value"] for row in holdings]
    priced_all = bool(holdings) and all(value is not None for value in market_values)
    holdings_value = sum(market_values) if priced_all else None
    total_value = _first_number(account, ("equity",))
    if total_value is None and holdings_value is not None and cash is not None:
        total_value = holdings_value + cash
    return {
        "holdings": holdings,
        "cash": cash,
        "priced_all": priced_all,
        "holdings_value": holdings_value,
        "total_value": total_value,
    }


st.title("포트폴리오")

account_result = load_latest_account_snapshot()
account_observed_at = getattr(account_result, "observed_at", None)
if not result_status(account_result, empty_text="저장된 계좌 스냅샷이 없습니다"):
    with st.container(border=True):
        st.metric("계좌 스냅샷", "없음")
        st.caption("execution이 저장한 계좌 스냅샷이 생성된 뒤 표시됩니다.")
        source_note(SOURCE_DB)
    account_available = False
    account: dict[str, Any] = {}
else:
    account_available = True
    account = result_payload(account_result, default={}) or {}
    with st.container(border=True):
        status = str(getattr(account_result, "status", "error"))
        st.metric("계좌 스냅샷", "저장됨" if status == "ok" else "조회 실패")
        st.caption(getattr(account_result, "message", None) or "execution 저장 원장의 읽기 전용 스냅샷")
        source_note(SOURCE_DB, observed_at=account_observed_at)

view = view_selector(
    "포트폴리오 보기",
    ("계좌 요약", "보유 종목", "리밸런싱", "리스크"),
    key="portfolio_adaptive_view",
    default="계좌 요약",
)

if not account_available and view != "리스크":
    st.info("계좌 요약·보유·리밸런싱은 저장된 계좌 스냅샷이 있어야 표시할 수 있어요.")
else:
    values = _account_values(account)
    holdings = values["holdings"]
    cash = values["cash"]
    total_value = values["total_value"]
    priced_all = values["priced_all"]

    if view == "계좌 요약":
        with st.container(key="portfolio_summary_metrics"):
            metric_columns = st.columns(4, gap="small")
            labels = (
                ("총자산", total_value, None, None),
                ("예수금", cash, None, None),
                ("보유 평가액", values["holdings_value"], None, None),
                ("보유 종목 수", len(holdings), None, None),
            )
            for column, (label, usd_value, krw_value, rate) in zip(metric_columns, labels):
                with column:
                    st.metric(label, display_money(usd_value) if label != "보유 종목 수" else str(usd_value), border=True)
                    if krw_value is not None:
                        st.caption(f"원화 {display_money(krw_value, currency='KRW')}", text_alignment="right")
                    if rate is not None:
                        st.caption(f"수익률 {display_percent(rate)}", text_alignment="right")
        st.caption(f"실행 모드 · {account.get('execution_mode') or '—'} · 스냅샷 시각 · {account.get('captured_at') or '—'}")
        st.caption("스냅샷에 저장되지 않은 매입원가·손익·환율은 추정하지 않습니다.")
        source_note(SOURCE_DB, observed_at=account_observed_at)

    elif view == "보유 종목":
        if not holdings:
            st.info("실제 미국 주식 보유 행이 없습니다.")
        else:
            display_holdings = [
                {
                    "종목": row.get("ticker"),
                    "수량": row.get("quantity"),
                    "현재가": row.get("price"),
                    "평가금액(USD)": row.get("market_value"),
                    "비중": display_percent(row.get("weight")),
                }
                for row in holdings
            ]
            dataframe(display_holdings, key="portfolio_holdings")
            if priced_all:
                tree_rows = [row for row in holdings if row["market_value"] and row["market_value"] > 0]
                if tree_rows:
                    labels = [row["ticker"] for row in tree_rows]
                    amounts = [row["market_value"] for row in tree_rows]
                    figure = go.Figure(
                        go.Treemap(
                            labels=labels,
                            parents=[""] * len(labels),
                            values=amounts,
                            texttemplate="%{label}<br>%{value:$,.0f}",
                            marker={
                                "colors": amounts,
                                "colorscale": [
                                    [0.0, _COLORS.surface_subtle],
                                    [0.45, MUTED],
                                    [1.0, PRIMARY],
                                ],
                                "showscale": False,
                                "line": {"color": _COLORS.background, "width": 1},
                            },
                            hovertemplate="%{label}<br>평가액 %{value:$,.2f}<extra></extra>",
                        )
                    )
                    figure.update_layout(**plotly_layout(height=430))
                    st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
            else:
                st.info("일부 종목의 fresh price가 없어 트리맵을 만들지 않습니다.")
            source_note(SOURCE_DB, detail="면적=저장된 평가금액; 실시간 가격·손익을 추정하지 않음")

    elif view == "리밸런싱":
        target_result = load_latest_target()
        if result_status(target_result, empty_text="최신 AI 승인 목표 비중이 없습니다"):
            target = result_payload(target_result, default={}) or {}
            risk_decision = target.get("risk_decision") if isinstance(target.get("risk_decision"), dict) else {}
            approved_weights = risk_decision.get("approved_weights") if isinstance(risk_decision.get("approved_weights"), dict) else {}
            if not approved_weights:
                st.info("최신 risk decision에 approved_weights가 없어 계산하지 않습니다.")
            else:
                prices = {row["ticker"]: row.get("price") for row in holdings if row.get("price") is not None}
                guide = rebalance_portfolio(holdings, cash, approved_weights, prices)
                guide_rows = (guide.get("rows") or guide.get("positions") or []) if isinstance(guide, dict) else guide or []
                if not guide_rows:
                    st.info("필요한 평가금액 또는 가격이 부족해 리밸런싱 가이드를 만들지 않습니다.")
                else:
                    formatted_rows = []
                    for row in guide_rows:
                        weight_gap = row.get("weight_gap")
                        if weight_gap is None:
                            weight_gap = row.get("weight_difference")
                        adjustment_value = row.get("adjustment_value")
                        if adjustment_value is None:
                            adjustment_value = row.get("adjustment_amount")
                        guide_quantity = row.get("guide_quantity_delta")
                        if guide_quantity is None:
                            guide_quantity = row.get("quantity_delta")
                        formatted_rows.append(
                            {
                                "종목": row.get("ticker") or row.get("symbol"),
                                "실제 보유": row.get("current_quantity"),
                                "현재가": row.get("current_price"),
                                "실제 비중": display_percent(row.get("actual_weight")),
                                "최종 목표 비중": display_percent(row.get("target_weight")),
                                "비중 차이": display_percent(weight_gap, signed=True),
                                "조정 필요 금액": adjustment_value,
                                "가이드 수량": guide_quantity,
                                "계산 상태": row.get("data_status") or "계산 가능",
                            }
                        )
                    chart_tickers = [str(row.get("ticker") or row.get("symbol")) for row in guide_rows]
                    actual_pcts = [float(row.get("actual_weight") or 0.0) * 100 for row in guide_rows]
                    target_pcts = [float(row.get("target_weight") or 0.0) * 100 for row in guide_rows]

                    fig = go.Figure()
                    fig.add_trace(
                        go.Bar(
                            x=chart_tickers,
                            y=actual_pcts,
                            name="현재 보유 비중",
                            marker_color=MUTED,
                            text=[f"{v:.1f}%" for v in actual_pcts],
                            textposition="auto",
                        )
                    )
                    fig.add_trace(
                        go.Bar(
                            x=chart_tickers,
                            y=target_pcts,
                            name="RiskGate 최종 목표",
                            marker_color=PRIMARY,
                            text=[f"{v:.1f}%" for v in target_pcts],
                            textposition="auto",
                        )
                    )
                    layout = plotly_layout(height=320)
                    layout["barmode"] = "group"
                    layout["yaxis_ticksuffix"] = "%"
                    layout["margin"] = {"l": 20, "r": 20, "t": 30, "b": 20}
                    fig.update_layout(**layout)
                    st.plotly_chart(
                        fig,
                        width="stretch",
                        config={"displaylogo": False},
                        key="portfolio_rebalance_bar_chart",
                    )

                    dataframe(formatted_rows, key="portfolio_rebalance")
                    source_note(
                        SOURCE_DB,
                        SOURCE_CALC,
                        observed_at=risk_decision.get("decided_at"),
                        detail="가이드 수량은 화면 계산이며 주문 객체를 생성하지 않음",
                    )

    elif view == "리스크":
        if not account_available:
            st.info(
                "저장된 Optimizer·RiskGate 결정은 계좌 스냅샷 없이도 볼 수 있어요. "
                "현재 비중 비교는 저장된 스냅샷이 있을 때만 표시합니다.",
                icon=":material/database:",
            )
        target_result = load_latest_target()
        if result_status(target_result, empty_text="최신 AI 승인 목표 비중이 없습니다"):
            target = result_payload(target_result, default={}) or {}
            risk_decision = target.get("risk_decision") if isinstance(target.get("risk_decision"), dict) else {}
            proposal = target.get("proposal") if isinstance(target.get("proposal"), dict) else {}
            approved_weights = risk_decision.get("approved_weights") if isinstance(risk_decision.get("approved_weights"), dict) else {}
            positive_values = [row.get("market_value") for row in holdings if row.get("market_value") is not None]
            actual_concentration = max(positive_values) / total_value if positive_values and total_value else None
            cash_weight = cash / total_value if cash is not None and total_value else None
            target_concentration = max(
                (float(weight) for symbol, weight in approved_weights.items() if symbol != "CASH"),
                default=None,
            )
            metadata = proposal.get("metadata") if isinstance(proposal.get("metadata"), dict) else {}
            risk_metrics = risk_decision.get("metrics") if isinstance(risk_decision.get("metrics"), dict) else {}
            policy_limits = risk_metrics.get("policy_limits") if isinstance(risk_metrics.get("policy_limits"), dict) else {}
            saved_limit = next(
                (
                    metadata.get(key)
                    for key in (
                        "max_single_name_weight",
                        "max_position_weight",
                        "construction_policy_max_weight",
                    )
                    if metadata.get(key) is not None
                ),
                None,
            )
            with st.container(horizontal=True):
                st.metric("현금 비중", display_percent(cash_weight), border=True)
                st.metric("실제 단일종목 집중도", display_percent(actual_concentration), border=True)
                st.metric("승인 목표 최대 비중", display_percent(target_concentration), border=True)
                st.metric("저장된 단일종목 한도", display_percent(saved_limit), border=True)
            if saved_limit is None:
                st.caption("proposal metadata에 한도가 없어 임의 한도를 사용하지 않습니다.")
            optimizer_weights = proposal.get("weights") if isinstance(proposal.get("weights"), dict) else {}
            if optimizer_weights and approved_weights:
                symbols = sorted(set(optimizer_weights) | set(approved_weights))
                figure = go.Figure()
                if priced_all and total_value and cash is not None:
                    actual_weights = {
                        str(row["ticker"]): float(row["market_value"]) / float(total_value)
                        for row in holdings
                        if row.get("ticker") and row.get("market_value") is not None
                    }
                    actual_weights["CASH"] = float(cash) / float(total_value)
                    figure.add_trace(
                        go.Bar(
                            x=symbols,
                            y=[actual_weights.get(symbol, 0.0) * 100 for symbol in symbols],
                            name="현재 비중",
                            marker_color=MUTED,
                        )
                    )
                figure.add_trace(
                    go.Bar(
                        x=symbols,
                        y=[float(optimizer_weights.get(symbol, 0.0)) * 100 for symbol in symbols],
                        name="Optimizer 목표",
                        marker_color=_COLORS.secondary_text,
                    )
                )
                figure.add_trace(
                    go.Bar(
                        x=symbols,
                        y=[float(approved_weights.get(symbol, 0.0)) * 100 for symbol in symbols],
                        name="RiskGate 최종",
                        marker_color=PRIMARY,
                    )
                )
                layout = plotly_layout(height=330)
                layout["barmode"] = "group"
                layout["yaxis_ticksuffix"] = "%"
                figure.update_layout(**layout)
                st.subheader(":material/compare_arrows: 비중 결정 비교")
                st.plotly_chart(
                    figure,
                    width="stretch",
                    config={"displaylogo": False},
                    key="portfolio_risk_weight_comparison",
                )
                if not (priced_all and total_value and cash is not None):
                    st.caption("계좌 가격 또는 예수금이 완전하지 않아 현재 비중은 비교에서 제외했습니다.")
            optimizer_metrics = metadata.get("optimizer") if isinstance(metadata.get("optimizer"), dict) else {}
            covariance = (
                optimizer_metrics.get("covariance")
                if isinstance(optimizer_metrics.get("covariance"), dict)
                else {}
            )
            covariance_symbols = covariance.get("symbols")
            correlation = covariance_to_correlation(covariance.get("matrix"))
            if (
                correlation
                and isinstance(covariance_symbols, list)
                and len(covariance_symbols) == len(correlation)
            ):
                st.subheader(":material/grid_on: 최적화 입력 상관관계")
                correlation_figure = go.Figure(
                    go.Heatmap(
                        z=correlation,
                        x=[str(symbol) for symbol in covariance_symbols],
                        y=[str(symbol) for symbol in covariance_symbols],
                        zmin=-1.0,
                        zmax=1.0,
                        colorscale=[
                            [0.0, _COLORS.surface_subtle],
                            [0.5, _COLORS.border_strong],
                            [1.0, PRIMARY],
                        ],
                        text=[[f"{value:.2f}" for value in row] for row in correlation],
                        texttemplate="%{text}",
                        hovertemplate="%{y} × %{x}<br>상관계수 %{z:.3f}<extra></extra>",
                        colorbar={"title": "상관"},
                    )
                )
                correlation_figure.update_layout(**plotly_layout(height=420))
                st.plotly_chart(
                    correlation_figure,
                    width="stretch",
                    config={"displaylogo": False},
                    key="portfolio_optimizer_correlation",
                )
                st.caption(
                    f"{covariance.get('method') or '공분산'} · "
                    f"{covariance.get('horizon_days') or '—'}거래일 보유기간 · "
                    f"관측 {covariance.get('observation_count') or '—'}개"
                )
            elif optimizer_metrics:
                st.caption("이전 제안에는 상관관계 행렬이 저장되지 않아 히트맵을 표시하지 않아요.")
            if not risk_metrics:
                st.info("이전 risk decision에는 승인 시점 위험 측정값이 저장되지 않았습니다.")
            else:
                st.subheader(":material/shield: 승인 시점 위험 측정값")
                with st.container(horizontal=True):
                    st.metric(
                        "포트폴리오 변동성",
                        f"{display_percent(risk_metrics.get('portfolio_volatility'))} / "
                        f"{display_percent(policy_limits.get('max_portfolio_volatility'))}",
                        border=True,
                    )
                    st.metric(
                        "SPY beta",
                        f"{display_number(risk_metrics.get('portfolio_beta'))} / "
                        f"{display_number(policy_limits.get('max_abs_beta'))}",
                        border=True,
                    )
                    st.metric(
                        "최대 쌍별 상관",
                        f"{display_number(risk_metrics.get('max_pairwise_correlation'))} / "
                        f"{display_number(policy_limits.get('max_pairwise_correlation'))}",
                        border=True,
                    )
                    st.metric(
                        "회전율",
                        f"{display_percent(risk_metrics.get('turnover'))} / "
                        f"{display_percent(policy_limits.get('max_turnover'))}",
                        border=True,
                    )
                market_risk = risk_metrics.get("market_risk") if isinstance(risk_metrics.get("market_risk"), dict) else {}
                dataframe(
                    [
                        {"측정값": "최대 낙폭", "실제값": display_percent(risk_metrics.get("drawdown_fraction")), "한도": "판정 참고값"},
                        {"측정값": "집중도 HHI", "실제값": display_number(risk_metrics.get("concentration_hhi")), "한도": display_number(policy_limits.get("max_concentration_hhi"))},
                        {"측정값": "가격 관측 수", "실제값": market_risk.get("observation_count") or "—", "한도": "최소 60 거래일"},
                        {"측정값": "가격 관측 구간", "실제값": f"{market_risk.get('first_trade_date') or '—'} ~ {market_risk.get('last_trade_date') or '—'}", "한도": market_risk.get("benchmark_symbol") or "SPY"},
                    ],
                    key="portfolio_risk_snapshot",
                )
            st.caption(
                f"risk policy · {risk_decision.get('policy_key') or '—'} / {risk_decision.get('policy_version') or '—'} · "
                f"저장 위반 규칙 · {compact_json(risk_decision.get('violations') or [])}"
            )
            source_note(
                *(
                    (SOURCE_DB, SOURCE_CALC)
                ),
                observed_at=risk_decision.get("decided_at"),
                detail="위험값은 승인 시점 원장값이며 화면에서 다시 계산하지 않음",
            )
