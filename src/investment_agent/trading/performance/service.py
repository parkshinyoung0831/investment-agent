"""실행 owner의 관측 원장을 계좌별 성과 보고서로 생산한다."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone

from investment_agent.platform.serialization import parse_datetime
from investment_agent.trading.performance.ledger import account_fills, nav_returns, number
from investment_agent.trading.performance.repository import PerformanceRepository, report_identity


def observed_fills(data, *, as_of_at=None):
    """개별 체결을 보존하고 누적 관측으로 누락 수량·최종 비용을 보완한다."""
    actual = [dict(row) for row in data.get("fills", ())
              if as_of_at is None or parse_datetime(row['filled_at']) <= as_of_at]
    actual_orders = defaultdict(list)
    for row in actual:
        actual_orders[str(row.get('client_order_id'))].append(row)
    grouped = defaultdict(list)
    for row in data.get("broker_order_snapshots", ()):
        if as_of_at is not None and parse_datetime(row["observed_at"]) > as_of_at:
            continue
        grouped[str(row["client_order_id"])].append(row)
    result = list(actual)
    for order_id, snapshots in sorted(grouped.items()):
        snapshots.sort(key=lambda row: (parse_datetime(row["observed_at"]), row["snapshot_hash"]))
        if order_id in actual_orders:
            # 실제 체결 시각·가격을 우선하며 브로커 누적량에 부족한 부분만 보완한다.
            lots = actual_orders[order_id]
            known_quantity = sum((number(row['quantity'], positive=True) for row in lots), number(0))
            final = snapshots[-1]
            total_quantity = number(final['filled_quantity'])
            if total_quantity < known_quantity:
                continue  # 개별 체결보다 오래된 관측으로 이미 확인한 체결을 줄이지 않는다.
            if total_quantity > known_quantity:
                notional = total_quantity * number(final['average_fill_price'], positive=True)
                known_notional = sum((number(row['quantity']) * number(row['price']) for row in lots), number(0))
                delta = total_quantity - known_quantity
                missing = dict(fill_id=f'observed-remainder:{order_id}:{total_quantity}', client_order_id=order_id,
                    quantity=float(delta), price=float(number((notional-known_notional)/delta, positive=True)),
                    filled_at=final['observed_at'], time_basis='broker_observed_at', source_snapshot_hash=final['snapshot_hash'])
                lots.append(missing)
                result.append(missing)
            for lot in lots:
                for field in ('commission', 'tax'):
                    if final.get(field) is not None:
                        lot[field] = float(number(final[field]) * number(lot['quantity']) / total_quantity)
                lot['fee_allocation'] = 'final_order_cost_pro_rata_quantity'
            continue
        previous_quantity = number(0)
        previous_notional = number(0)
        lots = []
        for row in snapshots:
            quantity = number(row["filled_quantity"])
            if quantity < previous_quantity:
                raise ValueError("cumulative broker quantity decreased")
            if not quantity:
                continue
            notional = quantity * number(row["average_fill_price"], positive=True)
            if quantity == previous_quantity:
                if notional != previous_notional:
                    raise ValueError("broker fill price correction requires explicit restatement")
                continue
            delta = quantity - previous_quantity
            price = number((notional - previous_notional) / delta, positive=True)
            lots.append(dict(fill_id=f"observed:{order_id}:{quantity}", client_order_id=order_id,
                quantity=float(delta), price=float(price), filled_at=row["observed_at"],
                time_basis="broker_observed_at", source_snapshot_hash=row["snapshot_hash"]))
            previous_quantity, previous_notional = quantity, notional
        if not lots:
            continue
        # 최종 누적 비용을 관측 수량 비례로 배분해 수량 없는 비용 정정도 다음 revision에 반영한다.
        final = snapshots[-1]
        for lot in lots:
            for field in ("commission", "tax"):
                lot[field] = float(number(final[field]) * number(lot["quantity"]) / previous_quantity) if final.get(field) is not None else None
            lot["fee_allocation"] = "final_order_cost_pro_rata_quantity"
        result.extend(lots)
    return result


def update_performance(*, source, repository=None, as_of_at=None, recommendation_rows=()):
    """외부 조회·주문 없이 원천 reader를 소비하고 재시도 가능한 보고서를 저장한다."""
    repository = repository or PerformanceRepository()
    now = parse_datetime(as_of_at or datetime.now(timezone.utc))
    data = source.performance_sources()
    orders = {str(row["client_order_id"]): row for row in data.get("orders", ())}
    intents = {str(row["intent_id"]): row for row in data.get("intents", ())}
    groups = defaultdict(lambda: {"fills": [], "snapshots": [], "events": []})
    unattributed = 0
    for raw in observed_fills(data, as_of_at=now):
        row = dict(raw)
        order = orders.get(str(row.get("client_order_id")), {})
        intent = intents.get(str(order.get("intent_id")), {})
        account = row.get("broker_account_hash") or order.get("broker_account_hash")
        if not account and order.get("account_seq"):
            account = hashlib.sha256(f"toss|{order['account_seq']}".encode()).hexdigest()
        execution_mode = row.get("execution_mode") or intent.get("execution_mode")
        if not account or execution_mode not in ("paper", "live"):
            unattributed += 1
            continue
        if parse_datetime(row["filled_at"]) > now:
            continue
        row["fill_id"] = row.get("fill_id") or row.get("broker_fill_id")
        for key in ("ticker", "side", "currency"):
            row[key] = row.get(key) or order.get(key)
        groups[(account, execution_mode)]["fills"].append(row)
    for row in data.get("account_snapshots", ()):
        if parse_datetime(row["captured_at"]) <= now:
            groups[(row["broker_account_hash"], row["execution_mode"])]["snapshots"].append(row)
    for row in repository.events():
        if parse_datetime(row["occurred_at"]) <= now:
            groups[(row["broker_account_hash"], row["execution_mode"])]["events"].append(row)
    created = 0
    for (account, execution_mode), group in sorted(groups.items()):
        snapshots = sorted(group["snapshots"], key=lambda row: parse_datetime(row["captured_at"]))
        # 같은 시각 상세점은 owner가 합치며 여기서는 충돌을 숨기지 않는다.
        by_time = {}
        for row in snapshots:
            stamp = parse_datetime(row["captured_at"]).isoformat()
            if stamp in by_time and by_time[stamp] != row:
                raise ValueError("conflicting account snapshot")
            by_time[stamp] = row
        snapshots = list(by_time.values())
        latest = snapshots[-1] if snapshots else {}
        moment = max([row["filled_at"] for row in group["fills"]] + [row["captured_at"] for row in snapshots] +
                     [row["occurred_at"] for row in group["events"]], key=parse_datetime)
        currency = latest.get("currency") or latest.get("base_currency") or "USD"
        events = group["events"]
        opening = [event for event in events if event["kind"] == "opening"]
        if len(opening) > 1:
            raise ValueError("multiple opening inventory baselines")
        inventory = opening[0].get("positions", []) if opening else []
        fills = group["fills"]
        if opening:
            fills = [row for row in fills if parse_datetime(row["filled_at"]) > parse_datetime(opening[0]["occurred_at"])]
        invalid_fills = [row for row in fills if not row.get("ticker") or not row.get("side") or row.get("currency") != currency]
        fills = [row for row in fills if row not in invalid_fills]
        marks = {row["ticker"]: row["market_price"] for row in latest.get("positions", ()) if row.get("ticker") and row.get("market_price")}
        accounting = account_fills(fills, opening_positions=inventory,
            events=[row for row in events if row["kind"] not in ("opening", "coverage")], marks=marks, currency=currency)
        quality = set(accounting["quality_issues"])
        if invalid_fills:
            quality.add("fill_identity_or_currency_unknown")
            accounting["realized_pnl"] = None
            accounting["unrealized_pnl"] = None
            for realization in accounting["realizations"]:
                realization["net_pnl"] = None
                realization["gross_pnl"] = None
        if not opening:
            quality.add("opening_inventory_unverified")
        if any(row.get("time_basis") == "broker_observed_at" for row in fills):
            quality.add("observed_fill_time_and_allocated_order_fees")
        elif any(row.get('fee_allocation') for row in fills):
            quality.add('allocated_order_fees')
        if unattributed:
            quality.add("unattributed_fills")
        expected = {row["ticker"]: float(row["quantity"]) for row in latest.get("positions", ()) if row.get("ticker")}
        actual = {row["ticker"]: row["quantity"] for row in accounting["positions"]}
        if "positions" not in latest:
            quality.add("position_reconciliation_unavailable")
        elif expected != actual:
            quality.add("position_quantity_mismatch")
            accounting["unrealized_pnl"] = None
        coverage = any(row["kind"] == "coverage" and row.get("cashflows_complete") is True and snapshots and
                       parse_datetime(row["start_at"]) <= parse_datetime(snapshots[0]["captured_at"]) and
                       parse_datetime(row["end_at"]) >= parse_datetime(snapshots[-1]["captured_at"]) for row in events)
        nav = nav_returns(snapshots, [row for row in events if row["kind"] in ("deposit", "withdrawal")],
                          is_cashflow_history_complete=coverage, currency=currency)
        quality.update(nav["quality_issues"])
        comparison = summarize_recommendations(recommendation_rows, parse_datetime(moment))
        base = dict(broker_account_hash=account, execution_mode=execution_mode, as_of_at=moment,
            currency=currency, accounting=accounting, nav=nav, quality_issues=sorted(quality),
            equity=latest.get("equity"), recommendation=comparison,
            benchmark=dict(value=None, reason="matched_account_benchmark_unavailable"))
        daily = dict(base, report_kind="daily", occurrence=parse_datetime(moment).date().isoformat())
        daily["report_id"] = report_identity(daily)
        created += repository.save_report(daily)
        for realization in accounting["realizations"]:
            report = dict(base, report_kind="realized", occurrence=realization["fill_id"],
                          as_of_at=realization["filled_at"], realization=realization)
            # 청산 보고서는 이후 시세/NAV 변화에 따라 과거 청산 알림을 다시 만들지 않는다.
            report.pop("accounting")
            report.pop("nav")
            report.pop("equity")
            report.pop("recommendation")
            report["quality_issues"] = sorted(issue for issue in quality if issue in (
                "opening_inventory_unverified", "observed_fill_time_and_allocated_order_fees", "allocated_order_fees", "unattributed_fills"))
            if realization["net_pnl"] is None:
                report["quality_issues"].append("realized_cost_or_fees_unknown")
            report["report_id"] = report_identity(report)
            created += repository.save_report(report)
    return dict(created=created, accounts=len(groups), unattributed_fills=unattributed)


def summarize_recommendations(rows, as_of):
    groups = defaultdict(list)
    for row in rows:
        if row.get("available_at") and parse_datetime(row["available_at"]) <= as_of and row.get("net_reward") is not None:
            groups[int(row["horizon_days"])].append(float(row["net_reward"]))
    return dict(kind="hypothetical_decision_outcomes", is_account_return=False,
                horizons=[dict(horizon_days=horizon, count=len(values), mean_net_reward=sum(values) / len(values))
                          for horizon, values in sorted(groups.items())])
