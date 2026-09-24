"""로컬 긴 가격 이력으로 과거 RSI·MACD를 계산해 Research 저장소에 채운다.

daily·backfill은 Supabase 가격(2019-09~)으로 계산해 과거 재현·ML 학습의 technical 열이 비었다.
이 명령은 로컬 사본(`LocalMirror`, 운영 DB 창 앞은 `market_history` archive)의 종가 전체로 종목마다
지표를 계산하고 `--start` 이후 행을 저장한다. 계산 입력은 daily와 같은 `compute_all`이다.

    python -m investment_agent.research.features.long_history --start 2015-01-01
"""
from __future__ import annotations

import argparse
from datetime import date

import pandas as pd

from investment_agent.platform.logging import get_logger

log = get_logger(__name__)


def mirror_closes() -> pd.DataFrame:
    """ticker · trade_date · close. ticker마다 universe와 같은 규칙으로 고른 증권 하나의 이력이다."""
    from investment_agent.data.market.local_mirror.store import LocalMirror

    mirror = LocalMirror()
    tickers = sorted({str(ticker).upper() for ticker in mirror.frame("securities")["ticker"].dropna()})
    chosen = mirror.security_ids(tickers)
    prices = mirror.daily_closes()
    by_id = {security_id: ticker for ticker, security_id in chosen.items()}
    frame = prices[prices["security_id"].isin(by_id)].loc[:, ["security_id", "trade_date", "close"]].copy()
    frame["ticker"] = frame["security_id"].map(by_id)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    frame = frame.dropna(subset=["close"])
    return frame.loc[:, ["ticker", "trade_date", "close"]].sort_values(["ticker", "trade_date"]).reset_index(drop=True)


def build_long_history(*, start: date, prices: pd.DataFrame | None = None,
                       upsert=None) -> int:
    from investment_agent.research.features import db
    from investment_agent.research.features.compute import compute_all

    source = mirror_closes() if prices is None else prices
    write = upsert or db.upsert_indicators
    frames = []
    for _ticker, group in source.groupby("ticker", sort=True):
        rows = compute_all(group)
        rows = rows[pd.to_datetime(rows["trade_date"]).dt.date >= start]
        frames.append(rows.dropna(subset=["rsi14", "macd", "macd_signal"]))
    indicators = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    # 저장소는 연도 분할을 통째로 다시 쓴다 — 종목마다 쓰면 분할을 수백 번 다시 쓴다. 한 번에 넘긴다.
    written = write(indicators) if len(indicators) else 0
    log.info("long history indicators written=%d tickers=%d start=%s", written, source["ticker"].nunique(), start)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.research.features.long_history")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 1),
                        help="저장할 첫 날짜. 그 앞 1년은 EMA warmup으로만 쓴다")
    args = parser.parse_args(argv)
    build_long_history(start=args.start)
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
