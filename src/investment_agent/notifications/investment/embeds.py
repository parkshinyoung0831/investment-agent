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

CASH_SYMBOL = "CASH"
ENGINE_FOOTER = "TradingAgents LLM → cvxpy optimizer → 결정론적 RiskGate"
# 카드 한 장에 담을 상한. Discord embed field는 1024자 제한이 있다.
_MAX_HOLDINGS = 10
_MAX_LINES = 3
_MAX_VIOLATIONS = 6
_EMPTY = "없음"

_SIGNAL_LABELS = {
    "open": "신규 편입",
    "increase": "비중 확대",
    "hold": "유지",
    "reduce": "비중 축소",
    "exit": "전량 청산",
    "watch": "관찰",
    "avoid": "회피",
}
_BUY_SIDE = frozenset({"open", "increase"})
_SELL_SIDE = frozenset({"reduce", "exit"})


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


def portfolio_embed(
    *,
    proposal: Mapping[str, Any],
    risk: Mapping[str, Any],
    run: Mapping[str, Any],
) -> dict[str, Any]:
    """하루 한 장의 종합 판단 카드. 승인 여부와 그 근거가 중심이다."""
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
    analysed = len(list(proposal.get("case_keys") or ()))
    metrics = dict(risk.get("metrics") or {})

    verdict = "승인" if is_approved else "거절"
    holding_text = (
        "\n".join(f"• `{symbol}` {_percent(weight)}" for symbol, weight in holdings[:_MAX_HOLDINGS])
        or _EMPTY
    )
    # shadow 경로는 시장위험을 계산하지 않아 키는 있고 값이 null이다. 그 자리를
    # 0으로 채우면 "베타 0.00"이라는 없는 사실이 카드에 적힌다 — 아예 빼는 게 맞다.
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
            "name": "🔎 분석 범위",
            "value": (
                f"분석 성공 **{analysed}/{len(requested)}**종목 · "
                f"실행 상태 `{run.get('status', '—')}` · "
                f"coverage `{(proposal.get('metadata') or {}).get('coverage', '—')}`"
            ),
            "inline": False,
        },
        {
            "name": "🧭 판단 근거",
            "value": _lines(proposal.get("reasoning") or ()),
            "inline": False,
        },
    ]
    if run.get("failure_reason"):
        fields.append({
            "name": "⚠️ 실행 실패 사유",
            "value": str(run["failure_reason"])[:1000],
            "inline": False,
        })

    return {
        "title": f"오늘의 투자 판단 · {_date(proposal.get('as_of_at'))}",
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
                    f"신뢰도 {_percent(final.get('confidence'))} · "
                    f"목표 비중 {_percent(final.get('target_weight'))}"
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
