"""토스 비실행 주문표를 Discord 건별 승인 카드로 바꾼다."""
from __future__ import annotations

from typing import Any

from investment_agent.execution.approval.ledger import ApprovalRequest, ApprovalSigner
from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.planning import FUNDING_PHASE_SELLS
from investment_agent.execution.orders.toss_manual import TossManualHandoff

_BLUE = 0x3182F6


def _ticket_lines(handoff: TossManualHandoff) -> str:
    if not handoff.tickets:
        return "주문 계획 없음"
    lines = [
        f"{ticket.side.upper():4} `{ticket.symbol}` {ticket.order_quantity:g}주 "
        f"@ ${ticket.reference_price:,.2f} ≈ ${ticket.estimated_notional:,.2f}"
        for ticket in handoff.tickets
    ]
    text = "\n".join(lines)
    return text if len(text) <= 1_024 else text[:1_021] + "..."


def button_components(
    request: ApprovalRequest,
    signer: ApprovalSigner,
    *,
    disabled: bool = False,
) -> list[dict[str, Any]]:
    """자유문장 대신 서명된 승인/거절 버튼 두 개만 만든다."""
    return [{
        "type": 1,
        "components": [
            {
                "type": 2,
                "style": 3,
                "label": "이 주문안 승인",
                "emoji": {"name": "✅"},
                "custom_id": signer.custom_id(request, "approve"),
                "disabled": disabled,
            },
            {
                "type": 2,
                "style": 4,
                "label": "거절",
                "custom_id": signer.custom_id(request, "reject"),
                "disabled": disabled,
            },
        ],
    }]


def build_approval_card(
    request: ApprovalRequest,
    handoff: TossManualHandoff,
    signer: ApprovalSigner,
) -> dict[str, Any]:
    """Discord message create API에 바로 전달할 안전한 payload를 만든다."""
    handoff.validate_manifest()
    if request.intent_id != handoff.intent_id:
        raise ExecutionSafetyError("approval intent does not match Toss handoff")
    if request.manifest_hash != handoff.manifest_hash:
        raise ExecutionSafetyError("approval plan hash does not match Toss handoff")
    if request.account_seq != handoff.account_seq:
        raise ExecutionSafetyError("approval account does not match Toss handoff")
    if request.allowed_client_order_ids != tuple(
        ticket.client_order_id for ticket in handoff.tickets
    ):
        raise ExecutionSafetyError("approval client_order_ids do not match Toss handoff")
    sells = sum(ticket.estimated_notional for ticket in handoff.tickets if ticket.side == "sell")
    buys = sum(ticket.estimated_notional for ticket in handoff.tickets if ticket.side == "buy")
    if request.execution_mode == "paper":
        title = "투자 주문안 승인 요청 · Paper 비실행"
        description = (
            "아래 버튼은 이 hash의 승인 상태만 기록합니다. "
            "Paper 승인은 토스 주문 permit으로 바뀌지 않습니다."
        )
    else:
        title = "토스 실주문 승인 요청 · LIVE"
        description = (
            "버튼 자체는 주문을 보내지 않습니다. 승인 뒤 동일 계좌·intent·plan hash를 "
            "원자적으로 1회 소비하고 모든 실시간 위험 조건을 다시 통과해야만 permit이 생깁니다."
        )
    if handoff.funding_phase == FUNDING_PHASE_SELLS:
        description += (
            "\n\n**자금 확보 단계** — 지금 현금으로는 매수를 다 댈 수 없어 매도만 담았습니다. "
            "매수는 이 주문표에 없습니다. 매도가 모두 끝나면 같은 분석 결과로 새 계좌 현금 기준 "
            "포트폴리오를 한 번 더 계산해 별도 승인으로 요청합니다."
        )
    embed = {
        "title": title,
        "description": description,
        "color": _BLUE,
        "fields": [
            {"name": "주문 계획", "value": _ticket_lines(handoff), "inline": False},
            {
                "name": "예상 금액",
                "value": f"매도 ${sells:,.2f} · 매수 ${buys:,.2f}",
                "inline": False,
            },
            {
                "name": "검증 hash",
                "value": (
                    f"proposal `{request.proposal_hash}`\n"
                    f"risk `{request.risk_hash}`\n"
                    f"plan `{request.manifest_hash}`"
                ),
                "inline": False,
            },
            {"name": "승인 만료", "value": request.expires_at, "inline": False},
        ],
        "footer": {
            "text": f"{request.approval_id} · 자유문장/답장/emoji는 승인되지 않습니다"
        },
    }
    return {
        "embeds": [embed],
        "components": button_components(request, signer),
        "allowed_mentions": {"parse": []},
    }
