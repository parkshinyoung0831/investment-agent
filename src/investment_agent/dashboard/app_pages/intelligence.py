"""투자 엔진의 입력·모델·신호·위험 심사를 추적하는 읽기 전용 Alpha Lab."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

import pandas as pd
import streamlit as st

from investment_agent.dashboard.components.alpha_lab import (
    DOMAIN_LABELS,
    RISK_STATE_LABELS,
    alpha_summary,
    candidate_rows,
    evaluation_rows,
    live_regime_from_prices,
    model_rows,
    policy_snapshot,
    trace_for_ticker,
)
from investment_agent.dashboard.components.animated_pipeline import animated_pipeline
from investment_agent.dashboard.db import load_ai_data, load_alpha_lab_data
from investment_agent.reporting.readers.dashboard import load_execution_data, load_price_history, load_tickers
from investment_agent.reporting.readers.news import load_live_news, provider_statuses
from investment_agent.dashboard.components.theme import dashboard_palette
from investment_agent.dashboard.components.ui import (
    SOURCE_CALC,
    SOURCE_DB,
    SOURCE_LIVE,
    dataframe,
    display_percent,
    format_time,
    render_source_help,
    result_payload,
    result_status,
    source_note,
    view_selector,
)


def _sentiment_tag(title: str, summary: str) -> str:
    """기사 생성 없이 제목·짧은 요약의 표면 키워드만 태그한다."""

    text = f"{title} {summary}".lower()
    positive = ("beat", "surge", "gain", "upgrade", "growth", "record", "호조", "상향", "증가")
    negative = ("miss", "fall", "drop", "downgrade", "probe", "risk", "하락", "부진", "조사", "위험")
    uncertain = ("may", "could", "uncertain", "rumor", "reportedly", "가능", "불확실", "관측")
    pos_score = sum(token in text for token in positive)
    neg_score = sum(token in text for token in negative)
    if any(token in text for token in uncertain):
        return "불확실"
    if pos_score > neg_score:
        return "긍정"
    if neg_score > pos_score:
        return "부정"
    return "불확실"


def _normalise_article(raw: dict[str, Any], ticker: str | None, *, usage: str) -> dict[str, Any]:
    content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
    provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
    canonical = content.get("canonicalUrl") if isinstance(content.get("canonicalUrl"), dict) else {}
    title = raw.get("title") or content.get("title") or ""
    summary = raw.get("summary") or content.get("summary") or content.get("description") or ""
    published = raw.get("providerPublishTime") or raw.get("published_at") or content.get("pubDate")
    if isinstance(published, (int, float)):
        published = datetime.fromtimestamp(published, tz=timezone.utc).isoformat()
    related = raw.get("related_tickers")
    related_display = ", ".join(map(str, related)) if isinstance(related, list) and related else ticker or raw.get("ticker") or "—"
    return {
        "제목": title or "제목 메타데이터 없음",
        "출처": raw.get("publisher") or raw.get("source") or provider.get("displayName") or "출처 메타데이터 없음",
        "게시 시각": format_time(published),
        "관련 종목": related_display,
        "태그": _sentiment_tag(str(title), str(summary)),
        "상태": usage,
        "짧은 요약": summary or "요약 메타데이터 없음",
        "URL": raw.get("link") or raw.get("url") or canonical.get("url") or "—",
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _engine_snapshot(payload: Mapping[str, Any]) -> dict[str, str]:
    """운영 경로의 최근 도달 지점을 네 개의 짧은 상태로 요약한다."""

    runs = _list(payload.get("decision_runs"))
    batches = _list(payload.get("signal_runs"))
    risks = _list(payload.get("risk_decisions"))
    approvals = _list(payload.get("approvals"))
    latest_run = _mapping(runs[0]) if runs else {}
    latest_batch = _mapping(batches[0]) if batches else {}
    latest_risk = _mapping(risks[0]) if risks else {}
    latest_approval = _mapping(approvals[0]) if approvals else {}

    run_status = str(latest_run.get("status") or "실행 기록 없음")
    if latest_batch:
        batch_status = "완료" if latest_batch.get("is_complete") is True else "불완전"
    else:
        batch_status = "배치 없음"
    if latest_risk:
        risk_status = "통과" if latest_risk.get("is_approved") is True else "차단"
    else:
        risk_status = "심사 없음"
    approval_status = str(latest_approval.get("status") or "주문 없음")
    return {
        "analysis": run_status,
        "batch": batch_status,
        "risk": risk_status,
        "order": approval_status,
    }


def _engine_steps(
    payload: Mapping[str, Any],
    *,
    live_regime: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    summary = alpha_summary(payload)
    if live_regime:
        summary["risk_state"] = RISK_STATE_LABELS.get(
            str(live_regime.get("risk_state") or ""),
            str(live_regime.get("risk_state") or "미계산"),
        )
    decisions = _list(payload.get("decision_runs"))
    candidates = candidate_rows(payload)
    batches = _list(payload.get("signal_runs"))
    signals = _list(payload.get("ticker_signals"))
    proposals = _list(payload.get("portfolio_proposals"))
    risks = _list(payload.get("risk_decisions"))
    approvals = _list(payload.get("approvals"))
    latest_batch = _mapping(batches[0]) if batches else {}
    batch_status = (
        "완료" if latest_batch.get("is_complete") is True
        else "불완전" if latest_batch
        else "미생성"
    )
    return [
        {"title": "근거 묶음", "value": f"분석 실행 {len(decisions)}회", "detail": "시장·기술·재무·매크로·13F 근거를 같은 기준 시각으로 묶어요.", "status": "운영" if decisions else "기록 없음"},
        {"title": "분석 후보", "value": f"{len(candidates)}종목", "detail": "추적 종목 가운데 지금 깊게 분석할 대상을 먼저 골라요. 매수 순위는 아니에요.", "status": "완료" if candidates else "기록 없음"},
        {"title": "TradingAgents 판단", "value": f"신호 {len(signals)}건", "detail": "시장·뉴스·재무 분석과 강세·약세·위험 토론을 종목별 의견으로 정리해요.", "status": "운영" if signals else "기록 없음"},
        {"title": "신호 배치", "value": f"배치 {len(batches)}건", "detail": "요청 종목이 모두 성공했고 아직 만료되지 않은 신호만 다음 단계로 넘겨요.", "status": batch_status},
        {"title": "Shadow 최적화", "value": f"제안 {len(proposals)}건", "detail": "예상수익·확신도·위험과 한도를 이용해 돈을 쓰지 않는 목표 비중을 계산해요.", "status": "완료" if proposals else "기록 없음"},
        {"title": "위험 · 사람 승인", "value": f"심사 {len(risks)}건", "detail": "결정적 위험 한도와 사람 승인을 모두 통과해야 주문 경계로 이동해요.", "status": f"승인 요청 {len(approvals)}건" if approvals else "주문 없음"},
    ]


def _render_engine(
    payload: Mapping[str, Any],
    observed_at: Any,
    *,
    live_regime: Mapping[str, Any] | None = None,
    live_observed_at: Any = None,
) -> None:
    summary = alpha_summary(payload)
    if live_regime:
        summary["risk_state"] = RISK_STATE_LABELS.get(
            str(live_regime.get("risk_state") or ""),
            str(live_regime.get("risk_state") or "미계산"),
        )
        summary["risk_confidence"] = live_regime.get("confidence")
    snapshot = _engine_snapshot(payload)
    with st.container(border=True):
        with st.container(horizontal=True):
            st.badge("현재 운영 경로", icon=":material/account_tree:", color="blue")
            st.badge("승인 전 주문 차단", icon=":material/lock:", color="gray")
        st.subheader("TradingAgents가 판단하고 Shadow에서 먼저 검증해요")
        st.caption(
            "ML·RL·Native Fusion은 연구·확장 경로예요. 현재 정기 분석과 같은 경로로 "
            "표시하지 않으며, 실주문은 별도의 위험 심사와 사람 승인이 있어야 이동해요."
        )
        with st.container(horizontal=True):
            st.metric("최근 분석", snapshot["analysis"], border=True)
            st.metric("신호 배치", snapshot["batch"], border=True)
            st.metric("최근 위험 심사", snapshot["risk"], border=True)
            st.metric("주문 경계", snapshot["order"], border=True)

    st.subheader("실제 운영 흐름")
    st.caption("움직이는 선은 데이터의 이동을 설명해요. 단계 카드를 누르면 멈추고 역할을 확인할 수 있어요.")
    animated_pipeline(
        _engine_steps(payload, live_regime=live_regime),
        key="alpha_engine_pipeline",
        preview=True,
    )
    policies = policy_snapshot()
    with st.expander("현재 포트폴리오 안전 한도", icon=":material/shield:"):
        with st.container(horizontal=True):
            st.metric("종목당 최대", display_percent(policies["risk"]["max_symbol_weight"]), border=True)
            st.metric("업종당 최대", display_percent(policies["risk"]["max_sector_weight"]), border=True)
            st.metric("회전율 최대", display_percent(policies["risk"]["max_turnover"]), border=True)
            st.metric("최소 현금", display_percent(policies["risk"]["min_cash_weight"]), border=True)
        st.caption("DB 값이 아니라 현재 실행 중인 Python 정책 객체의 기본 한도예요.")
    candidates = candidate_rows(payload)
    if candidates:
        st.subheader("현재 분석 우선순위")
        chart_frame = pd.DataFrame(candidates[:10])[["종목", "분석 우선순위"]]
        st.bar_chart(chart_frame, x="종목", y="분석 우선순위", color=dashboard_palette().primary)
        dataframe(candidates[:30], key="alpha_candidate_table", column_config={"분석 우선순위": st.column_config.ProgressColumn("분석 우선순위", min_value=0.0, max_value=1.0, format="percent"), "기준 시각": st.column_config.DatetimeColumn("기준 시각", format="YYYY-MM-DD HH:mm")})
        st.caption("이 순위는 매수 추천이 아니라 깊이 분석할 종목의 우선순위예요.")
    else:
        st.caption("아직 저장된 분석 우선순위가 없어요. 현재 경로와 안전 한도는 위에서 확인할 수 있어요.")

    regimes = _list(payload.get("market_regimes"))
    runs = _list(payload.get("decision_runs"))
    if live_regime or regimes or runs:
        left, right = st.columns(2)
        with left.container(border=True):
            st.markdown("**시장 국면 판정**")
            if live_regime or (regimes and isinstance(regimes[0], Mapping)):
                regime = live_regime or regimes[0]
                st.metric("현재 상태", summary["risk_state"], border=False)
                st.write(f"추세 **{regime.get('trend') or '—'}** · 변동성 **{regime.get('volatility_state') or '—'}** · 유동성 **{regime.get('liquidity_state') or '—'}** · 매크로 **{regime.get('macro_state') or '—'}**")
                basis = "실시간 가격 화면 계산" if live_regime else "저장 결과"
                st.caption(f"{basis} · 기준 {format_time(regime.get('as_of_at'))}")
            else:
                st.caption("저장된 시장 국면 계산 결과가 없어요.")
        with right.container(border=True):
            st.markdown("**최근 판단 실행**")
            if runs and isinstance(runs[0], Mapping):
                run = runs[0]
                st.metric("실행 상태", str(run.get("status") or "—"), border=False)
                st.write(f"단계 **{run.get('stage') or '—'}** · 후보 **{len(_list(run.get('candidate_tickers')))}종목** · 코드 **{str(run.get('code_commit') or '—')[:10]}**")
                st.caption(f"완료 {format_time(run.get('finished_at') or run.get('started_at'))}")
            else:
                st.caption("저장된 판단 실행 결과가 없어요.")
    sources = [SOURCE_DB, SOURCE_CALC]
    if live_regime:
        sources.append(SOURCE_LIVE)
    source_note(
        *sources,
        observed_at=live_observed_at or observed_at,
        detail="현재 코드 정책·최근 저장 결과·세션 계산을 함께 표시",
    )


def _render_models(payload: Mapping[str, Any], observed_at: Any) -> None:
    policies = policy_snapshot()
    models = model_rows(payload)
    evaluations = evaluation_rows(payload)
    artifacts = _list(payload.get("model_artifacts"))
    promotions = _list(payload.get("promotions"))
    training = _list(payload.get("training_samples"))
    with st.container(horizontal=True):
        st.metric("등록 Artifact", f"{len(artifacts)}개", border=True)
        st.metric("최근 학습 표본", f"{len(training)}건", border=True, help="화면이 읽은 최근 행 수예요. 전체 누적 건수와 다를 수 있어요.")
        st.metric("포트폴리오 평가", f"{len(evaluations)}건", border=True)
        st.metric("승격 기록", f"{len(promotions)}건", border=True)

    st.subheader("모델 성능과 재현성")
    if models:
        dataframe(models, key="alpha_model_table", column_config={"OOS 방향 적중률": st.column_config.NumberColumn(format="percent"), "OOS 순위 상관": st.column_config.NumberColumn(format="%.3f"), "OOS RMSE": st.column_config.NumberColumn(format="%.5f"), "검증 방향 적중률": st.column_config.NumberColumn(format="percent"), "학습 시작": st.column_config.DatetimeColumn(format="YYYY-MM-DD"), "학습 종료": st.column_config.DatetimeColumn(format="YYYY-MM-DD"), "생성 시각": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")})
    else:
        st.info("저장된 모델 Artifact가 없어요. 지원되는 학습 로직과 안전 한도는 아래에 표시해요.")
    if evaluations:
        st.subheader("표본 외 · 워크포워드 검증")
        dataframe(evaluations, key="alpha_evaluation_table", column_config={name: st.column_config.NumberColumn(format="percent") for name in ("총수익률", "벤치마크", "초과수익률", "최대 낙폭", "연환산 변동성", "회전율")})

    st.subheader("연구·확장 모델 구조")
    st.caption("아래 Fast Ranker와 Native Fusion은 구현된 연구 경로이며, 현재 정기 TradingAgents 분석과 동일한 운영 경로는 아니에요.")
    fusion = policies["fusion"]
    ranker = policies["ranker"]
    optimizer = policies["optimizer"]
    risk = policies["risk"]
    left, right = st.columns(2)
    with left.container(border=True):
        st.markdown("**신호 융합**")
        fusion_labels = {
            "numeric": "수치 모델",
            "market": "시장",
            "fundamental": "펀더멘털",
            "macro": "매크로",
            "event": "이벤트",
            "debate": "모델 토론",
        }
        fusion_rows = [
            {"입력": fusion_labels.get(name, name), "기본 비중": weight}
            for name, weight in fusion["component_weights"].items()
        ]
        st.bar_chart(pd.DataFrame(fusion_rows), x="입력", y="기본 비중", color=dashboard_palette().primary)
        st.caption(str(fusion["rule"]))
    with right.container(border=True):
        st.markdown("**Fast Ranker**")
        st.write(f"기존 정량 점수 **{ranker['baseline_weight']:.0%}** + 11개 영역 점수 **{ranker['numeric_weight']:.0%}**로 최대 **{ranker['max_candidates']}종목**을 골라요.")
        rank_rows = sorted(({"영역": DOMAIN_LABELS.get(name, name), "가중치": weight} for name, weight in ranker["domain_weights"].items()), key=lambda row: row["가중치"], reverse=True)
        dataframe(rank_rows, key="alpha_ranker_weights", column_config={"가중치": st.column_config.ProgressColumn(min_value=0.0, max_value=0.15, format="percent")})

    with st.container(horizontal=True):
        st.metric("종목당 최대", display_percent(risk["max_symbol_weight"]), border=True)
        st.metric("업종당 최대", display_percent(risk["max_sector_weight"]), border=True)
        st.metric("회전율 최대", display_percent(risk["max_turnover"]), border=True)
        st.metric("최소 현금", display_percent(risk["min_cash_weight"]), border=True)
        st.metric("최대 종목", f"{risk['max_positions']}종목", border=True)
    with st.container(border=True):
        st.markdown("**포트폴리오 최적화와 안전 경계**")
        st.write(f"기대수익×확신도에서 위험 페널티 **{optimizer['risk_aversion']:.1f}**와 회전율 페널티 **{optimizer['turnover_penalty']:.2f}**를 빼 목표 비중을 계산해요. 이후 결정적 위험 게이트가 집중도·유동성·변동성·베타·상관·노후 제안을 다시 검사해요.")
        st.caption("모델은 이 한도를 바꿀 수 없고, 모델 승격은 자동으로 실행되지 않아요.")
    if promotions:
        st.subheader("모델 승격 기록")
        promotion_rows = [{"Artifact": row.get("artifact_id"), "이전 단계": row.get("from_stage"), "다음 단계": row.get("to_stage"), "상태": row.get("status"), "승인 시각": row.get("approved_at"), "생성 시각": row.get("created_at")} for row in promotions if isinstance(row, Mapping)]
        dataframe(promotion_rows, key="alpha_promotions")
    source_note(SOURCE_DB, SOURCE_CALC, observed_at=observed_at, detail="모델 성과는 저장 결과, 가중치와 한도는 현재 Python 정책 기준")


def _trace_steps(trace: Mapping[str, Any], ticker: str) -> list[dict[str, str]]:
    candidate = _mapping(trace.get("candidate"))
    feature = _mapping(trace.get("event_feature"))
    signal = _mapping(trace.get("signal"))
    signal_body = _mapping(signal.get("proposal"))
    proposal = _mapping(trace.get("proposal"))
    weights = _mapping(proposal.get("weights"))
    risk = _mapping(trace.get("risk"))
    approval = _mapping(trace.get("approval"))
    intent = _mapping(trace.get("intent"))
    orders = _list(trace.get("orders"))
    fills = _list(trace.get("fills"))
    tca = _list(trace.get("tca_reports"))
    evaluation = _mapping(trace.get("evaluation"))
    return [
        {"title": "후보 선별", "value": f"#{candidate.get('rank_position')} · {display_percent(candidate.get('rank_score'))}" if candidate else "기록 없음", "detail": f"{candidate.get('domain_count') or 0}개 근거 영역" if candidate else "Fast Ranker 결과가 없어요.", "status": str(candidate.get("feature_version") or "미생성")},
        {"title": "이벤트 Feature", "value": f"중요도 {display_percent(feature.get('event_importance'))}" if feature else "기록 없음", "detail": f"이벤트 {feature.get('event_count') or 0}건 · 고영향 {feature.get('high_impact_event_count') or 0}건" if feature else "이벤트 snapshot이 없어요.", "status": str(feature.get("feature_version") or "미생성")},
        {"title": "종목 신호", "value": str(signal_body.get("signal") or signal_body.get("action") or "기록 없음"), "detail": f"기대 초과수익 {display_percent(signal_body.get('expected_excess_return'))} · 확신 {display_percent(signal_body.get('confidence'))}" if signal else "융합 신호가 없어요.", "status": "유효" if signal else "미생성"},
        {"title": "목표 비중", "value": display_percent(weights.get(ticker)) if proposal else "기록 없음", "detail": f"출처 {proposal.get('source_type') or '—'} · 확신 {display_percent(proposal.get('confidence'))}" if proposal else "포트폴리오 제안이 없어요.", "status": str(proposal.get("stage") or "미생성")},
        {"title": "위험 심사", "value": "통과" if risk.get("is_approved") is True else "차단" if risk else "기록 없음", "detail": f"조정 {len(_list(risk.get('adjustments')))}건 · 위반 {len(_list(risk.get('violations')))}건" if risk else "위험 심사 기록이 없어요.", "status": str(risk.get("policy_key") or "미심사")},
        {"title": "실행 Intent", "value": str(intent.get("status") or "생성 없음"), "detail": f"{intent.get('intent_id') or 'ID 없음'} · {intent.get('execution_mode') or '모드 미정'}" if intent else "RiskGate 이후 실행 의도가 생성되지 않았어요.", "status": "읽기 전용"},
        {"title": "사람 승인 · 주문", "value": f"승인 {approval.get('status') or '요청 없음'}", "detail": f"주문 {len(orders)}건 · 결정 {approval.get('decision') or '—'}" if approval else "승인 없이는 주문 경계로 이동하지 않아요.", "status": "읽기 전용"},
        {"title": "체결 · 결과", "value": f"체결 {len(fills)}건", "detail": f"TCA {len(tca)}건 · 평가 {evaluation.get('evaluated_at') or '기록 없음'}" if (tca or evaluation) else "체결·TCA·평가 기록이 아직 없어요.", "status": "관측 전용"},
    ]


def _merge_execution_payload(
    payload: Mapping[str, Any],
    execution_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Alpha Lab 사실에 실행 원장 배열을 덧붙여 한 번의 추적에서 연결한다."""

    merged = dict(payload)
    for key in ("intents", "approvals", "orders", "fills", "tca_reports", "reconciliations"):
        merged[key] = list(execution_payload.get(key) or [])
    return merged


def _render_trace(payload: Mapping[str, Any], observed_at: Any) -> None:
    symbols = sorted({str(row.get("ticker") or "").upper() for key in ("candidate_ranks", "event_features", "ticker_signals") for row in _list(payload.get(key)) if isinstance(row, Mapping) and row.get("ticker")})
    if not symbols:
        st.info("추적할 후보·Feature·신호가 아직 없어요. 모델 연구에서 현재 판단 규칙을 확인할 수 있어요.")
        return
    ticker = st.selectbox("판단을 추적할 종목", symbols, key="alpha_trace_ticker")
    trace = trace_for_ticker(payload, ticker)
    st.subheader(f"{ticker} 판단 경로")
    animated_pipeline(
        _trace_steps(trace, ticker),
        key=f"alpha_trace_pipeline_{ticker}",
        preview=False,
    )
    execution_rows = []
    for key, label in (("intent", "Intent"), ("approval", "승인"), ("orders", "주문"), ("fills", "체결"), ("tca_reports", "TCA")):
        value = trace.get(key)
        count = len(value) if isinstance(value, (list, tuple)) else int(bool(value))
        execution_rows.append({"실행 관측": label, "건수": count})
    if any(row["건수"] for row in execution_rows):
        st.subheader("실행 원장 연결")
        dataframe(execution_rows, key=f"alpha_trace_execution_counts:{ticker}")
        st.caption("이 화면은 실행 원장을 읽기만 하며 주문을 생성·수정·취소하지 않습니다.")
    candidate = _mapping(trace.get("candidate"))
    domains = _mapping(candidate.get("domain_scores"))
    if domains:
        domain_rows = [{"판단 근거": DOMAIN_LABELS.get(str(name), str(name)), "점수": float(score)} for name, score in domains.items() if isinstance(score, (int, float))]
        domain_rows.sort(key=lambda row: row["점수"], reverse=True)
        left, right = st.columns(2)
        with left.container(border=True):
            st.markdown("**후보 점수 구성**")
            st.bar_chart(pd.DataFrame(domain_rows), x="판단 근거", y="점수", color=dashboard_palette().primary)
        with right.container(border=True):
            st.markdown("**심사 결과와 조정**")
            risk = _mapping(trace.get("risk"))
            violations = _list(risk.get("violations"))
            adjustments = _list(risk.get("adjustments"))
            if adjustments:
                st.write("조정: " + " · ".join(str(item) for item in adjustments))
            if violations:
                st.write("차단 사유: " + " · ".join(str(item) for item in violations))
            if not adjustments and not violations:
                st.caption("저장된 조정 또는 위반 기록이 없어요.")
    source_note(SOURCE_DB, SOURCE_CALC, observed_at=observed_at, detail=f"{ticker}의 최근 단계별 사실을 ID로 연결")


def _provider_payload() -> list[dict[str, Any]]:
    result = provider_statuses()
    rows = result_payload(result, default=[]) or []
    if not result_status(result, empty_text="제공처 정책 상태가 없습니다"):
        rows = []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _render_news() -> None:
    _provider_payload()
    ticker_result = load_tickers()
    ticker_rows = result_payload(ticker_result, default=[]) or []
    tickers = sorted({str(row.get("ticker", "")).upper() for row in ticker_rows if row.get("ticker")})
    if getattr(ticker_result, "status", "error") != "ok":
        result_status(ticker_result, empty_text="저장된 추적 종목이 없습니다")
    with st.container(key="intel_query_inputs"):
        selection_col, topic_col = st.columns(2)
        selected_ticker = selection_col.selectbox("관련 종목", tickers, index=None, placeholder="실제 추적 종목(선택)", disabled=not tickers, key="intel_selected_ticker")
        topic = topic_col.text_input("시장 주제", placeholder="예: 미국 금리 또는 반도체", key="intel_topic")
    query = topic.strip() or (selected_ticker or "")
    with st.form("news-query", border=True):
        st.caption("검색 범위를 확인한 뒤 외부 호출을 실행하세요. 입력 변경만으로는 호출하지 않습니다.")
        fetch_news = st.form_submit_button("승인된 제공처에서 뉴스 조회", type="primary", icon=":material/search:", disabled=not bool(query))
    if fetch_news:
        news_result = load_live_news(query, ticker=selected_ticker)
        if result_status(news_result, empty_text="허용된 제공처에서 현재 기사를 찾지 못했습니다"):
            raw_articles = result_payload(news_result, default=[]) or []
            st.session_state["dashboard_live_news"] = {"query": query, "articles": [_normalise_article(row, selected_ticker, usage="참고용") for row in raw_articles], "observed_at": getattr(news_result, "observed_at", None), "usage_note": getattr(news_result, "message", None)}
        else:
            st.session_state.pop("dashboard_live_news", None)
    stored_evidence: list[dict[str, Any]] = []
    archived_news_count = 0
    case_observed = None
    if selected_ticker:
        case_result = load_ai_data(selected_ticker)
        case_payload = result_payload(case_result, default={}) or {}
        for case in case_payload.get("cases", []):
            case_observed = case_observed or case.get("as_of_at")
            digest = (
                case.get("evidence_digest")
                if isinstance(case.get("evidence_digest"), dict)
                else {}
            )
            source_news_count = sum(
                int(count or 0)
                for name, count in (digest.get("source_counts") or {}).items()
                if any(
                    vendor in str(name).lower()
                    for vendor in ("yfinance", "alpha_vantage")
                )
            )
            domain_news_count = sum(
                int(count or 0)
                for name, count in (digest.get("domain_counts") or {}).items()
                if "news" in str(name).lower()
            )
            archived_news_count += max(source_news_count, domain_news_count)
            for evidence in case.get("evidence_items") or []:
                if not isinstance(evidence, dict):
                    continue
                domain = str(evidence.get("domain") or "").lower()
                source = str(evidence.get("source") or "").lower()
                if "news" not in domain and not any(
                    vendor in source for vendor in ("yfinance", "alpha_vantage")
                ):
                    continue
                stored_evidence.append({
                    "근거 ID": evidence.get("evidence_id") or "—",
                    "출처": evidence.get("source") or "출처 메타데이터 없음",
                    "관측 시각": format_time(evidence.get("observed_at")),
                    "사용 가능 시각": format_time(evidence.get("available_at")),
                    "시점 품질": evidence.get("timing_status") or "—",
                    "상태": "AI 분석에 사용됨",
                })
    if stored_evidence:
        st.markdown("**저장된 case 외부 근거 메타데이터**")
        dataframe(stored_evidence, key=f"intel_stored_news:{selected_ticker}")
        source_note(
            SOURCE_DB,
            observed_at=case_observed,
            detail="reporting read model의 제한된 news evidence 메타데이터",
        )
    elif selected_ticker and archived_news_count:
        st.info(
            f"AI 분석에 사용된 뉴스 출처 근거 {archived_news_count}건의 원문은 "
            "검증 가능한 아티팩트에 보관되어 있어요."
        )
    elif selected_ticker:
        st.info("선택 종목의 저장된 case에 표시 가능한 뉴스 메타데이터가 없습니다.")
    else:
        st.caption("종목을 선택하면 해당 case에 실제 사용된 저장 뉴스 근거를 함께 표시합니다.")
    live_state = st.session_state.get("dashboard_live_news")
    if live_state and live_state.get("query") == query:
        st.markdown("**현재 참고용 뉴스 조회**")
        dataframe(live_state.get("articles", []), key=f"intel_live_news:{query}")
        source_note(SOURCE_LIVE, SOURCE_CALC, observed_at=live_state.get("observed_at"), detail="감성 태그는 제목·짧은 요약의 화면 키워드 계산")


def _render_provider_status(kind: str | None = None) -> None:
    rows = _provider_payload()
    if kind is not None:
        rows = [row for row in rows if row.get("kind") == kind]
    if kind == "social":
        st.subheader("소셜 미디어 사용 가능 상태")
        social_rows = [{"제공처": row.get("provider"), "상태": row.get("status") or "사용 불가", "이유": row.get("reason") or "정책 상태 설명 없음", "AI 사용": row.get("analysis_use") or "사용 불가"} for row in rows]
        dataframe(social_rows, key="intel_social_status")
        source_note(SOURCE_CALC, detail="허용 목록·승인 플래그·일일 한도 기준")
        return
    available_count = sum(str(row.get("status")) == "available" for row in rows)
    blocked_count = sum(str(row.get("status")) in {"blocked", "offline"} for row in rows)
    with st.container(horizontal=True):
        st.metric("승인·사용 가능", f"{available_count}개", border=True)
        st.metric("차단·오프라인", f"{blocked_count}개", border=True)
    dataframe(rows, key="intel_provider_all")
    render_source_help()


def render() -> None:
    """모델·학습 페이지가 탭 하나로 불러 쓴다. 페이지 단독 진입점은 아니다."""
    st.title("ATLAS 투자 엔진")
    st.caption("근거 수집부터 모델 판단, 포트폴리오, 위험 심사까지 현재 도달 지점을 확인해요.")

    view = view_selector("투자 엔진 보기", ("엔진 개요", "모델·검증", "종목 추적", "뉴스", "소셜", "연결 상태"), key="intelligence_adaptive_view", default="엔진 개요")
    if view in {"엔진 개요", "모델·검증", "종목 추적"}:
        alpha_result = load_alpha_lab_data()
        payload = result_payload(alpha_result, default={}) or {}
        if getattr(alpha_result, "message", None) and getattr(alpha_result, "status", None) == "ok":
            st.warning(str(alpha_result.message), icon=":material/warning:")
        if getattr(alpha_result, "status", None) == "empty":
            st.caption("아직 저장된 실행 기록은 없어요. 아래에는 현재 연결 구조와 코드 정책을 표시해요.")
            available = False
        else:
            available = result_status(alpha_result, empty_text="저장된 투자 엔진 실행 결과가 없습니다")
        if view == "엔진 개요":
            price_result = load_price_history(("SPY", "QQQ", "^VIX"), period="3mo")
            live_regime = live_regime_from_prices(result_payload(price_result, default=None))
            _render_engine(
                payload,
                getattr(alpha_result, "observed_at", None),
                live_regime=live_regime,
                live_observed_at=getattr(price_result, "observed_at", None),
            )
        elif view == "모델·검증":
            _render_models(payload, getattr(alpha_result, "observed_at", None))
        elif view == "종목 추적" and available:
            execution_result = load_execution_data()
            execution_payload = result_payload(execution_result, default={}) or {}
            trace_payload = _merge_execution_payload(payload, execution_payload)
            _render_trace(trace_payload, getattr(alpha_result, "observed_at", None))
    elif view == "뉴스":
        _render_news()
    elif view == "소셜":
        _render_provider_status("social")
    else:
        _render_provider_status()
