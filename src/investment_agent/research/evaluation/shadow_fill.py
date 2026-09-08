"""Shadow 판단을 "실제로 체결했다면" 으로 바꿔 비용까지 반영한 결과를 만든다.

`rl_training_labels`의 forward_return은 **비용이 없는 가격 수익률**이다. 그 값으로
학습하면 모델은 회전율이 높을수록 좋다고 배우고, 실제 실행에서 그 초과수익이 전부
수수료와 슬리피지로 사라진다. 학습에 쓰는 label은 반드시 이 모듈을 통과해야 한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from investment_agent.research.evaluation.costs import TransactionCostModel
from investment_agent.platform.serialization import ContractError
from investment_agent.trading.performance.pnl import TradeOutcome, make_trade_outcome

# 비용을 비율로 환산할 때 쓰는 기준 금액. commission_rate와 slippage_bps가 모두
# 비례 항이라 결과 비율은 이 값과 무관하다. minimum_commission을 0보다 크게 두면
# 그때부터 규모에 따라 달라지므로, 그 경우에는 실제 주문 금액을 넘겨야 한다.
DEFAULT_NOTIONAL = 10_000.0


@dataclass(frozen=True)
class ShadowTradeResult:
    """같은 구간의 비용 전·후 수익률을 나란히 보관한다."""

    ticker: str
    entry_at: str
    exit_at: str
    gross_return: float
    net_return: float
    cost_drag: float
    benchmark_return: float
    gross_excess_return: float
    net_excess_return: float
    outcome: TradeOutcome

    def to_labels(self) -> dict[str, float]:
        """TrainingSample이 그대로 받을 수 있는 label 묶음이다."""
        return {
            "gross_return": self.gross_return,
            "net_return": self.net_return,
            "cost_drag": self.cost_drag,
            "benchmark_return": self.benchmark_return,
            "gross_excess_return": self.gross_excess_return,
            "net_excess_return": self.net_excess_return,
        }


def _price(value: Any, name: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ContractError(f"{name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ContractError(f"{name} must be finite and positive")
    return parsed


def simulate_shadow_trade(
    *,
    ticker: str,
    entry_at: str,
    exit_at: str,
    entry_price: float,
    exit_price: float,
    benchmark_return: float,
    cost_model: TransactionCostModel | None = None,
    notional: float = DEFAULT_NOTIONAL,
) -> ShadowTradeResult:
    """구간 시작에 사서 끝에 파는 왕복 거래를 비용과 함께 계산한다.

    long-only 시스템이라 항상 매수 방향으로 본다. 벤치마크는 같은 구간을 그냥 들고
    있었을 때의 수익률(매매 없음)이라 비용을 빼지 않는다 — 회전하는 쪽에만 비용을
    물리므로 비교가 우리에게 불리한 방향으로 보수적이다.
    """
    model = cost_model or TransactionCostModel()
    entry = _price(entry_price, "entry_price")
    exit_ = _price(exit_price, "exit_price")
    size = _price(notional, "notional")
    quantity = size / entry

    buy = model.quote(side="buy", quantity=quantity, reference_price=entry)
    sell = model.quote(side="sell", quantity=quantity, reference_price=exit_)
    fees = buy.fee + sell.fee
    slippage = buy.slippage_cost + sell.slippage_cost

    outcome = make_trade_outcome(
        ticker=ticker,
        side="buy",
        entry_at=entry_at,
        exit_at=exit_at,
        quantity=quantity,
        entry_price=entry,
        exit_price=exit_,
        fees=fees,
        execution_slippage=slippage,
        metadata={
            "source": "shadow_simulation",
            "cost_model": model.to_dict(),
            "notional": size,
        },
    )
    basis = quantity * entry
    gross_return = exit_ / entry - 1.0
    net_return = outcome.net_pnl / basis
    benchmark = float(benchmark_return)
    if not math.isfinite(benchmark):
        raise ContractError("benchmark_return must be finite")
    return ShadowTradeResult(
        ticker=outcome.ticker,
        entry_at=outcome.entry_at,
        exit_at=outcome.exit_at,
        gross_return=gross_return,
        net_return=net_return,
        cost_drag=gross_return - net_return,
        benchmark_return=benchmark,
        gross_excess_return=gross_return - benchmark,
        net_excess_return=net_return - benchmark,
        outcome=outcome,
    )


def round_trip_cost_rate(cost_model: TransactionCostModel | None = None) -> float:
    """왕복 1회에 드는 비용 비율. 회전율 예산을 잡을 때 쓴다."""
    model = cost_model or TransactionCostModel()
    result = simulate_shadow_trade(
        ticker="COST", entry_at="2026-01-02T00:00:00+00:00",
        exit_at="2026-01-09T00:00:00+00:00",
        entry_price=100.0, exit_price=100.0, benchmark_return=0.0,
        cost_model=model,
    )
    return -result.net_return


__all__ = [
    "DEFAULT_NOTIONAL",
    "ShadowTradeResult",
    "round_trip_cost_rate",
    "simulate_shadow_trade",
]
