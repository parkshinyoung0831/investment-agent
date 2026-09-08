"""저장된 AI 투자 판단을 선택한 깊이만큼 읽기 전용으로 검토한다."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from investment_agent.dashboard.calculations import add_technical_indicators
from investment_agent.dashboard.db import load_ai_data
from investment_agent.reporting.readers.dashboard import load_price_history, load_tickers
from investment_agent.dashboard.components.theme import dashboard_palette, plotly_layout
from investment_agent.dashboard.components.ui import (
    SOURCE_CALC,
    SOURCE_DB,
    compact_json,
    dataframe,
    display_percent,
    format_time,
    page_header,
    render_source_help,
    result_payload,
    result_status,
    source_note,
    view_selector,
)


_COLORS = dashboard_palette()
PRIMARY = _COLORS.primary
MUTED = _COLORS.muted
UP = _COLORS.up
DOWN = _COLORS.down


def _rows_for_ticker(rows: list[dict[str, Any]], ticker: str) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("ticker", "")).upper() == ticker]


def _latest(rows: list[dict[str, Any]], *time_keys: str) -> dict[str, Any]:
    if not rows:
        return {}

    def key(row: dict[str, Any]) -> str:
        return next((str(row.get(name)) for name in time_keys if row.get(name)), "")

    return max(rows, key=key)


def _frame_from_prices(payload: Any, ticker: str) -> pd.DataFrame:
    if isinstance(payload, pd.DataFrame):
        return payload.copy()
    if isinstance(payload, dict):
        candidate = payload.get(ticker)
        if candidate is None:
            candidate = payload.get(ticker.upper())
        if candidate is None:
            candidate = payload.get("prices")
        if isinstance(candidate, pd.DataFrame):
            return candidate.copy()
        if isinstance(candidate, list):
            return pd.DataFrame(candidate)
    if isinstance(payload, list):
        return pd.DataFrame(payload)
    return pd.DataFrame()


def _technical_frame(ticker: str) -> tuple[Any, pd.DataFrame]:
    """선택된 가격 뷰 안에서만 저장된 OHLCV를 읽고 지표를 계산한다."""

    price_result = load_price_history([ticker], period="6mo")
    frame = _frame_from_prices(result_payload(price_result), ticker)
    if not frame.empty:
        frame = add_technical_indicators(frame).tail(90)
    return price_result, frame


def render() -> None:
    """주문·체결 페이지가 탭 하나로 불러 쓴다. 페이지 단독 진입점은 아니다.

    스크립트였을 때의 st.stop()은 return으로 바꿨다 — 탭 안에서 st.stop()을 부르면
    호스트 페이지의 나머지 탭까지 통째로 멈춘다.
    """
    page_header(
        "AI 투자 승인 & 토론",
        "승인 판단을 먼저 보고 필요한 근거만 단계적으로 확인해요",
        discord="#투자-승인",
    )
    render_source_help()
    st.info(
        "모든 상세 화면은 읽기 전용이에요. 프리뷰는 현재 세션에서만 계산하며 "
        "DB 저장, 승인 요청 생성, Discord 발송, 주문 실행은 하지 않아요.",
        icon=":material/verified_user:",
    )

    ticker_result = load_tickers()
    ticker_payload = result_payload(ticker_result, default=[]) or []
    ticker_values = sorted(
        {
            str(row.get("ticker", "")).upper()
            for row in ticker_payload
            if isinstance(row, dict) and row.get("ticker")
        }
    )
    if not result_status(ticker_result, empty_text="선택 가능한 실제 추적 종목이 없습니다") or not ticker_values:
        return

    ticker = st.selectbox(
        "검토할 종목",
        ticker_values,
        index=None,
        placeholder="실제 추적 종목을 선택하세요",
        key="ai_selected_ticker",
    )
    if not ticker:
        st.info("종목을 선택하면 저장된 최신 승인 요약만 먼저 표시합니다.")
        return

    ai_result = load_ai_data(ticker)
    if not result_status(ai_result, empty_text=f"{ticker}의 저장된 AI 판단이 없습니다"):
        return

    ai_payload = result_payload(ai_result, default={}) or {}
    cases = _rows_for_ticker(list(ai_payload.get("cases", [])), ticker)
    signals = _rows_for_ticker(list(ai_payload.get("signals", [])), ticker)
    proposals = list(ai_payload.get("proposals", []))
    risk_decisions = list(ai_payload.get("risk_decisions", []))
    approvals = list(ai_payload.get("approvals", []))

    latest_case = _latest(cases, "as_of_at", "created_at")
    latest_signal = _latest(signals, "recorded_at", "created_at")
    signal_proposal = latest_signal.get("proposal") if isinstance(latest_signal.get("proposal"), dict) else {}
    latest_proposal = _latest(proposals, "as_of_at", "created_at")
    proposal_id = latest_proposal.get("proposal_id")
    matching_risk = [row for row in risk_decisions if row.get("proposal_id") == proposal_id]
    latest_risk = _latest(matching_risk, "decided_at")
    risk_id = latest_risk.get("risk_decision_id")
    matching_approvals = [
        row
        for row in approvals
        if row.get("risk_decision_id") == risk_id
        or (proposal_id and row.get("proposal_id") == proposal_id)
    ]
    latest_approval = _latest(matching_approvals, "requested_at", "updated_at")
    proposed_weights = latest_proposal.get("weights") if isinstance(latest_proposal.get("weights"), dict) else {}
    approved_weights = latest_risk.get("approved_weights") if isinstance(latest_risk.get("approved_weights"), dict) else {}
    evidence_digest = (
        latest_case.get("evidence_digest")
        if isinstance(latest_case.get("evidence_digest"), dict)
        else {}
    )
    evidence_manifest = (
        latest_case.get("evidence_manifest")
        if isinstance(latest_case.get("evidence_manifest"), dict)
        else {}
    )
    evidence_items = (
        latest_case.get("evidence_items")
        if isinstance(latest_case.get("evidence_items"), list)
        else []
    )

    view = view_selector(
        "상세 보기",
        ("승인 요약", "역할 토론", "기술 차트", "근거 번들", "분석 프리뷰"),
        key=f"ai_adaptive_view:{ticker}",
        default="승인 요약",
    )

    if view == "승인 요약":
        proposed = proposed_weights.get(ticker, signal_proposal.get("target_weight"))
        approved = approved_weights.get(ticker)
        with st.container(horizontal=True):
            st.metric("AI 제안 비중", display_percent(proposed), border=True)
            st.metric("리스크 승인 비중", display_percent(approved), border=True)
            approved_flag = latest_risk.get("is_approved")
            st.metric(
                "리스크 게이트",
                "승인" if approved_flag is True else "거부" if approved_flag is False else "—",
                border=True,
            )
            st.metric("승인 요청 상태", latest_approval.get("status") or "—", border=True)

        final_decision = latest_case.get("final_decision") if isinstance(latest_case.get("final_decision"), dict) else {}
        with st.container(border=True):
            st.markdown("**지금 확인할 판단**")
            st.write(
                f"시그널 · {signal_proposal.get('signal') or final_decision.get('action') or '—'}  "
                f"/ 신뢰도 · {display_percent(signal_proposal.get('confidence') or latest_proposal.get('confidence'))}"
            )
            violations = latest_risk.get("violations") or []
            if violations:
                st.warning("위반 규칙 · " + compact_json(violations))
            else:
                st.caption("저장된 위반 규칙 없음")
            st.caption(
                f"요청 만료 · {format_time(latest_approval.get('expires_at'))} · "
                f"case 상태 · {latest_case.get('status') or '—'}"
            )
            if latest_proposal and not latest_risk:
                st.warning("데이터 없음 · 이 제안 ID와 정확히 연결된 risk decision이 없습니다.")
            elif latest_risk and not latest_approval:
                st.caption("이 risk decision과 정확히 연결된 승인 요청은 없습니다.")
            source_note(
                SOURCE_DB,
                observed_at=latest_risk.get("decided_at") or latest_proposal.get("as_of_at"),
                detail="proposal_id/risk_decision_id가 정확히 일치하는 승인 체인만 결합",
            )

    elif view == "역할 토론":
        st.subheader(":material/forum: 다중 에이전트 토론")
        analyses = (
            latest_case.get("role_summaries")
            if isinstance(latest_case.get("role_summaries"), list)
            else []
        )
        if not analyses:
            archived_count = int(evidence_digest.get("role_analysis_count") or 0)
            if archived_count and evidence_manifest:
                st.info(
                    f"역할 분석 {archived_count}개 원문은 검증 가능한 아티팩트로 보관되어 "
                    "이 화면에는 전달하지 않아요."
                )
            else:
                st.info(
                    "이 case에는 표시 가능한 저장 role analysis가 없습니다. "
                    "가짜 토론을 만들지 않습니다."
                )
        else:
            stances = [str(a.get("stance") or "").lower() for a in analyses if a.get("stance")]
            bull_count = sum(1 for s in stances if any(w in s for w in ("bull", "buy", "long", "positive", "매수", "낙관")))
            bear_count = sum(1 for s in stances if any(w in s for w in ("bear", "sell", "short", "negative", "매도", "비관")))
            neutral_count = len(analyses) - bull_count - bear_count

            with st.container(horizontal=True):
                st.metric("참여 분석관", f"{len(analyses)}명", border=True)
                st.metric("긍정 (Bull)", f"{bull_count}명", border=True)
                st.metric("경계 (Bear)", f"{bear_count}명", border=True)
                st.metric("중립 / 리스크 검토", f"{neutral_count}명", border=True)

            for analysis in analyses:
                role = str(analysis.get("role") or analysis.get("name") or "저장된 분석")
                role_lower = role.lower()
                icon = (
                    ":material/trending_up:" if "bull" in role_lower
                    else ":material/trending_down:" if "bear" in role_lower
                    else ":material/balance:" if "risk" in role_lower or "judge" in role_lower
                    else ":material/query_stats:" if "market" in role_lower
                    else ":material/description:" if "fundamental" in role_lower
                    else ":material/newspaper:" if "news" in role_lower
                    else ":material/forum:" if "social" in role_lower or "sentiment" in role_lower
                    else ":material/smart_toy:"
                )
                with st.container(border=True):
                    st.markdown(f"### {icon} {role}")
                    summary = analysis.get("summary") or analysis.get("text") or analysis.get("content")
                    if summary:
                        st.write(summary)
                    if analysis.get("stance") is not None:
                        st.caption(
                            f"입장(Stance) · **{analysis.get('stance')}** | 신뢰도(Confidence) · **{display_percent(analysis.get('confidence'))}**"
                        )
                    for claim in analysis.get("claims") or []:
                        text = claim.get("text") if isinstance(claim, dict) else claim
                        st.write(f"• **주장 근거**: {text}")
                    for risk in analysis.get("risks") or []:
                        st.write(f"• **주의 리스크**: {risk}")
            source_note(
                SOURCE_DB,
                observed_at=latest_case.get("as_of_at"),
                detail="reporting read model의 제한된 role 요약",
            )

    elif view == "근거 번들":
        source_counts = evidence_digest.get("source_counts") or {}
        domain_counts = evidence_digest.get("domain_counts") or {}
        storage_label = {
            "artifact": "아티팩트",
            "artifact_error": "아티팩트 오류",
            "missing": "없음",
        }.get(str(latest_case.get("evidence_storage") or ""), "없음")
        with st.container(horizontal=True):
            st.metric(
                "근거 항목",
                f"{int(evidence_digest.get('evidence_count') or 0):,}건",
                border=True,
            )
            st.metric("근거 출처", f"{len(source_counts):,}개", border=True)
            st.metric(
                "역할 분석",
                f"{int(evidence_digest.get('role_analysis_count') or 0):,}개",
                border=True,
            )
            st.metric("원문 저장", storage_label, border=True)

        evidence_rows = []
        for evidence in evidence_items:
            if not isinstance(evidence, dict):
                continue
            evidence_rows.append(
                {
                    "근거 ID": evidence.get("evidence_id"),
                    "도메인": evidence.get("domain"),
                    "출처": evidence.get("source"),
                    "관측 시각": evidence.get("observed_at"),
                    "사용 가능 시각": evidence.get("available_at"),
                    "시점 품질": evidence.get("timing_status"),
                }
            )
        if evidence_rows:
            dataframe(evidence_rows, key=f"ai_evidence:{ticker}")
        elif evidence_digest.get("evidence_count"):
            st.info(
                "근거 원문은 아티팩트에 보관되어 이 화면에는 source별 요약만 표시해요."
            )
        else:
            st.info("이 case에는 표시 가능한 저장 evidence 항목이 없습니다.")

        count_rows = [
            {"구분": "도메인", "이름": name, "건수": count}
            for name, count in domain_counts.items()
        ] + [
            {"구분": "출처", "이름": name, "건수": count}
            for name, count in source_counts.items()
        ]
        if count_rows:
            dataframe(count_rows, key=f"ai_evidence_digest:{ticker}")

        missing_or_warnings = {
            "missing_data": evidence_digest.get("missing_data") or [],
            "warnings": evidence_digest.get("warnings") or [],
        }
        if any(missing_or_warnings.values()):
            st.warning("데이터 품질 · " + compact_json(missing_or_warnings))
        artifact_error = latest_case.get("evidence_artifact_error")
        if artifact_error:
            st.warning(
                "근거 아티팩트를 저장하지 못해 이 case는 DB 원문 보존 상태예요. "
                "운영 로그에서 저장 경로와 디스크 상태를 확인해 주세요."
            )
        if evidence_manifest:
            with st.expander("아티팩트 참조"):
                st.write(
                    f"아티팩트 ID · {evidence_manifest.get('artifact_id') or '—'}  "
                    f"/ 스키마 · v{evidence_manifest.get('schema_version') or '—'}"
                )
                st.code(str(evidence_manifest.get("uri") or "—"), language=None)
                st.caption(
                    f"SHA-256 · {evidence_manifest.get('sha256') or '—'} · "
                    f"크기 · {evidence_manifest.get('byte_size') or 0:,} bytes"
                )
        source_note(
            SOURCE_DB,
            observed_at=latest_case.get("as_of_at"),
            detail="reporting decision read model; 원문 payload는 화면에 전달하지 않음",
        )

    elif view == "기술 차트":
        st.subheader(":material/candlestick_chart: 90거래일 가격 · SMA20/SMA60 · RSI14")
        with st.spinner("저장된 market.prices_daily에서 선택 종목 가격을 조회하고 있습니다…"):
            price_result, price_frame = _technical_frame(ticker)
        if result_status(price_result, empty_text=f"{ticker} 가격 이력이 없습니다"):
            required = {"Open", "High", "Low", "Close", "SMA20", "SMA60", "RSI14"}
            if price_frame.empty or not required.issubset(price_frame.columns):
                st.info("실제 OHLCV가 부족해 기술 차트를 만들지 않습니다.")
            else:
                x_values = price_frame.index
                figure = make_subplots(
                    rows=2,
                    cols=1,
                    shared_xaxes=True,
                    vertical_spacing=0.08,
                    row_heights=[0.72, 0.28],
                )
                figure.add_trace(
                    go.Candlestick(
                        x=x_values,
                        open=price_frame["Open"],
                        high=price_frame["High"],
                        low=price_frame["Low"],
                        close=price_frame["Close"],
                        increasing_line_color=UP,
                        decreasing_line_color=DOWN,
                        name=ticker,
                    ),
                    row=1,
                    col=1,
                )
                figure.add_trace(
                    go.Scatter(x=x_values, y=price_frame["SMA20"], name="SMA20", line={"color": PRIMARY}),
                    row=1,
                    col=1,
                )
                figure.add_trace(
                    go.Scatter(x=x_values, y=price_frame["SMA60"], name="SMA60", line={"color": MUTED}),
                    row=1,
                    col=1,
                )
                figure.add_trace(
                    go.Scatter(x=x_values, y=price_frame["RSI14"], name="RSI14", line={"color": PRIMARY}),
                    row=2,
                    col=1,
                )
                figure.add_hline(y=70, line_dash="dot", line_color=DOWN, row=2, col=1)
                figure.add_hline(y=30, line_dash="dot", line_color=UP, row=2, col=1)
                figure.update_layout(**plotly_layout(height=640), xaxis_rangeslider_visible=False)
                st.plotly_chart(figure, width="stretch", config={"displaylogo": False})
                source_note(SOURCE_DB, SOURCE_CALC, observed_at=price_frame.index.max())

    elif view == "분석 프리뷰":
        st.subheader(":material/preview: 읽기 전용 분석 프리뷰")
        st.caption("버튼을 누른 경우에만 가격을 조회합니다. 결과는 현재 브라우저 세션에만 남습니다.")
        preview_key = f"readonly_preview:{ticker}"
        if st.button("프리뷰 계산", type="primary", icon=":material/analytics:", key=f"preview_button:{ticker}"):
            with st.spinner("가격과 저장 판단을 결합하고 있습니다…"):
                price_result, price_frame = _technical_frame(ticker)
            if result_status(price_result, empty_text=f"{ticker} 가격 이력이 없습니다"):
                required = {"Close", "SMA20", "SMA60", "RSI14"}
                if price_frame.empty or not required.issubset(price_frame.columns):
                    st.info("실제 가격 이력이 부족해 프리뷰를 계산하지 않습니다.")
                else:
                    last = price_frame.iloc[-1]
                    technical = "중립"
                    if pd.notna(last.get("SMA20")) and pd.notna(last.get("SMA60")):
                        technical = "상방 정렬" if float(last["SMA20"]) > float(last["SMA60"]) else "하방 정렬"
                    st.session_state[preview_key] = {
                        "ticker": ticker,
                        "price_at": str(price_frame.index.max()),
                        "technical": technical,
                        "rsi14": None if pd.isna(last.get("RSI14")) else float(last["RSI14"]),
                        "stored_signal": signal_proposal.get("signal"),
                        "proposed_weight": proposed_weights.get(ticker, signal_proposal.get("target_weight")),
                        "approved_weight": approved_weights.get(ticker),
                        "violations": latest_risk.get("violations") or [],
                        "missing_data": signal_proposal.get("missing_data") or evidence_digest.get("missing_data", []),
                    }
        preview = st.session_state.get(preview_key)
        if preview:
            with st.container(border=True):
                st.json(preview, expanded=True)
                source_note(SOURCE_DB, SOURCE_CALC, detail="저장·주문·승인 요청 생성 없음")
        else:
            st.info("아직 프리뷰를 실행하지 않았습니다. 저장된 승인 판단은 ‘승인 요약’에서 확인하세요.")
