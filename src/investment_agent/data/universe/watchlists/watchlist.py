"""관심종목을 추가·해제·조회하는 로컬 CLI."""
from __future__ import annotations

import argparse
from datetime import date

from investment_agent.data.universe.watchlists import db
from investment_agent.platform.logging import configure_logging, get_logger

log = get_logger(__name__)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("날짜는 YYYY-MM-DD 형식이어야 합니다") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="investment_agent.data.universe.watchlists.watchlist")
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", help="관심종목에 수동 출처 추가")
    add.add_argument("ticker")
    add.add_argument("--watch-from", type=_date, default=None)
    watch_from = commands.add_parser(
        "watch-from", help="관심종목 적용 시작일을 고쳐 쓴다 (add로는 바뀌지 않는다)")
    watch_from.add_argument("date", type=_date)
    watch_from.add_argument(
        "--ticker", action="append", dest="tickers", default=None,
        help="지정한 종목만. 생략하면 활성 관심종목 전체",
    )

    remove = commands.add_parser("remove", help="관심종목 해제")
    remove.add_argument("ticker")

    listing = commands.add_parser("list", help="관심종목 조회")
    listing.add_argument("--all", action="store_true", help="해제 이력까지 표시")
    listing.add_argument(
        "--source",
        choices=("all", "manual", "toss"),
        default="all",
        help="출처별 필터",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parser().parse_args(argv)
    if args.command == "add":
        cik = db.add_member(
            args.ticker,
            watch_from=args.watch_from,
        )
        log.info("관심 기업 추가 완료 ticker=%s cik=%s", args.ticker.upper(), cik)
        return 0
    if args.command == "watch-from":
        changed = db.set_watch_from(args.date, args.tickers)
        log.info(
            "관심 시작일 변경 date=%s 대상=%s changed=%d",
            args.date, ",".join(args.tickers) if args.tickers else "전체", changed,
        )
        return 0
    if args.command == "remove":
        removed = db.remove_member(args.ticker)
        log.info("관심 기업 해제 ticker=%s removed=%s", args.ticker.upper(), removed)
        return 0

    rows = db.list_members(include_inactive=args.all)
    if args.source != "all":
        rows = [row for row in rows if args.source in (row.get("sources") or [])]
    log.info(
        "관심종목 조회 count=%d include_inactive=%s source=%s",
        len(rows),
        args.all,
        args.source,
    )
    for row in rows:
        log.info(
            "watchlist ticker=%s sources=%s watch_from=%s removed_at=%s",
            row.get("ticker"),
            ",".join(row.get("sources") or []),
            row.get("watch_from"),
            row.get("removed_at"),
        )
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())

