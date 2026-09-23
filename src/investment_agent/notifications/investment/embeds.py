"""자동매매 판단·체결을 Discord embed로 조립한다.

여기서 하는 일은 조립뿐이다 — DB도 네트워크도 만지지 않으므로 그대로 단위 테스트한다.

읽는 순서는 DESIGN-system.md §3.1을 따른다: **지금 상태 → 중요한 변화 → 근거**. 첫 줄(description)만 읽어도
"주식을 얼마나 들고, 현금이 왜 그만큼이며, 게이트를 통과했나"를 알 수 있어야 한다.

카드에 적는 것은 **원장에 실제로 있는 값**뿐이다. 아직 판단에 반영되지 않는 요소를 반영된 것처럼 쓰지 않고,
LLM이 스스로 적은 확률·신뢰도는 System이 쓰는 값이 아니므로 "LLM 추정"이라고 밝힌다. 근거가 없는 채로 내린
판단이면 `missing_data`를 감추지 않는다 — "무엇을 못 보고 판단했나"가 신뢰도만큼 중요하다.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping, Sequence

from investment_agent.platform.serialization import finite_float
from .palette import COLOR_DANGER, COLOR_NEUTRAL, COLOR_WARNING
from investment_agent.reporting.services.investment import CASH_SYMBOL

ENGINE_FOOTER = "factor 기대수익 · TradingAgents 논지 검증 → SPY 대비 위험 optimizer → 결정론적 RiskGate"
# 카드 한 장에 담을 상한. Discord embed field는 1024자 제한이 있다.
_MAX_HOLDINGS = 10
_MAX_LINES = 3
_MAX_VIOLATIONS = 6
_MAX_REASONS = 8
_EMPTY = "없음"
# 불릿 한 줄의 상한. LLM 문장은 길어 카드가 벽글이 된다.
_MAX_LINE_CHARS = 160
# 문장 속 근거 ID 인용: "(EV-FUND-1a2b)", "(EV-A; EV-B)", "(EXT-...)".
_EVIDENCE_REFERENCE = re.compile(r"\s*\((?:(?:EV|EXT)-[A-Za-z0-9_-]+[;,\s]*)+\)")
# 현금이 최소 현금 예산보다 이만큼 넘게 많으면 이유를 적는다. 그보다 작으면 설명할 것이 없다.
_CASH_EXPLAIN_GAP = 0.05

# TradingAgents 논지. 매수·매도 지시가 아니다 — 비중은 optimizer가 정한다.
_THESIS_LABELS = {"positive": "논지 긍정", "neutral": "논지 중립", "negative": "논지 부정"}
_HARD_CONSTRAINT_LABELS = {
    "block_new_buy": "신규 매수 금지",
    "force_exit": "강제 청산",
    "exclude": "편입 제외",
}
# 논지 필드가 없는 옛 기록의 의견 단어.
_LEGACY_SIGNAL_LABELS = {
    "open": "논지 긍정", "increase": "논지 긍정", "hold": "논지 중립", "watch": "논지 중립",
    "reduce": "논지 부정", "exit": "강제 청산", "avoid": "신규 매수 금지",
}
_DIRECTION = {"positive": 1, "open": 1, "increase": 1, "negative": -1, "reduce": -1, "exit": -1}
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
# 현금 사유로 세는 ALPHA 판정(`trading.decision.alpha`의 reason). 늘릴 수 없게 막힌 후보다.
_BLOCKED_REASONS = (
    ("UNVERIFIED_ENTRY_BLOCKED", "논지 검증 전이라 신규 편입을 막은 후보"),
    ("THESIS_VETO", "논지가 부정이라 늘리지 않은 종목"),
    ("THESIS_BROKEN", "논지 붕괴로 청산하는 종목"),
    ("FACTOR_BREAKDOWN", "품질 기준에서 떨어진 종목"),
)


def _percent(value: Any) -> str:
    number = finite_float(value)
    return "—" if number is None else f"{number * 100:.1f}%"


def _signed_percent(value: Any) -> str:
    number = finite_float(value)
    return "—" if number is None else f"{number * 100:+.2f}%"


def _readable(text: str) -> str:
    """카드용 한 줄. 문장 안의 근거 ID 괄호는 뺀다 — ID는 원장에 있고 카드는 인용 개수로 보여준다."""
    cleaned = _EVIDENCE_REFERENCE.sub("", str(text)).strip()
    return cleaned if len(cleaned) <= _MAX_LINE_CHARS else cleaned[:_MAX_LINE_CHARS - 1].rstrip() + "…"


def _lines(values: Sequence[Any], *, limit: int = _MAX_LINES) -> str:
    """목록을 불릿으로 접는다. 비면 빈칸 대신 '없음'이라고 적는다."""
    items = [_readable(value) for value in (values or ()) if str(value).strip()]
    items = [item for item in items if item]
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


def _cash_reasons(metadata: Mapping[str, Any], metrics: Mapping[str, Any]) -> list[str]:
    """현금이 최소 현금 예산보다 많은 이유. 원장(목표 metadata·RiskGate 지표)에 있는 사실만 센다."""
    lines: list[str] = []
    counts = Counter(str(reason) for reason in (metadata.get("alpha_reasons") or {}).values())
    for code, label in _BLOCKED_REASONS:
        if counts.get(code):
            lines.append(f"{label} **{counts[code]}**")
    short = list(metadata.get("short_history_excluded") or ())
    if short:
        lines.append(f"가격 이력이 짧아 제외한 신규 후보 **{len(short)}** ({', '.join(short[:4])})")
    banded = list(metadata.get("no_trade_band_kept") or ())
    if banded:
        lines.append(f"비중 변화가 1% 미만이라 거래를 생략한 종목 **{len(banded)}** ({', '.join(banded[:4])})")
    limits = dict(metrics.get("policy_limits") or {})
    turnover, limit = finite_float(metrics.get("discretionary_turnover")), finite_float(limits.get("max_turnover"))
    if turnover is not None and limit is not None and turnover >= limit - 0.005:
        lines.append(f"재조정당 turnover 한도 {limit:.0%}까지 옮김 — 다음 재조정에서 더 채운다")
    tail = dict(metadata.get("tail_risk") or {})
    scale = finite_float(tail.get("scale"))
    if scale is not None and scale < 0.999:
        lines.append(f"꼬리위험(CVaR·변동성) 한도로 위험자산을 ×{scale:.2f}로 줄임")
    if metadata.get("exposure_limits_relaxed"):
        lines.append("factor 노출 제약을 맞출 수 없어 제약 없이 풀었음(다음 재조정에서 다시 시도)")
    if not lines:
        lines.append("담을 수 있는 후보의 기대수익이 위험 대비 작아 optimizer가 현금을 남김")
    return lines


def portfolio_embed(
    *,
    proposal: Mapping[str, Any],
    risk: Mapping[str, Any],
    run: Mapping[str, Any],
) -> dict[str, Any]:
    """System Portfolio 목표 카드. 첫 줄에 노출·현금·판정, 그다음 현금 이유·비중 변경·보유."""
    is_approved = bool(risk.get("is_approved"))
    violations = list(risk.get("violations") or ())
    weights = dict(proposal.get("weights") or {})
    cash = float(weights.pop(CASH_SYMBOL, 0.0))
    holdings = sorted(
        ((symbol, float(weight)) for symbol, weight in weights.items() if float(weight) > 0.0),
        key=lambda item: item[1],
        reverse=True,
    )
    metadata = dict(proposal.get("metadata") or {})
    metrics = dict(risk.get("metrics") or {})
    regime = (metadata.get("market_regime") or {}).get("risk_state") if isinstance(metadata.get("market_regime"), Mapping) else None
    # 시장 상태로 조인 뒤 게이트가 실제로 건 최소 현금.
    min_cash = finite_float(dict(metrics.get("policy_limits") or {}).get("min_cash_weight"))

    budget = [f"최소 현금 {_percent(min_cash)}"] if min_cash is not None else []
    if regime:
        budget.append(f"시장 {regime}")
    # 시장위험 값이 원장에 없으면 0으로 채우지 않는다 — "베타 0.00"이라는 없는 사실이 카드에 적힌다.
    metric_text = " · ".join(
        f"{label} {finite_float(metrics.get(key)):.2f}"
        for key, label in (("portfolio_volatility", "변동성"), ("portfolio_beta", "베타"), ("turnover", "회전율"))
        if finite_float(metrics.get(key)) is not None
    )
    description = (
        f"주식 **{_percent(1.0 - cash)}** · 현금 **{_percent(cash)}**"
        + (f" ({' · '.join(budget)})" if budget else "")
        + f"\nRiskGate **{'승인' if is_approved else '거절'}**"
        + (f" · {metric_text}" if metric_text and is_approved else "")
    )

    fields: list[dict[str, Any]] = []
    if run.get("failure_reason"):
        fields.append({"name": "⚠️ 실행 실패", "value": str(run["failure_reason"])[:1000], "inline": False})
    if not is_approved:
        fields.append({"name": "⚖️ RiskGate 위반", "value": _lines(violations, limit=_MAX_VIOLATIONS), "inline": False})
    if min_cash is not None and cash > min_cash + _CASH_EXPLAIN_GAP:
        fields.append({
            "name": "💵 현금이 이만큼인 이유",
            "value": "\n".join(f"• {line}" for line in _cash_reasons(metadata, metrics))[:1024],
            "inline": False,
        })
    reason_text = _trade_reason_lines(metadata)
    if reason_text:
        fields.append({"name": "🔁 비중 변경", "value": reason_text[:1024], "inline": False})
    fields.append({
        "name": f"📊 목표 보유 {len(holdings)}종목",
        "value": "\n".join(f"• `{symbol}` {_percent(weight)}" for symbol, weight in holdings[:_MAX_HOLDINGS])
        + (f"\n• …외 {len(holdings) - _MAX_HOLDINGS}종목" if len(holdings) > _MAX_HOLDINGS else "")
        if holdings else _EMPTY,
        "inline": False,
    })

    requested = list(run.get("candidate_tickers") or ())
    scope = (
        f"후보 {len(requested)}종목 · factor {_date(metadata.get('factor_snapshot_as_of'))} · "
        f"실행 {run.get('status', '—')} · 정책 {dict(metadata.get('system_policy') or {}).get('version', '—')}"
    )
    color = COLOR_DANGER if run.get("failure_reason") else (COLOR_NEUTRAL if is_approved else COLOR_WARNING)
    return {
        "title": f"System Portfolio · {_date(proposal.get('as_of_at'))}",
        "description": description,
        "color": color,
        "fields": fields,
        "footer": {"text": f"{scope}\n{ENGINE_FOOTER}"},
    }


def _thesis_label(final: Mapping[str, Any]) -> tuple[str, str | None]:
    thesis = final.get("thesis")
    hard = str(final.get("hard_constraint") or "none")
    if thesis is not None:
        return _THESIS_LABELS.get(str(thesis), str(thesis)), _HARD_CONSTRAINT_LABELS.get(hard)
    signal = str(final.get("signal") or "hold")
    return _LEGACY_SIGNAL_LABELS.get(signal, signal), None


def candidate_embed(*, decision: Mapping[str, Any]) -> dict[str, Any]:
    """종목 하나의 심층 판단 카드. 논지와 핵심 위험이 먼저, 근거와 '없는 근거'가 다음이다."""
    final = dict(decision.get("final_decision") or {})
    label, hard = _thesis_label(final)
    evidence_count = len(list(final.get("evidence_ids") or ()))
    previous = final.get("previous_signal")
    now_direction = _DIRECTION.get(str(final.get("thesis") or final.get("signal")), 0)
    # 직전 판단은 옛 의견 단어로만 기록된다(`previous_signal`).
    before_direction = _DIRECTION.get(str(previous), 0)
    if previous:
        continuity = f"직전 판단 {_LEGACY_SIGNAL_LABELS.get(str(previous), str(previous))}"
        if now_direction and before_direction and now_direction != before_direction:
            continuity += " → **방향 변경**"
    else:
        continuity = "직전 판단 없음"
    title = f"{decision.get('ticker', '—')} · {label}" + (f" · {hard}" if hard else "")
    # LLM의 target_weight·확률·신뢰도는 System이 쓰지 않는다(ALPHA는 방향과 강제 제약만 읽고 기대수익은 소폭
    # 조정에만 쓴다). 반영되는 값처럼 보이지 않게 "LLM 추정"으로 적는다.
    description = (
        f"기준 {_date(decision.get('as_of_at'))} · {continuity}\n"
        f"LLM 추정: 20거래일 SPY 대비 **{_signed_percent(final.get('expected_excess_return'))}** · "
        f"상승확률 {_percent(final.get('probability_up'))}"
    )
    fields = [
        {"name": "⚠️ 핵심 위험", "value": _lines(final.get("key_risks") or ()), "inline": False},
        {"name": "🧭 판단 근거", "value": _lines(final.get("reasoning") or ()), "inline": False},
        {
            "name": f"🔗 인용 근거 {evidence_count}건 · 확보하지 못한 근거",
            "value": _lines(final.get("missing_data") or ()),
            "inline": False,
        },
    ]
    return {
        "title": title,
        "description": description,
        # 강제 제약은 계산된 위험 경고라 status.warning(§5.6). 논지 방향은 색으로 말하지 않는다.
        "color": COLOR_WARNING if hard else COLOR_NEUTRAL,
        "fields": fields,
        "footer": {"text": f"사례 {decision.get('case_key', '—')}\n{ENGINE_FOOTER}"},
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
    arrival = finite_float(order.get("arrival_price"))
    if filled_quantity > 0:
        notional = sum(float(fill.get("quantity") or 0.0) * float(fill.get("price") or 0.0) for fill in fills)
        average = notional / filled_quantity
        fill_text = f"체결 **{filled_quantity:g}주** · 평균 **{average:.2f}**"
        if commission:
            fill_text += f" · 수수료 {commission:.2f}"
        if arrival:
            # 실행 비용: 매수는 도착가보다 비싸게, 매도는 싸게 체결될수록 비용이다(+가 비용).
            cost_bp = (average / arrival - 1.0) * 10_000 * (1 if side == "buy" else -1)
            fill_text += f"\n도착가 {arrival:.2f} 대비 실행 비용 **{cost_bp:+.1f}bp**"
    else:
        fill_text = f"아직 체결 없음 (주문 상태 `{order.get('status', '—')}`)"

    order_text = f"수량 **{float(order.get('quantity') or 0):g}주** · 승인 기준가 {float(order.get('reference_price') or 0):.2f}"
    if arrival:
        order_text += f" · 제출 직전 시세 {arrival:.2f}"
    return {
        "title": f"{order.get('ticker', '—')} · {'매수' if side == 'buy' else '매도'}",
        "description": f"실행 대상 **{execution_mode}**",
        "color": COLOR_NEUTRAL,
        "fields": [
            {"name": "🧾 주문", "value": order_text, "inline": False},
            {"name": "✅ 체결", "value": fill_text, "inline": False},
        ],
        "footer": {
            "text": f"주문 {order.get('client_order_id', '—')} · 승인 {order.get('approval_id', '—')} · "
                    f"의도 {order.get('intent_id', '—')}\n{ENGINE_FOOTER}",
        },
    }


__all__ = ["ENGINE_FOOTER", "candidate_embed", "portfolio_embed", "trade_embed"]
