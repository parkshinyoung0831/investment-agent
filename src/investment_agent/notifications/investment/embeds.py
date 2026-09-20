"""자동매매 판단·체결을 Discord embed로 조립한다.

여기서 하는 일은 조립뿐이다 — DB도 네트워크도 만지지 않으므로 그대로 단위 테스트한다.

카드에 적는 것은 **원장에 실제로 있는 값**뿐이다. 엔진 구성을 footer에 사실대로
적고, 아직 판단에 반영되지 않는 요소(강화학습 정책 등)를 반영된 것처럼 쓰지 않는다.
근거가 없는 채로 내린 판단이면 `missing_data`를 감추지 않고 그대로 보여준다 —
"무엇을 못 보고 판단했나"가 신뢰도만큼 중요하다.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from investment_agent.platform.serialization import finite_float
from .palette import COLOR_APPROVED, COLOR_INFO, COLOR_REJECTED
from investment_agent.reporting.services.investment import CASH_SYMBOL

ENGINE_FOOTER = "factor 기대수익 · TradingAgents 논지 검증 → cvxpy optimizer → 결정론적 RiskGate"
# 카드 한 장에 담을 상한. Discord embed field는 1024자 제한이 있다.
_MAX_HOLDINGS = 10
_MAX_LINES = 3
_MAX_VIOLATIONS = 6
_EMPTY = "없음"

# TradingAgents가 적은 의견 단어. 주문이 아니다 — 실제 비중 변화는 System 목표가 정한다.
_SIGNAL_LABELS = {
    "open": "편입 의견",
    "increase": "확대 의견",
    "hold": "유지 의견",
    "reduce": "축소 의견",
    "exit": "청산 의견",
    "watch": "관찰",
    "avoid": "회피",
}
_BUY_SIDE = frozenset({"open", "increase"})
_SELL_SIDE = frozenset({"reduce", "exit"})
# optimizer가 비중을 바꾼 주 사유(`trading.system.target.trade_reasons`). "유지 의견인데 왜 파나"에 답한다.
_REASON_LABELS = {
    "HARD_RISK_LIMIT": "위험 한도 준수",
    "THESIS_EXIT": "청산 판단",
    "ALPHA_DECAY": "전망 약화",
    "REBALANCE": "더 나은 후보로 자금 이동",
    "ALPHA_OPPORTUNITY": "전망 개선",
}
# 기대수익으로 표현할 수 없어 optimizer에 건 제약(`CONSTRAINT_*`).
_CONSTRAINT_LABELS = {
    "force_exit": "논지 붕괴로 전량 청산",
    "block_increase": "확대 금지(검증 전·품질 약화·하락 논지)",
}
_MAX_REASONS = 8


def _percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _signed_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:+.2f}%"
    except (TypeError, ValueError):
        return "—"


def _lines(values: Sequence[Any], *, limit: int = _MAX_LINES) -> str:
    """목록을 불릿으로 접는다. 비면 빈칸 대신 '없음'이라고 적는다."""
    items = [str(value).strip() for value in (values or ()) if str(value).strip()]
    if not items:
        return _EMPTY
    shown = [f"• {item}" for item in items[:limit]]
    if len(items) > limit:
        shown.append(f"• …외 {len(items) - limit}건")
    return "\n".join(shown)


def _date(value: Any) -> str:
    return str(value or "")[:10] or "—"


def _trade_reason_lines(metadata: Mapping[str, Any]) -> str:
    """바뀐 비중마다 현재→목표와 주 사유를 적는다. 사유가 원장에 없으면 줄을 만들지 않는다."""
    reasons = dict(metadata.get("trade_reasons") or {})
    rows = sorted(
        reasons.items(),
        key=lambda item: abs(float(item[1].get("target_weight") or 0) - float(item[1].get("current_weight") or 0)),
        reverse=True,
    )
    lines = []
    for symbol, row in rows[:_MAX_REASONS]:
        line = (
            f"• `{symbol}` {_percent(row.get('current_weight'))} → {_percent(row.get('target_weight'))} · "
            f"{_REASON_LABELS.get(str(row.get('code')), str(row.get('code')))}"
        )
        constraint = _CONSTRAINT_LABELS.get(str(row.get("constraint") or ""))
        if constraint:
            line += f" ({constraint})"
        if row.get("expected_return_capped"):
            line += " · 과대 기대수익 상한 적용"
        lines.append(line)
    if len(rows) > _MAX_REASONS:
        lines.append(f"• …외 {len(rows) - _MAX_REASONS}건")
    return "\n".join(lines)


def portfolio_embed(
    *,
    proposal: Mapping[str, Any],
    risk: Mapping[str, Any],
    run: Mapping[str, Any],
) -> dict[str, Any]:
    """System Portfolio 목표 카드. RiskGate 판정과 비중이 바뀐 이유가 중심이다."""
    is_approved = bool(risk.get("is_approved"))
    violations = list(risk.get("violations") or ())
    weights = dict(proposal.get("weights") or {})
    cash = weights.pop(CASH_SYMBOL, 0.0)
    holdings = sorted(
        ((symbol, float(weight)) for symbol, weight in weights.items() if float(weight) > 0.0),
        key=lambda item: item[1],
        reverse=True,
    )
    requested = list(run.get("candidate_tickers") or ())
    metadata = dict(proposal.get("metadata") or {})
    metrics = dict(risk.get("metrics") or {})

    verdict = "승인" if is_approved else "거절"
    holding_text = (
        "\n".join(f"• `{symbol}` {_percent(weight)}" for symbol, weight in holdings[:_MAX_HOLDINGS])
        or _EMPTY
    )
    # 시장위험 값이 원장에 없으면 그 자리를 0으로 채우지 않는다 — "베타 0.00"이라는 없는 사실이 카드에
    # 적힌다. 아예 빼는 게 맞다.
    metric_text = " · ".join(
        f"{label} {finite_float(metrics.get(key)):.2f}"
        for key, label in (
            ("portfolio_volatility", "변동성"),
            ("portfolio_beta", "베타"),
            ("turnover", "회전율"),
        )
        if finite_float(metrics.get(key)) is not None
    ) or _EMPTY

    fields = [
        {
            "name": f"⚖️ RiskGate 판정 · {verdict}",
            "value": (
                metric_text if is_approved
                else _lines(violations, limit=_MAX_VIOLATIONS)
            ),
            "inline": False,
        },
        {
            "name": f"📊 목표 비중 (현금 {_percent(cash)})",
            "value": holding_text,
            "inline": False,
        },
        {
            "name": "🔎 판단 범위",
            "value": (
                f"후보 **{len(requested)}**종목 · "
                f"실행 상태 `{run.get('status', '—')}` · "
                f"factor 횡단면 `{_date(metadata.get('factor_snapshot_as_of'))}`"
            ),
            "inline": False,
        },
        {
            "name": "🧭 판단 근거",
            "value": _lines(proposal.get("reasoning") or ()),
            "inline": False,
        },
    ]
    reason_text = _trade_reason_lines(metadata)
    if reason_text:
        fields.insert(2, {"name": "🔁 비중 변경 사유", "value": reason_text[:1024], "inline": False})
    if run.get("failure_reason"):
        fields.append({
            "name": "⚠️ 실행 실패 사유",
            "value": str(run["failure_reason"])[:1000],
            "inline": False,
        })

    return {
        "title": f"System Portfolio 목표 · {_date(proposal.get('as_of_at'))}",
        "description": (
            f"신뢰도 **{_percent(proposal.get('confidence'))}** · "
            f"제안 `{proposal.get('proposal_id', '—')}`"
        ),
        "color": COLOR_APPROVED if is_approved else COLOR_REJECTED,
        "fields": fields,
        "footer": {"text": ENGINE_FOOTER},
    }


def candidate_embed(*, decision: Mapping[str, Any]) -> dict[str, Any]:
    """종목 하나의 심층 판단 카드. 근거와 '없는 근거'를 함께 적는다."""
    final = dict(decision.get("final_decision") or {})
    signal = str(final.get("signal") or "hold")
    label = _SIGNAL_LABELS.get(signal, signal)
    if signal in _BUY_SIDE:
        color = COLOR_APPROVED
    elif signal in _SELL_SIDE:
        color = COLOR_REJECTED
    else:
        color = COLOR_INFO

    evidence_count = len(list(final.get("evidence_ids") or ()))
    previous = final.get("previous_signal")
    # LLM의 target_weight는 optimizer가 읽지 않는다. 카드에 "목표 비중"으로 적으면 반영되지 않는
    # 값을 반영된 것처럼 보이게 한다 — 대신 직전 판단과의 연속성을 보여준다.
    continuity = (
        f"직전 판단 {_SIGNAL_LABELS.get(str(previous), str(previous))}"
        + (" → **방향 변경**" if (previous in _BUY_SIDE and signal in _SELL_SIDE)
           or (previous in _SELL_SIDE and signal in _BUY_SIDE) else "")
        if previous else "직전 판단 없음"
    )
    return {
        "title": f"[{label}] {decision.get('ticker', '—')}",
        "description": f"기준 {_date(decision.get('as_of_at'))} · 사례 `{decision.get('case_key', '—')}`",
        "color": color,
        "fields": [
            {
                "name": "📈 신호",
                "value": (
                    f"기대 초과수익 **{_signed_percent(final.get('expected_excess_return'))}** · "
                    f"상승확률 {_percent(final.get('probability_up'))}\n"
                    f"신뢰도 {_percent(final.get('confidence'))} · {continuity}"
                ),
                "inline": False,
            },
            {
                "name": "🧭 판단 근거",
                "value": _lines(final.get("reasoning") or ()),
                "inline": False,
            },
            {
                "name": f"🔗 인용 근거 {evidence_count}건 · 확보하지 못한 근거",
                "value": _lines(final.get("missing_data") or ()),
                "inline": False,
            },
        ],
        "footer": {"text": ENGINE_FOOTER},
    }


def trade_embed(
    *,
    order: Mapping[str, Any],
    fills: Sequence[Mapping[str, Any]],
    execution_mode: str,
) -> dict[str, Any]:
    """실제 주문·체결 기록 카드. 체결 전이면 체결값을 지어내지 않는다."""
    side = str(order.get("side") or "buy").lower()
    filled_quantity = sum(float(fill.get("quantity") or 0.0) for fill in fills)
    commission = sum(float(fill.get("commission") or 0.0) for fill in fills)
    if filled_quantity > 0:
        notional = sum(
            float(fill.get("quantity") or 0.0) * float(fill.get("price") or 0.0)
            for fill in fills
        )
        fill_text = (
            f"체결 **{filled_quantity:g}주** · 평균 **{notional / filled_quantity:.2f}**"
            + (f" · 수수료 {commission:.2f}" if commission else "")
        )
    else:
        fill_text = f"아직 체결 없음 (주문 상태 `{order.get('status', '—')}`)"

    return {
        "title": f"[{'매수' if side == 'buy' else '매도'}] {order.get('ticker', '—')}",
        "description": f"실행 대상 `{execution_mode}` · 주문 `{order.get('client_order_id', '—')}`",
        "color": COLOR_APPROVED if side == "buy" else COLOR_REJECTED,
        "fields": [
            {
                "name": "🧾 주문",
                "value": (
                    f"수량 **{float(order.get('quantity') or 0):g}주** · "
                    f"기준가 {float(order.get('reference_price') or 0):.2f}"
                ),
                "inline": False,
            },
            {"name": "✅ 체결", "value": fill_text, "inline": False},
            {
                "name": "🔐 승인 연결",
                "value": f"승인 `{order.get('approval_id', '—')}` · 의도 `{order.get('intent_id', '—')}`",
                "inline": False,
            },
        ],
        "footer": {"text": ENGINE_FOOTER},
    }


__all__ = ["ENGINE_FOOTER", "candidate_embed", "portfolio_embed", "trade_embed"]
