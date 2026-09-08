"""13F 거장 레이더 — 매니저별 포트폴리오 구성을 먼저 보고, 고른 매니저만 파고든다.

13F는 **분기말 long equity 장부**다. 숏·파생·채권·해외 상장·비상장 자산은 애초에
들어오지 않고, 제출까지 최대 45일이 걸린다. 그래서 이 화면의 모든 비중은 '보고된 장부
안에서의 비중'이며, 매니저 자산 전체의 배분이 아니다 — 이 한계를 화면에 상시 표시한다.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from investment_agent.dashboard.calculations import (
    finite_number,
    guru_portfolio,
    guru_position_changes,
)
from investment_agent.reporting.readers.dashboard import load_guru_data
from investment_agent.dashboard.components.theme import dashboard_palette, plotly_layout
from investment_agent.dashboard.components.ui import (
    SOURCE_CALC,
    SOURCE_DB,
    dataframe,
    detail_layout,
    detail_surface,
    display_percent,
    open_detail,
    result_payload,
    result_status,
    source_note,
    view_selector,
)


_COLORS = dashboard_palette()


_SELECTED_KEY = "guru_selected_manager"
_CARD_COLUMNS = 4
_DETAIL_VIEWS = ("포트폴리오", "포지션 변화")


def _manager_investment_style(manager: dict[str, Any]) -> str | None:
    """대표 매니저의 실제 운용 성격을 카드 제목 옆에 짧게 표시한다."""

    identity = " ".join(
        str(manager.get(field) or "")
        for field in ("name_ko", "name", "fund_name_ko", "fund_name")
    ).lower()
    styles = (
        ("버핏", "가치투자"),
        ("berkshire", "가치투자"),
        ("애크먼", "행동주의 가치투자"),
        ("ackman", "행동주의 가치투자"),
        ("혼", "집중 장기투자"),
        ("hohn", "집중 장기투자"),
        ("콜먼", "성장주 중심 투자"),
        ("coleman", "성장주 중심 투자"),
        ("드러켄밀러", "거시 전술투자"),
        ("druckenmiller", "거시 전술투자"),
        ("테퍼", "가치·거시 투자"),
        ("tepper", "가치·거시 투자"),
        ("클라만", "가치투자"),
        ("klarman", "가치투자"),
    )
    return next((label for needle, label in styles if needle in identity), None)


def _manager_investment_summary(manager: dict[str, Any]) -> str | None:
    """카드의 짧은 성향보다 한 단계 풀어 쓴 매니저별 투자 관점이다."""

    identity = " ".join(
        str(manager.get(field) or "")
        for field in ("name_ko", "name", "fund_name_ko", "fund_name")
    ).lower()
    approaches = (
        ("버핏", "하락장 대응력·현금 여력·경제적 해자를 중시하는 장기 가치투자"),
        ("berkshire", "하락장 대응력·현금 여력·경제적 해자를 중시하는 장기 가치투자"),
        ("애크먼", "주주가치 개선을 직접 이끄는 행동주의 가치투자"),
        ("ackman", "주주가치 개선을 직접 이끄는 행동주의 가치투자"),
        ("혼", "소수의 고확신 기업에 장기 집중 투자"),
        ("hohn", "소수의 고확신 기업에 장기 집중 투자"),
        ("콜먼", "성장 가능성이 큰 기업을 장기 보유"),
        ("coleman", "성장 가능성이 큰 기업을 장기 보유"),
        ("드러켄밀러", "거시 흐름과 시장 변화에 빠르게 대응하는 전술 투자"),
        ("druckenmiller", "거시 흐름과 시장 변화에 빠르게 대응하는 전술 투자"),
        ("테퍼", "가치 판단과 거시 환경을 함께 보는 투자"),
        ("tepper", "가치 판단과 거시 환경을 함께 보는 투자"),
        ("클라만", "가격 대비 가치가 높은 기업을 장기 보유"),
        ("klarman", "가격 대비 가치가 높은 기업을 장기 보유"),
    )
    return next(
        (summary for needle, summary in approaches if needle in identity),
        str(manager.get("thesis_ko") or "") or None,
    )


def _money_short(value: Any) -> str:
    number = finite_number(value)
    if number is None:
        return "—"
    for unit, scale in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(number) >= scale:
            return f"${number / scale:,.1f}{unit}"
    return f"${number:,.0f}"


def _select_manager(cik: str) -> None:
    st.session_state[_SELECTED_KEY] = (
        None if st.session_state.get(_SELECTED_KEY) == cik else cik
    )


def _render_manager_card(
    manager: dict[str, Any],
    *,
    latest: dict[str, Any] | None,
    selected: bool,
) -> None:
    cik = str(manager.get("manager_cik"))
    with st.container(border=True, key=f"guru_card_{cik}"):
        name = manager.get("name_ko") or manager.get("name") or cik
        style = _manager_investment_style(manager)
        name_column, style_column = st.columns(
            [3, 2], gap="small", vertical_alignment="center"
        )
        with name_column:
            st.markdown(f"**{name}**")
        if style:
            with style_column:
                st.badge(style, color="blue")
        st.caption(manager.get("fund_name_ko") or manager.get("fund_name") or "펀드명 없음")
        if latest is None:
            st.info("저장된 공시가 없습니다.")
        else:
            with st.container(horizontal=True, gap="small"):
                st.metric("평가액", _money_short(latest.get("reported_value_usd")), border=True)
                st.metric(
                    "종목",
                    f"{latest.get('reported_line_count')}개"
                    if latest.get("reported_line_count") is not None
                    else "—",
                    border=True,
                )
            st.caption(f"기준 {latest.get('period_end') or '—'} · 제출 {latest.get('filing_date') or '—'}")
        st.button(
            "닫기" if selected else "포트폴리오 보기",
            key=f"guru_open_{cik}",
            type="primary" if selected else "tertiary",
            icon=":material/expand_less:" if selected else ":material/pie_chart:",
            width="stretch",
            on_click=_select_manager,
            args=(cik,),
        )


def _trust_notes(filing: dict[str, Any], portfolio: dict[str, Any]) -> list[str]:
    """이 장부를 얼마나 믿을 수 있는지. 공시 표에만 있던 사실을 문장으로 올린다."""

    notes: list[str] = []
    if filing.get("confidential_omitted"):
        notes.append("기밀 처리로 일부 보유가 공시에서 빠졌습니다 — 합계가 실제보다 작습니다.")
    amendment = str(filing.get("amendment_type") or "").strip()
    if amendment:
        notes.append(f"정정공시({amendment}) 기준입니다.")
    reported = finite_number(filing.get("reported_line_count"))
    parsed = finite_number(filing.get("parsed_line_count"))
    if reported is not None and parsed is not None and parsed < reported:
        notes.append(
            f"보고 {reported:.0f}종목 중 {parsed:.0f}종목만 파싱됐습니다 — 비중이 실제와 다를 수 있습니다."
        )
    excluded = int(portfolio.get("excluded") or 0)
    if excluded:
        notes.append(f"금액을 읽지 못한 {excluded}종목은 비중 계산에서 제외했습니다(0으로 채우지 않음).")
    reported_value = finite_number(filing.get("reported_value_usd"))
    total = finite_number(portfolio.get("total_value"))
    if reported_value and total and reported_value > 0:
        gap = total / reported_value - 1.0
        if abs(gap) >= 0.02:
            notes.append(
                f"장부 합계가 보고 가치와 {gap:+.1%} 차이납니다 — 파생·비주식 보유가 섞였을 수 있습니다."
            )
    return notes


def _render_portfolio(
    portfolio: dict[str, Any],
    *,
    cik: str,
    filing: dict[str, Any],
) -> None:
    """보고된 장부를 기기별로 읽기 좋은 비중 차트와 보유 목록으로 보여준다."""

    if not portfolio.get("holdings"):
        st.info(
            "이 공시에서 금액을 읽을 수 있는 long equity 보유가 없습니다. "
            "비중을 임의로 만들지 않습니다."
        )
        return

    with st.container(horizontal=True, gap="small", key=f"guru_portfolio_summary_{cik}"):
        st.metric("보고 가치 합계", _money_short(portfolio.get("total_value")), border=True)
        st.metric("종목", f"{portfolio.get('position_count')}개", border=True)
        st.metric("상위 5 집중도", display_percent(portfolio.get("top5_share")), border=True)
        st.metric("상위 10 집중도", display_percent(portfolio.get("top10_share")), border=True)

    notes = _trust_notes(filing, portfolio)
    if notes:
        st.warning(" · ".join(notes), icon=":material/rule:")
    st.caption(
        f"양식 {filing.get('form_type') or '—'} · 제출 {filing.get('filing_date') or '—'}"
    )

    top = list(portfolio.get("top") or [])
    chart_labels = [
        str(row.get("issuer_name") or row.get("label") or row.get("ticker") or "—")
        for row in top
    ]
    chart_colors = [_COLORS.muted if row.get("cusip") is None else _COLORS.primary for row in top]
    chart_customdata = [[row.get("value_usd")] for row in top]

    # 원형은 라벨을 읽을 수 있을 때만 유용하다. 상위 10개와 나머지 묶음으로
    # 제한해 작은 다이얼로그에서도 조각과 글자가 서로 덮이지 않게 한다.
    donut_rows = list(top[:10])
    remainder = top[10:]
    if remainder:
        donut_rows.append(
            {
                "label": f"나머지 {len(remainder)}개",
                "weight": sum(float(row.get("weight") or 0) for row in remainder),
                "value_usd": sum(float(row.get("value_usd") or 0) for row in remainder),
                "cusip": None,
            }
        )
    donut_companies = [
        str(row.get("issuer_name") or row.get("label") or row.get("ticker") or "—")
        for row in donut_rows
    ]
    donut_labels = [
        f"{company} · {display_percent(row.get('weight'))}"
        for company, row in zip(donut_companies, donut_rows, strict=True)
    ]
    # 순위가 높을수록 진하고, 낮을수록 옅은 색을 사용해 비중 순서를 직관적으로 보여준다.
    rank_colors = [
        "#1D4ED8", "#2563EB", "#3B82F6", "#4F8DF7", "#60A5FA",
        "#76B2FB", "#93C5FD", "#A9D3FE", "#BFDBFE", "#D7E9FF",
    ]
    donut_colors = [
        "#64748B" if row.get("cusip") is None else rank_colors[index]
        for index, row in enumerate(donut_rows)
    ]
    donut_customdata = [
        [row.get("value_usd"), company]
        for company, row in zip(donut_companies, donut_rows, strict=True)
    ]

    # 넓은 화면에서는 비중 구성을 한눈에 보는 원형을, iPhone에서는 라벨을 읽기
    # 쉬운 가로 막대를 사용한다.
    donut = go.Figure(
        go.Pie(
            labels=donut_labels,
            values=[row.get("weight") for row in donut_rows],
            customdata=donut_customdata,
            marker={"colors": donut_colors},
            # 조각은 기업명만, 범례는 기업명·비중으로 표시해 정보 중복을 줄인다.
            texttemplate="%{customdata[1]}",
            textposition="outside",
            textfont={"size": 11},
            hovertemplate="%{label}<br>장부 내 비중 %{percent}<br>평가액 $%{customdata[0]:,.0f}<extra></extra>",
        )
    )
    donut_layout = plotly_layout(height=410)
    donut_layout["margin"] = {"l": 16, "r": 158, "t": 18, "b": 18}
    donut_layout["uniformtext"] = {"minsize": 10, "mode": "hide"}
    donut_layout["legend"] = {
        "orientation": "v",
        "y": 0.5,
        "yanchor": "middle",
        "x": 1.02,
        "xanchor": "left",
        "font": {"size": 11},
    }
    donut.update_layout(**donut_layout, showlegend=True)
    with st.container(key=f"guru_portfolio_donut_{cik}"):
        st.plotly_chart(donut, width="stretch", config={"displaylogo": False}, key=f"guru_donut:{cik}")

    bars = go.Figure(
        go.Bar(
            x=[row.get("weight") for row in top], y=chart_labels, orientation="h",
            marker={"color": chart_colors}, customdata=chart_customdata,
            hovertemplate="%{y}<br>장부 내 비중 %{x:.2%}<br>평가액 $%{customdata[0]:,.0f}<extra></extra>",
        )
    )
    bar_layout = plotly_layout(height=max(300, 34 * len(top) + 90))
    bar_layout["margin"] = {"l": 10, "r": 10, "t": 12, "b": 42}
    bar_layout["xaxis"] = {"tickformat": ".0%", "title": "장부 내 비중", "rangemode": "tozero"}
    bar_layout["yaxis"] = {"autorange": "reversed", "tickfont": {"size": 12}}
    bars.update_layout(**bar_layout, showlegend=False)
    with st.container(key=f"guru_portfolio_bar_{cik}"):
        st.plotly_chart(bars, width="stretch", config={"displaylogo": False}, key=f"guru_bar:{cik}")
    holdings = list(portfolio["holdings"])

    st.markdown("##### 상위 보유 종목")
    def render_holding_card(rank: int, holding: dict[str, Any]) -> None:
        ticker = str(holding.get("ticker") or "—")
        issuer = str(holding.get("issuer_name") or holding.get("label") or "—")
        quantity = finite_number(holding.get("quantity"))
        quantity_label = f"{quantity:,.0f}주" if quantity is not None else "—"
        with st.container(border=True, key=f"guru_holding_card:{cik}:{rank}"):
            left, right = st.columns([1, 2], gap="small", vertical_alignment="center")
            with left:
                st.markdown(f"**{rank}. {issuer} · {ticker}**")
            with right:
                st.markdown(
                    f'<div class="guru-holding-summary">포트폴리오 비중 {display_percent(holding.get("weight"))} · '
                    f'평가액 {_money_short(holding.get("value_usd"))} · 보유 수량 {quantity_label}</div>',
                    unsafe_allow_html=True,
                )

    for rank, holding in enumerate(holdings[:5], start=1):
        render_holding_card(rank, holding)

    remaining_holdings = holdings[5:]
    if remaining_holdings:
        more_holdings_key = f"guru_more_holdings:{cik}"
        show_more_holdings = bool(st.session_state.get(more_holdings_key, False))
        if st.button(
            "감추기" if show_more_holdings else f"더보기 · {len(remaining_holdings)}개",
            key=f"{more_holdings_key}:toggle",
            type="tertiary",
            icon=":material/expand_less:" if show_more_holdings else ":material/expand_more:",
        ):
            show_more_holdings = not show_more_holdings
            st.session_state[more_holdings_key] = show_more_holdings
        if show_more_holdings:
            for rank, holding in enumerate(remaining_holdings, start=6):
                render_holding_card(rank, holding)

    table = pd.DataFrame(
        [
            {
                "발행사": row.get("issuer_name") or row.get("label") or "—",
                "티커": row.get("ticker") or "—",
                "평가액": row.get("value_usd"),
                "비중": row.get("weight"),
                "수량": row.get("quantity"),
                "CUSIP": row.get("cusip"),
            }
            for row in holdings
        ]
    )
    with st.expander(f"전체 보유 종목 표 · {len(holdings)}개", expanded=False):
        st.caption("필요할 때만 가로로 스크롤해 전체 장부를 확인할 수 있습니다.")
        dataframe(
            table,
            key=f"guru_holding_table:{cik}",
            column_config={"비중": st.column_config.NumberColumn(format="percent")},
        )


def _render_changes(
    *,
    cik: str,
    manager_filings: list[dict[str, Any]],
    positions_by_accession: dict[str, list[dict[str, Any]]],
    cusip_map: dict[str, str | None],
) -> None:
    """비교 가능한 두 분기의 포지션 변화를 보여준다."""

    if len(manager_filings) < 2:
        st.info(
            "비교 가능한 직전 분기 공시가 없습니다. 신규·증가·감소·매도를 추정하지 않습니다."
        )
        return

    current, previous = manager_filings[0], manager_filings[1]
    current_positions = positions_by_accession.get(str(current.get("accession_no")), [])
    previous_positions = positions_by_accession.get(str(previous.get("accession_no")), [])
    changes = guru_position_changes(current_positions, previous_positions, cusip_map)

    if not changes:
        st.info("비교 가능한 두 분기 사이에 임계값 이상의 포지션 변화가 없습니다.")
        return

    counts = {
        "new": sum(row["change"] == "new" for row in changes),
        "increase": sum(row["change"] == "increase" for row in changes),
        "decrease": sum(row["change"] == "decrease" for row in changes),
        "exit": sum(row["change"] == "exit" for row in changes),
    }
    labels = {"new": "신규", "increase": "증가", "decrease": "감소", "exit": "매도"}
    filter_key = f"guru_changes_filter:{cik}:{current.get('period_end')}"
    selected_change = st.session_state.get(filter_key)
    if selected_change not in labels or not counts.get(selected_change, 0):
        selected_change = None
        st.session_state.pop(filter_key, None)
    with st.container(horizontal=True, gap="small"):
        for key in ("new", "increase", "decrease", "exit"):
            if st.button(
                f"{labels[key]} {counts[key]}종목",
                key=f"{filter_key}:{key}",
                type="primary" if selected_change == key else "secondary",
                width="stretch",
                disabled=counts[key] == 0,
            ):
                selected_change = None if selected_change == key else key
                st.session_state[filter_key] = selected_change

    visible_changes = [
        row for row in changes
        if selected_change is None or str(row.get("change")) == selected_change
    ]
    dataframe(
        [
            {
                "변화": labels.get(row["change"], "—"),
                "종목": row.get("ticker") or "—",
                "발행사": row.get("issuer_name") or "—",
                "수량 변화율": row.get("change_fraction"),
                "현재 수량": row.get("current_quantity"),
                "직전 수량": row.get("previous_quantity"),
                "현재 평가액": row.get("current_value_usd"),
                "직전 평가액": row.get("previous_value_usd"),
            }
            for row in visible_changes
        ],
        key=f"guru_changes:{cik}",
        column_config={"수량 변화율": st.column_config.NumberColumn(format="percent")},
    )
    source_note(
        SOURCE_DB,
        SOURCE_CALC,
        observed_at=current.get("filing_date"),
        detail="비교 불가능한 자산은 신규·매도로 추정하지 않고 아예 제외합니다",
    )


def _render_smart_changes(cik: str, rows: list[dict[str, Any]]) -> None:
    """DB의 amendment-aware effective-quarter 변화 View를 표시한다."""
    manager_rows = [row for row in rows if str(row.get("manager_cik")) == cik]
    if not manager_rows:
        st.info("비교 가능한 직전 effective quarter가 없습니다.")
        return
    period_end = max(str(row.get("period_end") or "") for row in manager_rows)
    changes = [
        row for row in manager_rows
        if str(row.get("period_end") or "") == period_end
    ]
    labels = {
        "NEW": "신규", "ADD": "증가", "HOLD": "유지",
        "REDUCE": "감소", "EXIT": "매도",
    }
    counts = {
        key: sum(str(row.get("change_type")) == key for row in changes)
        for key in labels
    }
    filter_key = f"guru_smart_changes_filter:{cik}:{period_end}"
    selected_change = st.session_state.get(filter_key)
    if selected_change not in labels or not counts.get(selected_change, 0):
        selected_change = None
        st.session_state.pop(filter_key, None)
    with st.container(horizontal=True, gap="small"):
        for key in ("NEW", "ADD", "HOLD", "REDUCE", "EXIT"):
            if st.button(
                f"{labels[key]} {counts[key]}종목",
                key=f"{filter_key}:{key}",
                type="primary" if selected_change == key else "secondary",
                width="stretch",
                disabled=counts[key] == 0,
            ):
                selected_change = None if selected_change == key else key
                st.session_state[filter_key] = selected_change
    visible_changes = [
        row for row in changes
        if selected_change is None or str(row.get("change_type")) == selected_change
    ]
    dataframe(
        [
            {
                "변화": labels.get(str(row.get("change_type")), "—"),
                "종목": row.get("ticker") or "—",
                "발행사": row.get("issuer_name") or "—",
                "수량 변화율": (
                    float(row["quantity_change_pct"]) / 100
                    if row.get("quantity_change_pct") is not None else None
                ),
                "현재 수량": row.get("current_quantity"),
                "직전 수량": row.get("previous_quantity"),
                "현재 비중": (
                    float(row["current_weight_pct"]) / 100
                    if row.get("current_weight_pct") is not None else None
                ),
                "직전 비중": (
                    float(row["previous_weight_pct"]) / 100
                    if row.get("previous_weight_pct") is not None else None
                ),
                "비중 변화(%p)": row.get("weight_change_pp"),
            }
            for row in sorted(
                visible_changes,
                key=lambda row: (
                    str(row.get("change_type") or ""),
                    str(row.get("ticker") or row.get("cusip") or ""),
                ),
            )
        ],
        key=f"guru_smart_changes:{cik}:{period_end}",
        column_config={
            "수량 변화율": st.column_config.NumberColumn(format="percent"),
            "현재 비중": st.column_config.NumberColumn(format="percent"),
            "직전 비중": st.column_config.NumberColumn(format="percent"),
        },
    )
    source_note(
        SOURCE_DB,
        detail="institutional 원장 · amendment-aware effective portfolio 기준",
    )


def _render_manager_detail(
    manager: dict[str, Any],
    *,
    cik: str,
    manager_filings: list[dict[str, Any]],
    positions_by_accession: dict[str, list[dict[str, Any]]],
    cusip_map: dict[str, str | None],
    smart_changes: list[dict[str, Any]],
) -> None:
    """매니저 하나의 최신 장부와 분기 변화를 상세 표면에만 표시한다."""

    if investment_summary := _manager_investment_summary(manager):
        st.caption(f"투자 관점 · {investment_summary}")

    latest = manager_filings[0]
    detail_view = view_selector(
        "상세 보기",
        _DETAIL_VIEWS,
        key=f"guru_detail_view:{cik}",
        default="포트폴리오",
    )
    if detail_view == "포트폴리오":
        rows = positions_by_accession.get(str(latest.get("accession_no")), [])
        _render_portfolio(
            guru_portfolio(rows, cusip_map),
            cik=cik,
            filing=latest,
        )
    elif smart_changes:
        _render_smart_changes(cik, smart_changes)
    else:
        _render_changes(
            cik=cik,
            manager_filings=manager_filings,
            positions_by_accession=positions_by_accession,
            cusip_map=cusip_map,
        )


st.html("""
    <style>
    div[class*="st-key-guru_card_"] [data-testid="stMetricValue"] {
        font-size: 1.35rem !important;
        line-height: 1.15 !important;
    }
    .guru-holding-summary {
        color: var(--secondary-foreground-color);
        font-size: 0.82rem;
        line-height: 1.35;
        text-align: right;
    }
    .guru-disclosure {
        color: var(--secondary-foreground-color);
        font-size: 0.86rem;
        line-height: 1.45;
        margin: 0.15rem 0 1rem;
    }
    .guru-disclosure-help {
        align-items: center;
        border: 1px solid currentColor;
        border-radius: 50%;
        cursor: help;
        display: inline-flex;
        font-size: 0.72rem;
        font-weight: 700;
        height: 1rem;
        justify-content: center;
        margin-left: 0.3rem;
        vertical-align: text-bottom;
        width: 1rem;
    }
    @media (max-width: 743px) {
        div[class*="st-key-guru_card_"] [data-testid="stMetricValue"] {
            font-size: 1.2rem !important;
        }
    }
    </style>
""")
st.title("13F 포트폴리오")
st.html("""
    <div class="guru-disclosure">
        13F 공시 기준 · 현재 보유와 전체 자산을 뜻하지 않습니다.
        <span class="guru-disclosure-help" title="13F는 분기말 long equity 공시입니다. 숏·파생·채권·해외 상장·비상장 자산과 기준일 이후 거래는 포함되지 않으며, 제출까지 최대 45일이 걸릴 수 있습니다.">?</span>
    </div>
""")

guru_result = load_guru_data()
if not result_status(guru_result, empty_text="저장된 13F 데이터가 없습니다"):
    st.stop()

payload = result_payload(guru_result, default={}) or {}
managers = sorted(
    [row for row in payload.get("managers", []) if row.get("is_active") is not False],
    key=lambda row: (row.get("display_order") is None, row.get("display_order") or 999),
)
filings = list(payload.get("filings", []))
positions = list(payload.get("positions", []))
smart_changes = list(payload.get("smart_changes", []))
cusip_map = {
    str(row.get("cusip")): row.get("ticker")
    for row in payload.get("cusip_map", [])
    if row.get("cusip")
}
if not managers:
    st.info("활성 매니저 메타데이터가 없습니다.")
    st.stop()

filings_by_manager: dict[str, list[dict[str, Any]]] = {}
for filing in filings:
    filings_by_manager.setdefault(str(filing.get("manager_cik")), []).append(filing)
for rows in filings_by_manager.values():
    rows.sort(
        key=lambda row: (str(row.get("period_end") or ""), str(row.get("filing_date") or "")),
        reverse=True,
    )
positions_by_accession: dict[str, list[dict[str, Any]]] = {}
for row in positions:
    positions_by_accession.setdefault(str(row.get("accession_no")), []).append(row)

selected_cik = st.session_state.get(_SELECTED_KEY)
surface = detail_surface()
listing, manager_side = detail_layout(surface)

with listing:
    st.markdown("### 투자 매니저 포트폴리오")
    for start in range(0, len(managers), _CARD_COLUMNS):
        chunk = managers[start:start + _CARD_COLUMNS]
        with st.container(key=f"guru_manager_grid_{start}"):
            columns = st.columns(_CARD_COLUMNS, gap="small")
            for column, manager in zip(columns, chunk):
                cik = str(manager.get("manager_cik"))
                manager_filings = filings_by_manager.get(cik, [])
                latest = manager_filings[0] if manager_filings else None
                with column:
                    _render_manager_card(
                        manager,
                        latest=latest,
                        selected=selected_cik == cik,
                    )

if selected_cik:
    manager = next(
        (row for row in managers if str(row.get("manager_cik")) == selected_cik), None
    )
    selected_manager_filings = filings_by_manager.get(selected_cik, [])
    if manager is not None and selected_manager_filings:
        open_detail(
            f"{manager.get('name_ko') or manager.get('name')} 포트폴리오",
            lambda: _render_manager_detail(
                manager,
                cik=selected_cik,
                manager_filings=selected_manager_filings,
                positions_by_accession=positions_by_accession,
                cusip_map=cusip_map,
                smart_changes=smart_changes,
            ),
            surface=surface,
            side=manager_side,
            icon=":material/pie_chart:",
            width="large",
            on_dismiss=lambda: st.session_state.pop(_SELECTED_KEY, None),
        )
    elif manager is not None:
        with manager_side if manager_side is not None else st.container():
            st.info(f"{manager.get('name_ko') or manager.get('name')}의 저장된 공시가 없습니다.")
