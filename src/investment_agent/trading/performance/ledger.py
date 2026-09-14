"""체결 FIFO와 현금흐름 구간 수익률. 원가·비용·평가 증거가 없으면 미확인이다."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from investment_agent.platform.serialization import parse_datetime


def number(value, *, positive=False):
    """금액과 수량의 NaN·무한·boolean을 거부한다."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid accounting number") from exc
    if isinstance(value, bool) or not result.is_finite() or (positive and result <= 0):
        raise ValueError("invalid accounting number")
    return result


def unique(rows, key):
    """재수집은 동일 원천 ID로 접고 내용 충돌은 숨기지 않는다."""
    found = {}
    for row in rows:
        identity = str(row.get(key) or "")
        if not identity:
            raise ValueError(f"missing {key}")
        if identity in found and found[identity] != row:
            raise ValueError(f"conflicting {key}")
        found[identity] = dict(row)
    return list(found.values())


def account_fills(fills, *, opening_positions=(), events=(), marks=None, currency="USD"):
    """계좌·통화별로 분리한 증분 체결을 FIFO로 재생한다. 누적 체결량 입력은 금지한다."""
    fills = unique(fills, "fill_id")
    events = unique(events, "event_id")
    lots = defaultdict(list)
    issues = set()
    realizations = []
    dividend = Decimal(0)
    for row in opening_positions:
        quantity = number(row["quantity"], positive=True)
        cost = row.get("cost_basis")
        basis = number(cost) if cost is not None else None
        if basis is not None and basis < 0:
            raise ValueError("negative opening basis")
        lots[str(row["ticker"])].append([quantity, basis / quantity if basis is not None else None,
                                        basis / quantity if basis is not None else None])
    timeline = [(parse_datetime(r["filled_at"]), "fill", r["fill_id"], r) for r in fills]
    timeline += [(parse_datetime(r["occurred_at"]), "event", r["event_id"], r) for r in events]
    for _, kind, _, row in sorted(timeline, key=lambda item: item[:3]):
        if kind == "event":
            if row["kind"] == "split":
                ratio = number(row["ratio"], positive=True)
                for lot in lots[str(row["ticker"])]:
                    lot[0] *= ratio
                    lot[1] = lot[1] / ratio if lot[1] is not None else None
                    lot[2] = lot[2] / ratio if lot[2] is not None else None
            elif row["kind"] == "dividend":
                if row.get("currency") != currency:
                    raise ValueError("dividend currency mismatch")
                dividend += number(row["amount"])
            elif row["kind"] not in ("deposit", "withdrawal", "coverage"):
                raise ValueError("unsupported corporate action")
            continue
        if row.get("currency") != currency:
            raise ValueError("fill currency mismatch or missing")
        ticker = str(row["ticker"])
        quantity, price = number(row["quantity"], positive=True), number(row["price"], positive=True)
        fees_known = row.get("commission") is not None and row.get("tax") is not None
        fees = sum((number(row[name]) for name in ("commission", "tax") if row.get(name) is not None), Decimal(0))
        if fees < 0:
            raise ValueError("negative fees")
        if not fees_known:
            issues.add("fees_unknown")
        side = str(row["side"]).lower()
        if side == "buy":
            lots[ticker].append([quantity, price, price + fees / quantity if fees_known else None])
        elif side == "sell":
            remaining, gross_cost, net_cost, unknown = quantity, Decimal(0), Decimal(0), Decimal(0)
            is_net_known = fees_known
            while remaining and lots[ticker]:
                lot = lots[ticker][0]
                matched = min(remaining, lot[0])
                if lot[1] is None:
                    unknown += matched
                else:
                    gross_cost += matched * lot[1]
                if lot[2] is None:
                    is_net_known = False
                else:
                    net_cost += matched * lot[2]
                remaining -= matched
                lot[0] -= matched
                if not lot[0]:
                    lots[ticker].pop(0)
            unknown += remaining
            if unknown:
                issues.add("opening_cost_basis_unknown")
            realizations.append(dict(fill_id=row["fill_id"], ticker=ticker, filled_at=row["filled_at"],
                quantity=float(quantity), unknown_quantity=float(unknown), proceeds=float(quantity * price),
                gross_pnl=float(quantity * price - gross_cost) if not unknown else None,
                net_pnl=float(quantity * price - net_cost - fees) if not unknown and is_net_known else None))
        else:
            raise ValueError("unsupported fill side")
    positions = []
    for ticker, inventory in sorted(lots.items()):
        if not inventory:
            continue
        quantity = sum((lot[0] for lot in inventory), Decimal(0))
        is_basis_known = all(lot[2] is not None for lot in inventory)
        cost = sum((lot[0] * lot[2] for lot in inventory), Decimal(0)) if is_basis_known else None
        mark = (marks or {}).get(ticker)
        value = quantity * number(mark, positive=True) if mark is not None else None
        if cost is None:
            issues.add("position_cost_basis_unknown")
        if value is None:
            issues.add("position_mark_unknown")
        positions.append(dict(ticker=ticker, quantity=float(quantity), cost_basis=float(cost) if cost is not None else None,
                              market_value=float(value) if value is not None else None,
                              unrealized_pnl=float(value - cost) if value is not None and cost is not None else None))
    realized = [row["net_pnl"] for row in realizations]
    unrealized = [row["unrealized_pnl"] for row in positions]
    return dict(currency=currency, fill_count=len(fills), positions=positions, realizations=realizations,
        realized_pnl=sum(realized) if realized and all(v is not None for v in realized) else None,
        unrealized_pnl=sum(unrealized) if unrealized and all(v is not None for v in unrealized) else None,
        dividend_income=float(dividend) if any(e["kind"] == "dividend" for e in events) else None,
        quality_issues=sorted(issues))


def nav_returns(snapshots, cashflows, *, is_cashflow_history_complete=False, currency="USD"):
    """입출금 직전·직후 평가점이 있어야 정확한 시간가중 수익률을 계산한다."""
    snapshots = sorted(snapshots, key=lambda row: parse_datetime(row["captured_at"]))
    flows = unique(cashflows, "event_id")
    periods = []
    issues = set()
    if not is_cashflow_history_complete:
        issues.add("cashflow_history_incomplete")
    if len(snapshots) < 2:
        issues.add("insufficient_nav_history")
    for left, right in zip(snapshots, snapshots[1:]):
        start, end = parse_datetime(left["captured_at"]), parse_datetime(right["captured_at"])
        value = None
        if end <= start:
            raise ValueError("duplicate NAV timestamp")
        if left.get("currency") != currency or right.get("currency") != currency:
            issues.add("nav_currency_unknown_or_mixed")
        elif is_cashflow_history_complete:
            capital = number(left["equity"], positive=True)
            growth = Decimal(1)
            is_valid = True
            endpoint_amount = Decimal(0)
            for flow in sorted(flows, key=lambda row: parse_datetime(row["occurred_at"])):
                moment = parse_datetime(flow["occurred_at"])
                if not start < moment <= end or flow["kind"] not in ("deposit", "withdrawal"):
                    continue
                if flow.get("currency") != currency:
                    issues.add("cashflow_currency_unknown_or_mixed")
                    is_valid = False
                    break
                amount = number(flow["amount"], positive=True) * (1 if flow["kind"] == "deposit" else -1)
                before = flow.get("nav_before")
                after = flow.get("nav_after")
                if moment == end and before is None:
                    endpoint_amount += amount
                    continue
                if before is None or after is None:
                    issues.add("cashflow_valuation_missing")
                    is_valid = False
                    break
                before, after = number(before, positive=True), number(after, positive=True)
                if abs(after - before - amount) > Decimal("0.000001"):
                    raise ValueError("cashflow NAV does not reconcile")
                growth *= before / capital
                capital = after
            if is_valid:
                value = float(growth * number(number(right["equity"]) - endpoint_amount, positive=True) / capital - 1)
        periods.append(dict(start_at=left["captured_at"], end_at=right["captured_at"], twr=value))
    cumulative = Decimal(1)
    is_complete = bool(periods) and all(row["twr"] is not None for row in periods)
    if is_complete:
        for row in periods:
            cumulative *= 1 + number(row["twr"])
    return dict(currency=currency, periods=periods, daily_return=periods[-1]["twr"] if periods else None,
                cumulative_return=float(cumulative - 1) if is_complete else None, quality_issues=sorted(issues),
                return_method="time_weighted_subperiods")
