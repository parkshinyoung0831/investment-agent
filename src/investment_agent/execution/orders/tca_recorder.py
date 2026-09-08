"""실시간 체결 비용(TCA) 계측 및 레코더.

체결 이벤트(Decision price vs Fill price)를 바탕으로 슬리피지(bps), 스프레드 비용,
Implementation Shortfall을 계산하여 감사 및 피드백용 TCAReport를 생성한다.
"""
from __future__ import annotations

from investment_agent.execution.orders.tca import TCAReport, build_tca_report


class TCARecorder:
    """체결 결과에 대한 실시간 비용 계측기."""

    @staticmethod
    def record_fill(
        *,
        ticker: str,
        side: str,
        decision_price: float,
        fill_price: float,
        quantity: float,
        arrival_price: float | None = None,
        bid: float | None = None,
        ask: float | None = None,
        fees: float = 0.0,
        intent_id: str | None = None,
        broker_order_id: str | None = None,
        source_kind: str = "live",
    ) -> TCAReport:
        """체결 가격과 결정 가격을 바탕으로 TCAReport를 생성하고 슬리피지 bps를 메타데이터에 기록한다."""
        arr_price = arrival_price if arrival_price is not None and arrival_price > 0 else decision_price

        # 슬리피지 bps 계산:
        # 매수의 경우 체결가가 높으면 양수 슬리피지 (비용 발생)
        # 매도의 경우 체결가가 낮으면 양수 슬리피지 (비용 발생)
        direction = 1.0 if str(side).lower() == "buy" else -1.0
        slippage_ratio = direction * (fill_price - decision_price) / decision_price
        slippage_bps = round(slippage_ratio * 10000.0, 2)

        metadata = {
            "slippage_bps": slippage_bps,
            "cost_quality": "favorable" if slippage_bps <= 0 else ("acceptable" if slippage_bps <= 15 else "high"),
        }

        report = build_tca_report(
            ticker=ticker,
            side=side,
            decision_price=decision_price,
            arrival_price=arr_price,
            fill_price=fill_price,
            quantity=quantity,
            bid=bid,
            ask=ask,
            fees=fees,
            intent_id=intent_id,
            broker_order_id=broker_order_id,
            source_kind=source_kind,
            metadata=metadata,
        )
        return report


__all__ = [
    "TCARecorder",
]
