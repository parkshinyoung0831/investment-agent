"""저장된 투자 엔진 사실과 코드 정책을 화면용 설명으로 투영한다."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from investment_agent.platform.serialization import parse_datetime
from investment_agent.reporting.services.investment import (
    build_fusion_policy_read_model,
    build_live_regime_read_model,
    build_optimizer_policy_read_model,
    build_ranker_policy_read_model,
    build_risk_policy_read_model,
)


DOMAIN_LABELS: Mapping[str, str] = {
    "price_anomaly": "가격 이상",
    "volume_anomaly": "거래량 이상",
    "momentum": "모멘텀",
    "technical_regime_change": "기술 국면",
    "fundamental_change": "펀더멘털",
    "estimate_revision": "예상치 변화",
    "sec_event": "SEC 이벤트",
    "news_velocity": "뉴스 속도",
    "social_velocity": "소셜 속도",
    "event_importance": "이벤트 중요도",
    "portfolio_relevance": "포트폴리오 연관",
}

STAGE_LABELS: Mapping[str, str] = {
    "shadow": "섀도",
    "backtest": "백테스트",
    "out_of_sample": "표본 외 검증",
    "walk_forward": "워크포워드",
    "paper": "모의 운용",
    "live": "실전",
}

RISK_STATE_LABELS: Mapping[str, str] = {
    "RISK_ON": "위험 선호",
    "NORMAL": "중립",
    "RISK_OFF": "위험 회피",
    "CRISIS": "위기",
}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    values = payload.get(key)
    if not isinstance(values, list):
        return []
    return [dict(row) for row in values if isinstance(row, Mapping)]


def latest_rows(rows: Iterable[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    """가장 최근 시각과 정확히 같은 snapshot 행만 보존한다."""

    parsed: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            timestamp = parse_datetime(str(value)).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        parsed.append((timestamp, dict(row)))
    if not parsed:
        return []
    latest = max(timestamp for timestamp, _ in parsed)
    return [row for timestamp, row in parsed if timestamp == latest]


def alpha_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """첫 화면 지표를 실제 최근 행에서만 계산한다."""

    regimes = latest_rows(_rows(payload, "market_regimes"), "as_of_at")
    candidates = latest_rows(_rows(payload, "candidate_ranks"), "as_of_at")
    signals = _rows(payload, "ticker_signals")
    artifacts = _rows(payload, "model_artifacts")
    risks = _rows(payload, "risk_decisions")
    latest_regime = regimes[0] if regimes else {}
    approved = sum(row.get("is_approved") is True for row in risks)
    return {
        "risk_state": RISK_STATE_LABELS.get(
            str(latest_regime.get("risk_state") or ""),
            str(latest_regime.get("risk_state") or "미계산"),
        ),
        "risk_confidence": _number(latest_regime.get("confidence")),
        "candidate_count": len(candidates),
        "signal_count": len(signals),
        "model_count": len(artifacts),
        "live_model_count": sum(row.get("stage") == "live" for row in artifacts),
        "paper_model_count": sum(row.get("stage") == "paper" for row in artifacts),
        "risk_approval_count": approved,
        "risk_review_count": len(risks),
        "as_of_at": latest_regime.get("as_of_at")
        or (candidates[0].get("as_of_at") if candidates else None),
    }


def candidate_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """최신 Fast Ranker snapshot을 비교 가능한 행으로 만든다."""

    candidates = latest_rows(_rows(payload, "candidate_ranks"), "as_of_at")
    candidates.sort(key=lambda row: int(row.get("rank_position") or 10**9))
    result: list[dict[str, Any]] = []
    for row in candidates:
        domains = {
            str(name): score
            for name, score in _as_mapping(row.get("domain_scores")).items()
            if _number(score) is not None
        }
        strongest = sorted(domains.items(), key=lambda item: float(item[1]), reverse=True)[:3]
        result.append(
            {
                "순위": int(row.get("rank_position") or len(result) + 1),
                "종목": str(row.get("ticker") or "—"),
                "분석 우선순위": _number(row.get("rank_score")),
                "근거 영역": int(row.get("domain_count") or len(domains)),
                "주요 근거": " · ".join(
                    f"{DOMAIN_LABELS.get(name, name)} {float(score):.0%}"
                    for name, score in strongest
                ) or "근거 없음",
                "Feature 버전": str(row.get("feature_version") or "—"),
                "기준 시각": row.get("as_of_at"),
            }
        )
    return result


def model_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """모델 artifact의 재현성과 OOS 성과를 평면 행으로 만든다."""

    result: list[dict[str, Any]] = []
    for row in _rows(payload, "model_artifacts"):
        params = _as_mapping(row.get("params"))
        oos = _as_mapping(params.get("out_of_sample"))
        validation = _as_mapping(params.get("validation"))
        result.append(
            {
                "모델": str(row.get("algorithm") or "—").upper(),
                "단계": STAGE_LABELS.get(str(row.get("stage") or ""), str(row.get("stage") or "—")),
                "Feature": str(row.get("feature_version") or "—"),
                "OOS 방향 적중률": _number(oos.get("direction_accuracy")),
                "OOS 순위 상관": _number(oos.get("rank_correlation")),
                "OOS RMSE": _number(oos.get("rmse")),
                "검증 방향 적중률": _number(validation.get("direction_accuracy")),
                "OOS 표본": int(oos.get("sample_count") or 0),
                "학습 시작": row.get("train_start"),
                "학습 종료": row.get("train_end"),
                "생성 시각": row.get("created_at"),
                "Artifact": str(row.get("artifact_id") or "—"),
            }
        )
    return result


def evaluation_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """포트폴리오 평가와 누수·생존편향 검증을 같은 행에 둔다."""

    result: list[dict[str, Any]] = []
    for row in _rows(payload, "portfolio_evaluations"):
        checks = (
            row.get("survivorship_check_passed") is True,
            row.get("leakage_check_passed") is True,
            row.get("data_integrity_check_passed") is True,
        )
        result.append(
            {
                "검증": STAGE_LABELS.get(
                    str(row.get("evaluation_kind") or ""),
                    str(row.get("evaluation_kind") or "—"),
                ),
                "총수익률": _number(row.get("total_return")),
                "벤치마크": _number(row.get("benchmark_return")),
                "초과수익률": _number(row.get("excess_return")),
                "최대 낙폭": _number(row.get("max_drawdown")),
                "연환산 변동성": _number(row.get("annualized_volatility")),
                "회전율": _number(row.get("turnover")),
                "안전 검증": "3/3 통과" if all(checks) else f"{sum(checks)}/3 통과",
                "평가 시각": row.get("evaluated_at"),
            }
        )
    return result


def trace_for_ticker(payload: Mapping[str, Any], ticker: str) -> dict[str, Any]:
    """한 종목이 후보에서 실행·평가까지 지나간 최근 사실을 ID로 연결한다."""

    symbol = str(ticker or "").upper().strip()
    candidates = [
        row for row in _rows(payload, "candidate_ranks")
        if str(row.get("ticker") or "").upper() == symbol
    ]
    features = [
        row for row in _rows(payload, "event_features")
        if str(row.get("ticker") or "").upper() == symbol
    ]
    signals = [
        row for row in _rows(payload, "ticker_signals")
        if str(row.get("ticker") or "").upper() == symbol
    ]
    proposals = [
        row for row in _rows(payload, "portfolio_proposals")
        if symbol in _as_mapping(row.get("weights"))
    ]
    proposal = proposals[0] if proposals else {}
    proposal_id = str(proposal.get("proposal_id") or "")
    risks = [
        row for row in _rows(payload, "risk_decisions")
        if str(row.get("proposal_id") or "") == proposal_id
    ]
    risk = risks[0] if risks else {}
    risk_id = str(risk.get("risk_decision_id") or "")
    intents = [
        row for row in _rows(payload, "intents")
        if (risk_id and str(row.get("risk_decision_id") or "") == risk_id)
        or (proposal_id and str(row.get("proposal_id") or "") == proposal_id)
    ]
    intent = intents[0] if intents else {}
    intent_id = str(intent.get("intent_id") or "")
    approvals = [
        row for row in _rows(payload, "approvals")
        if (intent_id and str(row.get("intent_id") or "") == intent_id)
        or str(row.get("risk_decision_id") or "") == risk_id
        or (proposal_id and str(row.get("proposal_id") or "") == proposal_id)
    ]
    orders = [
        row for row in _rows(payload, "orders")
        if intent_id and str(row.get("intent_id") or "") == intent_id
    ]
    order_ids = {
        str(row.get("client_order_id"))
        for row in orders
        if row.get("client_order_id")
    }
    fills = [
        row for row in _rows(payload, "fills")
        if str(row.get("client_order_id") or "") in order_ids
    ]
    tca_reports = [
        row for row in _rows(payload, "tca_reports")
        if (intent_id and str(row.get("intent_id") or "") == intent_id)
        or str(row.get("client_order_id") or "") in order_ids
    ]
    evaluations = [
        row for row in _rows(payload, "portfolio_evaluations")
        if proposal_id and str(row.get("proposal_id") or "") == proposal_id
    ]
    return {
        "candidate": candidates[0] if candidates else {},
        "event_feature": features[0] if features else {},
        "signal": signals[0] if signals else {},
        "proposal": proposal,
        "risk": risk,
        "intent": intent,
        "approval": approvals[0] if approvals else {},
        "orders": orders,
        "fills": fills,
        "tca_reports": tca_reports,
        "evaluation": evaluations[0] if evaluations else {},
    }


def policy_snapshot() -> dict[str, Any]:
    """DB가 비어 있어도 현재 코드가 실제 적용하는 결정 규칙을 반환한다."""

    return {
        "ranker": build_ranker_policy_read_model(),
        "fusion": build_fusion_policy_read_model(),
        "optimizer": build_optimizer_policy_read_model(),
        "risk": build_risk_policy_read_model(),
        "promotion": {
            "auto_promoted": False,
            "rule": "OOS·워크포워드·섀도·모의 운용 증거를 통과한 뒤 사람의 명시적 승인 필요",
        },
    }


def live_regime_from_prices(value: Any) -> dict[str, Any] | None:
    """SPY·QQQ·VIX 최근 가격으로 저장하지 않는 시장 국면 미리보기를 계산한다."""

    return build_live_regime_read_model(value)


__all__ = [
    "DOMAIN_LABELS",
    "RISK_STATE_LABELS",
    "STAGE_LABELS",
    "alpha_summary",
    "candidate_rows",
    "evaluation_rows",
    "latest_rows",
    "live_regime_from_prices",
    "model_rows",
    "policy_snapshot",
    "trace_for_ticker",
]
