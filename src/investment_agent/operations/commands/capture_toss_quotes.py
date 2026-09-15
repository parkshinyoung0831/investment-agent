"""진입 감시 대상 종목의 토스 현재가를 파일로 남긴다. LLM을 부르지 않는 실행 범위 명령이다.

진입 재검토(`watch_entries`)는 LLM을 부르므로 broker 자격증명을 갖지 않는 판단 범위로 뜬다.
시세가 필요한 순간만 이 명령이 실행 범위에서 조회해 파일로 넘긴다. 파일은 조회 시각을
담고, 소비하는 쪽이 120초 신선도를 다시 검사한다.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

QUOTE_FILE_VERSION = 1
ENTRY_SIGNALS = ("open", "increase", "reduce", "exit")


def entry_symbols(book, now: datetime) -> set[str]:
    """진입 감시가 시세를 봐야 하는 종목. `watch_entries`와 같은 규칙을 공유한다."""
    return {
        record.proposal.ticker for record in book.records
        if record.is_valid_at(now) and record.proposal.signal in ENTRY_SIGNALS
    }


def write_quotes(path: Path, *, prices: dict[str, float], timestamps: dict[str, str | None],
                 captured_at: datetime) -> None:
    payload = {
        "version": QUOTE_FILE_VERSION,
        "captured_at": captured_at.isoformat(),
        "quotes": {ticker: {"price": price, "quoted_at": timestamps.get(ticker)} for ticker, price in prices.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".quotes-", suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
    os.replace(temporary, path)


def read_quotes(path: Path) -> dict[str, tuple[float, str | None]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("version") != QUOTE_FILE_VERSION or not isinstance(payload.get("quotes"), dict):
        raise ValueError("unsupported quote file")
    return {
        str(ticker): (float(row["price"]), row.get("quoted_at"))
        for ticker, row in payload["quotes"].items()
    }


def capture(path: Path, *, symbols: Iterable[str], fetch: Callable, now: datetime) -> int:
    selected = set(symbols)
    prices, timestamps = fetch(selected) if selected else ({}, {})
    write_quotes(path, prices=prices, timestamps=timestamps, captured_at=now)
    return len(prices)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.capture_toss_quotes")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    from investment_agent.execution.brokers.toss.client import fetch_prices
    from investment_agent.trading.supabase_repository import SupabaseRepository

    now = datetime.now(timezone.utc)
    symbols = entry_symbols(SupabaseRepository().load_signal_book(as_of_at=now), now)
    count = capture(Path(args.out), symbols=symbols, fetch=fetch_prices, now=now)
    log.info("entry quotes captured symbols=%d", count)
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
