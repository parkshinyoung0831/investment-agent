"""대시보드 실제 보유와 목표 비중 간 리밸런싱 가이드 계산."""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from investment_agent.dashboard.calculations._common import (
    _records,
    finite_number,
)
from investment_agent.dashboard.calculations.strategy import _valid_weights

def _price_mapping(prices: Any) -> dict[str, float]:
    """실시간 가격 응답에서 양수인 종목 가격만 추출한다."""
    if not isinstance(prices, Mapping):
        return {}
    output: dict[str, float] = {}
    for symbol, raw_value in prices.items():
        value = raw_value
        if isinstance(raw_value, Mapping):
            value = next((raw_value.get(key) for key in ("price", "current_price", "close") if key in raw_value), None)
        parsed = finite_number(value)
        if parsed is not None and parsed > 0.0:
            output[str(symbol).upper().strip()] = parsed
    return output


def _holding_rows(holdings: Any) -> list[dict[str, Any]] | None:
    """보유 응답을 종목·수량·평가액 행으로 정규화하며 불완전 행은 거부한다."""
    if isinstance(holdings, Mapping):
        rows = [{"ticker": symbol, "quantity": quantity} for symbol, quantity in holdings.items()]
    else:
        rows = _records(holdings)
    if holdings is None or rows is None:
        return None
    output: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        quantity = finite_number(row.get("quantity", row.get("qty")))
        market_value = finite_number(row.get("market_value", row.get("evaluation_amount")))
        if not symbol or (quantity is None and market_value is None):
            return None
        if quantity is not None and quantity < 0.0:
            return None
        if market_value is not None and market_value < 0.0:
            return None
        output.append({"ticker": symbol, "quantity": quantity, "market_value": market_value})
    return output


def rebalance_portfolio(
    holdings: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    cash: Any,
    target_weights: Mapping[str, Any],
    prices: Mapping[str, Any],
) -> dict[str, Any]:
    """실제 보유와 승인 목표 비중의 읽기 전용 리밸런싱 가이드를 계산한다.

    반환값에는 ``available``, ``complete``, ``total_value``, ``cash_weight``,
    ``concentration``, ``missing_prices``와 ``rows``가 있다. 행은 현재/목표 비중,
    조정 금액, 소수 단위 ``guide_quantity_delta``만 제공하며 주문 방향·주문 유형·
    주문 식별자는 만들지 않는다. 필수 계좌 가치가 없으면 수치를 0으로 만들지 않는다.
    """
    cash_value = finite_number(cash)
    normalized_holdings = _holding_rows(holdings)
    normalized_targets = _valid_weights(target_weights)
    price_by_symbol = _price_mapping(prices)
    unavailable = {
        "available": False,
        "complete": False,
        "total_value": None,
        "cash_value": cash_value,
        "cash_weight": None,
        "concentration": None,
        "missing_prices": (),
        "rows": [],
    }
    if (
        cash_value is None
        or cash_value < 0.0
        or normalized_holdings is None
        or normalized_targets is None
        or "CASH" not in {str(symbol).upper() for symbol in target_weights}
    ):
        return unavailable

    holdings_by_symbol: dict[str, dict[str, float | None]] = {}
    missing_for_value: set[str] = set()
    for row in normalized_holdings:
        symbol = row["ticker"]
        quantity = row["quantity"]
        market_value = row["market_value"]
        price = price_by_symbol.get(symbol)
        if market_value is None:
            if quantity == 0.0:
                market_value = 0.0
            elif quantity is not None and price is not None:
                market_value = quantity * price
            else:
                missing_for_value.add(symbol)
        current = holdings_by_symbol.setdefault(symbol, {"quantity": 0.0, "market_value": 0.0})
        if quantity is None:
            current["quantity"] = None
        elif current["quantity"] is not None:
            current["quantity"] = float(current["quantity"]) + quantity
        if market_value is None:
            current["market_value"] = None
        elif current["market_value"] is not None:
            current["market_value"] = float(current["market_value"]) + market_value
    if missing_for_value or any(value["market_value"] is None for value in holdings_by_symbol.values()):
        unavailable["missing_prices"] = tuple(sorted(missing_for_value))
        return unavailable

    securities_value = math.fsum(float(value["market_value"]) for value in holdings_by_symbol.values())
    total_value = cash_value + securities_value
    if not math.isfinite(total_value) or total_value <= 0.0:
        return unavailable
    symbols = sorted((set(holdings_by_symbol) | set(normalized_targets)) - {"CASH"})
    missing_prices: set[str] = set()
    rows: list[dict[str, Any]] = []
    security_weights: list[float] = []
    for symbol in symbols:
        current = holdings_by_symbol.get(symbol, {"quantity": 0.0, "market_value": 0.0})
        quantity = current["quantity"]
        current_value = float(current["market_value"])
        actual_weight = current_value / total_value
        target_weight = normalized_targets.get(symbol, 0.0)
        target_value = target_weight * total_value
        adjustment_value = target_value - current_value
        price = price_by_symbol.get(symbol)
        held_quantity = finite_number(quantity)
        # 가격이 필요한 종목(목표가 있거나 실제로 들고 있는 종목)만 결측으로 신고한다.
        if price is None and (target_weight > 0.0 or (held_quantity is not None and held_quantity > 0.0)):
            missing_prices.add(symbol)
        guide_quantity = adjustment_value / price if price is not None and quantity is not None else None
        rows.append({
            "ticker": symbol,
            "quantity": quantity,
            "current_quantity": quantity,
            "price": price,
            "current_price": price,
            "current_value": current_value,
            "actual_weight": actual_weight,
            "target_weight": target_weight,
            "weight_difference": target_weight - actual_weight,
            "difference": target_weight - actual_weight,
            "weight_gap": target_weight - actual_weight,
            "target_value": target_value,
            "adjustment_amount": adjustment_value,
            "adjustment_value": adjustment_value,
            "guide_quantity": guide_quantity,
            "quantity_delta": guide_quantity,
            "guide_quantity_delta": guide_quantity,
            "status": "complete" if guide_quantity is not None else "price_or_quantity_missing",
            "data_status": "complete" if guide_quantity is not None else "price_or_quantity_missing",
        })
        security_weights.append(actual_weight)
    cash_weight = cash_value / total_value
    rows.append({
        "ticker": "CASH",
        "quantity": None,
        "current_quantity": None,
        "price": None,
        "current_price": None,
        "current_value": cash_value,
        "actual_weight": cash_weight,
        "target_weight": normalized_targets["CASH"],
        "weight_difference": normalized_targets["CASH"] - cash_weight,
        "difference": normalized_targets["CASH"] - cash_weight,
        "weight_gap": normalized_targets["CASH"] - cash_weight,
        "target_value": normalized_targets["CASH"] * total_value,
        "adjustment_amount": normalized_targets["CASH"] * total_value - cash_value,
        "adjustment_value": normalized_targets["CASH"] * total_value - cash_value,
        "guide_quantity": None,
        "quantity_delta": None,
        "guide_quantity_delta": None,
        "status": "not_applicable",
        "data_status": "not_applicable",
    })
    return {
        "available": True,
        "complete": not missing_prices,
        "total_value": total_value,
        "cash_value": cash_value,
        "cash_weight": cash_weight,
        "concentration": max(security_weights, default=0.0),
        "missing_prices": tuple(sorted(missing_prices)),
        "rows": rows,
    }
