"""System Portfolio와 My Portfolio를 한 화면에서 비교하는 read model.

- System: 목표비중·NAV·기간 수익률·SPY 대비·낙폭·변동성·회전율. 원장(`system_nav`) 값만 쓴다.
- My: 최신 계좌 스냅샷 비중과 System 현재 비중의 차이, 따라간 정도, 같은 기간의 실제 수익률 차이.

실제 수익률은 입출금을 뺀 시간가중 수익률(`trading.performance`)이 있을 때만 비교한다. 없으면 차이를
만들지 않는다 — 입출금이 섞인 계좌 가치 변화를 수익률로 부르면 사람의 선택이 성과를 바꿨는지 알 수 없다.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from investment_agent.trading.system.accounting import performance_summary

CASH_SYMBOL = "CASH"


def _position_value(row: Mapping[str, Any]) -> float:
    if row.get("market_value") is not None:
        return float(row["market_value"])
    if row.get("quantity") is not None and row.get("market_price") is not None:
        return float(row["quantity"]) * float(row["market_price"])
    return 0.0


def _account_weights(account: Mapping[str, Any]) -> dict[str, float] | None:
    positions = [row for row in (account.get("holdings") or account.get("positions") or ()) if row.get("ticker")]
    values = {str(row["ticker"]).upper(): _position_value(row) for row in positions}
    cash = float(account.get("cash") or account.get("cash_value") or 0.0)
    total = cash + math.fsum(values.values())
    if total <= 0:
        return None
    weights = {ticker: value / total for ticker, value in values.items() if value > 0}
    weights[CASH_SYMBOL] = cash / total
    return weights


def _follow_ratio(system: Mapping[str, float], mine: Mapping[str, float]) -> float:
    """1 − 회전율 거리. 1이면 System과 같은 비중, 0이면 겹치는 보유가 없다."""
    symbols = set(system) | set(mine)
    return 1.0 - 0.5 * math.fsum(abs(float(system.get(s, 0.0)) - float(mine.get(s, 0.0))) for s in symbols)


def _system_return_since(history: Sequence[Mapping[str, Any]], start_date: str) -> float | None:
    if not history:
        return None
    base = [row for row in history if str(row["trade_date"]) <= start_date[:10]]
    if not base:
        return None
    return float(history[-1]["nav"]) / float(base[-1]["nav"]) - 1.0


def build_system_portfolio_read_model(
    *,
    nav_rows: Sequence[Mapping[str, Any]],
    target_rows: Sequence[Mapping[str, Any]],
    proposals: Sequence[Mapping[str, Any]] = (),
    account: Mapping[str, Any] | None = None,
    performance_reports: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    history = sorted((dict(row) for row in nav_rows), key=lambda row: str(row["trade_date"]))
    targets = sorted((dict(row) for row in target_rows), key=lambda row: str(row["decided_at"]), reverse=True)
    latest_target = targets[0] if targets else None
    proposal = next((dict(row) for row in proposals
                     if latest_target and row.get("proposal_id") == latest_target.get("proposal_id")), None)
    current = dict(history[-1]["weights"]) if history else {CASH_SYMBOL: 1.0}
    system = {
        "summary": performance_summary(history),
        "history": [{"trade_date": row["trade_date"], "nav": row["nav"], "benchmark_nav": row["benchmark_nav"]}
                    for row in history],
        "current_weights": current,
        "latest_target": latest_target,
        "trade_reasons": dict((proposal or {}).get("metadata", {}).get("trade_reasons") or {}),
        "alpha_reasons": dict((proposal or {}).get("metadata", {}).get("alpha_reasons") or {}),
        "market_regime": (proposal or {}).get("metadata", {}).get("market_regime"),
    }
    mine: dict[str, Any] = {"available": False}
    weights = _account_weights(account) if account else None
    if weights is not None:
        symbols = sorted((set(current) | set(weights)) - {CASH_SYMBOL})
        mine = {
            "available": True,
            "captured_at": account.get("captured_at"),
            "weights": weights,
            "follow_ratio": _follow_ratio(current, weights),
            "differences": [
                {"ticker": symbol, "system_weight": float(current.get(symbol, 0.0)),
                 "my_weight": float(weights.get(symbol, 0.0)),
                 "gap": float(weights.get(symbol, 0.0)) - float(current.get(symbol, 0.0))}
                for symbol in symbols
            ] + [{"ticker": CASH_SYMBOL, "system_weight": float(current.get(CASH_SYMBOL, 0.0)),
                  "my_weight": float(weights.get(CASH_SYMBOL, 0.0)),
                  "gap": float(weights.get(CASH_SYMBOL, 0.0)) - float(current.get(CASH_SYMBOL, 0.0))}],
        }
    daily = sorted((row for row in performance_reports if row.get("report_kind") == "daily"),
                   key=lambda row: str(row.get("as_of_at") or ""))
    nav = dict((daily[-1] if daily else {}).get("nav") or {})
    periods = list(nav.get("periods") or ())
    my_return = nav.get("cumulative_return")
    if my_return is not None and periods:
        start = str(periods[0]["start_at"])
        system_return = _system_return_since(history, start)
        mine.update(return_since=start, my_return=my_return, system_return=system_return,
                    return_gap=(float(my_return) - system_return) if system_return is not None else None)
    return {"system": system, "my": mine}


__all__ = ["build_system_portfolio_read_model"]
