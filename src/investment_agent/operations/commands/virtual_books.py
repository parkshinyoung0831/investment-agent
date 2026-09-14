"""Shadow·Paper 가상계좌를 운영한다. 실주문·실계좌 원장에는 닿지 않는다.

    python -m investment_agent.operations.commands.virtual_books            # 전 계좌 정산·평가·판단
    python -m investment_agent.operations.commands.virtual_books --summary  # 성과 요약
    python -m investment_agent.operations.commands.virtual_books --create paper-champion --stage paper

계좌가 하나도 없으면 기본 두 개를 만든다: 실계좌와 같은 판단을 따르는 `shadow-champion`,
승격된 RL 정책의 목표비중을 따르는 `shadow-rl-challenger`. 초기 자산은 가상의 기준값이라 성과는
수익률로만 비교한다.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import canonical_json, parse_datetime
from investment_agent.trading.contracts import ContractError
from investment_agent.trading.shadow.engine import run_book
from investment_agent.trading.shadow.store import VirtualBookStore, book_summary

log = get_logger(__name__)

DEFAULT_INITIAL_NAV = 100_000.0
DEFAULT_BOOKS = (
    ("shadow-champion", "shadow", "optimizer"),
    ("shadow-rl-challenger", "shadow", "rl_policy"),
)


def ensure_default_books(store: VirtualBookStore, *, now: datetime) -> None:
    if store.books():
        return
    for book_id, stage, policy_kind in DEFAULT_BOOKS:
        store.create_book(book_id=book_id, stage=stage, policy_kind=policy_kind,
                          initial_nav=DEFAULT_INITIAL_NAV, created_at=now)


def run_all(store: VirtualBookStore, repository, *, now: datetime) -> dict[str, dict]:
    """계좌 하나의 실패가 다른 계좌 운영을 막지 않는다. 실패는 결과에 남긴다."""
    results: dict[str, dict] = {}
    for book in store.books():
        try:
            results[book.book_id] = run_book(store, repository, book.book_id, now=now).to_dict()
        except (ContractError, RuntimeError, ValueError) as exc:
            log.warning("virtual book run failed book=%s: %s", book.book_id, exc)
            results[book.book_id] = {"book_id": book.book_id, "error": f"{type(exc).__name__}: {exc}"}
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.virtual_books")
    parser.add_argument("--as-of")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--create")
    parser.add_argument("--stage", choices=("shadow", "paper"), default="shadow")
    parser.add_argument("--policy", choices=("optimizer", "rl_policy"), default="optimizer")
    parser.add_argument("--initial-nav", type=float, default=DEFAULT_INITIAL_NAV)
    args = parser.parse_args(argv)
    now = parse_datetime(args.as_of) if args.as_of else datetime.now(timezone.utc)
    store = VirtualBookStore()
    if args.create:
        store.create_book(book_id=args.create, stage=args.stage, policy_kind=args.policy,
                          initial_nav=args.initial_nav, created_at=now)
        log.info("virtual book created: %s", args.create)
        return 0
    if args.summary:
        summaries = [book_summary(book, store.nav_history(book.book_id)) for book in store.books()]
        log.info("virtual book summary %s", canonical_json(summaries))
        return 0
    from investment_agent.trading.supabase_repository import SupabaseRepository

    ensure_default_books(store, now=now)
    results = run_all(store, SupabaseRepository(), now=now)
    log.info("virtual books %s", canonical_json(results))
    return 1 if any("error" in result for result in results.values()) else 0


__all__ = ["DEFAULT_BOOKS", "ensure_default_books", "main", "run_all"]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
