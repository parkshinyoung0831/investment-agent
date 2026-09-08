"""Paper intent 생성 및 승인 요청 진입점."""
from __future__ import annotations

import argparse


def validate_paper_scope(
    proposal: dict,
    *,
    approved_weights: dict,
    current_tracked: set[str],
) -> None:
    """부분 분석이나 실제 계좌 기준이 없는 목표 비중을 주문으로 승격하지 않는다."""
    metadata = dict(proposal.get("metadata") or {})
    if metadata.get("coverage") != "full_portfolio":
        raise RuntimeError(
            "paper execution requires a full_portfolio proposal; "
            "a partial TradingAgents batch is research only"
        )
    if not proposal.get("account_snapshot_id"):
        raise RuntimeError(
            "paper execution requires a fresh account_snapshot_id; "
            "cash-only Shadow turnover is not an account snapshot"
        )
    preserved = {
        str(symbol).upper()
        for symbol in metadata.get("preserved_unanalyzed_symbols") or ()
    }
    eligible = {str(symbol).upper() for symbol in current_tracked} | preserved
    outside = sorted(
        str(symbol).upper() for symbol, weight in approved_weights.items()
        if str(symbol).upper() != "CASH"
        and float(weight) > 0.0
        and str(symbol).upper() not in eligible
    )
    if outside:
        raise RuntimeError(
            "approved targets are outside the current tracked universe: " + ", ".join(outside)
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.approve_paper")
    parser.add_argument("--risk-decision-id", required=True)
    parser.add_argument(
        "--confirm", required=True,
        help="사고 방지를 위해 risk-decision-id를 그대로 한 번 더 입력",
    )
    parser.add_argument("--ttl-minutes", type=int, default=30)
    args = parser.parse_args(argv)
    if args.confirm != args.risk_decision_id:
        raise RuntimeError("--confirm must exactly match --risk-decision-id")

    from investment_agent.operations.commands.create_execution_intent import main as create_intent

    return create_intent([
        "--risk-decision-id", args.risk_decision_id,
        "--execution-mode", "paper",
        "--confirm", args.confirm,
        "--ttl-minutes", str(args.ttl_minutes),
    ])


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
