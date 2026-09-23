"""Supabase(원본 창고) → 로컬 사본(계산 작업장) 동기화.

```
universe.securities · entities ─┐
universe.index_memberships ──────┼→ 가격 대상 종목(추적 + 과거 S&P 500 멤버 + 참조 ETF)
market.prices_daily · actions ───┘→ data/local/mirror/*.parquet
```

- **증분이 기본이다.** 최근 `lookback_days`의 봉만 다시 받아 덮는다(공급자 정정·늦은 적재를 잡는다). 새로 가격
  대상이 된 종목과, 창 안에 새 분할이 생긴 종목은 전체 이력을 다시 받는다 — 분할은 저장 종가 전체의 기준을 바꾼다.
- **주기적으로 전체를 다시 받는다**(`full_after`). 증분 창 밖의 정정은 그때 덮인다.
- 사본은 Supabase를 바꾸지 않는다. Supabase에 쓰는 것은 GitHub Actions 수집 파이프라인뿐이다.
- 읽기는 각 도메인 owner(`data.universe.persistence`, `data.market.persistence`)를 거친다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from investment_agent.data.market.local_mirror.store import (
    T_ACTIONS,
    T_MEMBERSHIPS,
    T_PRICES,
    T_SECURITIES,
    LocalMirror,
    MirrorManifest,
)
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)

DEFAULT_LOOKBACK_DAYS = 10
DEFAULT_FULL_AFTER = timedelta(days=7)
_EARLIEST_BAR = date(1900, 1, 1)
_SECURITY_COLUMNS = ("security_id", "ticker", "cik", "is_active_listing", "is_identity_verified", "is_tracked",
                     "sic_division")
_PRICE_COLUMNS = ("security_id", "trade_date", "open", "high", "low", "close", "volume", "is_repaired")
_ACTION_COLUMNS = ("security_id", "action_date", "split_ratio", "dividend_amount")


@dataclass(frozen=True)
class MirrorSource:
    """원본 창고 읽기. 기본은 Supabase 도메인 owner이고, 테스트는 가짜를 넣는다."""

    securities: Callable[[], list[dict]]
    memberships: Callable[[], list[dict]]
    profiles: Callable[[Sequence[str]], list[dict]]
    bars: Callable[..., list[dict]]
    actions: Callable[[Sequence[int]], list[dict]]
    reference_tickers: Sequence[str] = field(default_factory=tuple)


def supabase_source() -> MirrorSource:
    from investment_agent.data.market import REFERENCE_PRICE_TICKERS
    from investment_agent.data.market import persistence as market
    from investment_agent.data.universe import persistence as universe

    return MirrorSource(
        securities=universe.select_all_security_rows,
        memberships=universe.select_sp500_membership_rows,
        profiles=lambda tickers: universe.select_security_profiles(list(tickers)),
        bars=market.bars_for_securities,
        actions=market.actions_for_securities,
        reference_tickers=tuple(REFERENCE_PRICE_TICKERS),
    )


@dataclass(frozen=True)
class SyncResult:
    manifest: MirrorManifest
    is_full: bool
    price_securities: int
    refetched_securities: int

    def to_dict(self) -> dict[str, Any]:
        return {"manifest": self.manifest.to_dict(), "is_full": self.is_full,
                "price_securities": self.price_securities, "refetched_securities": self.refetched_securities}


def _preferred_ids(securities: Sequence[Mapping[str, Any]], tickers: Sequence[str]) -> dict[str, int]:
    wanted = {str(ticker).upper() for ticker in tickers}
    best: dict[str, tuple[tuple[bool, bool, int], int]] = {}
    for row in securities:
        ticker = str(row["ticker"]).upper()
        if ticker not in wanted:
            continue
        key = (bool(row["is_active_listing"]), bool(row["is_identity_verified"]), int(row["security_id"]))
        if ticker not in best or key > best[ticker][0]:
            best[ticker] = (key, int(row["security_id"]))
    return {ticker: value[1] for ticker, value in best.items()}


def _frame(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows), columns=list(columns))
    return frame.loc[:, list(columns)]


def sync_local_mirror(
    *,
    mirror: LocalMirror | None = None,
    source: MirrorSource | None = None,
    now: datetime | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    full: bool = False,
    full_after: timedelta = DEFAULT_FULL_AFTER,
) -> SyncResult:
    """원본 창고를 읽어 사본을 갱신한다. 실패하면 사본은 이전 상태 그대로다(manifest를 마지막에 쓴다)."""
    target = mirror or LocalMirror()
    origin = source or supabase_source()
    current = now or datetime.now(timezone.utc)
    previous = target.manifest()
    is_full = bool(full or previous is None or previous.full_synced_at is None
                   or current - previous.full_synced_at >= full_after)

    securities = [dict(row) for row in origin.securities()]
    memberships = [dict(row) for row in origin.memberships()]
    tracked_ids = {int(row["security_id"]) for row in securities if row.get("is_tracked")}
    member_ids = {int(row["security_id"]) for row in memberships}
    # 멤버십 행은 신원 미확인 자리표시 종목(같은 ticker)을 가리킬 수 있다. 가격은 확인된 종목에 쌓이고 ticker
    # 조회도 확인된 종목으로 풀리므로, 멤버의 ticker를 확인된 종목으로도 풀어 그 가격을 복사한다. 빠뜨리면
    # 지수에서 나간 과거 멤버의 가격이 사본에 없어 재현이 그 종목들을 조용히 뺀다(생존 편향).
    member_ticker_ids = set(_preferred_ids(securities, sorted({str(row["ticker"]).upper() for row in memberships
                                                                 if row.get("ticker")})).values())
    reference_ids = set(_preferred_ids(securities, origin.reference_tickers).values())
    price_ids = sorted(tracked_ids | member_ids | member_ticker_ids | reference_ids)
    by_id = {int(row["security_id"]): row for row in securities}
    profile_tickers = sorted({str(by_id[security_id]["ticker"]).upper() for security_id in price_ids if security_id in by_id})
    sectors = {str(row["ticker"]).upper(): row.get("sic_division") for row in origin.profiles(profile_tickers)}
    security_frame = _frame(
        [{**{name: row.get(name) for name in _SECURITY_COLUMNS if name != "sic_division"},
          "sic_division": sectors.get(str(row["ticker"]).upper())} for row in securities],
        _SECURITY_COLUMNS,
    )

    actions = _frame(origin.actions(price_ids), _ACTION_COLUMNS)
    existing: pd.DataFrame | None = None
    if not is_full and (target.root / f"{T_PRICES}.parquet").exists():
        existing = pd.read_parquet(target.root / f"{T_PRICES}.parquet", engine="pyarrow")
    window_start = current.date() - timedelta(days=lookback_days)
    if existing is None:
        refetch = set(price_ids)
    else:
        known = set(int(value) for value in existing["security_id"].unique())
        recent_splits = {int(value) for value in actions.loc[
            actions["split_ratio"].notna() & (actions["action_date"] >= window_start.isoformat()), "security_id"]}
        refetch = (set(price_ids) - known) | (recent_splits & set(price_ids))
    fresh_rows: list[dict] = []
    if refetch:
        fresh_rows += origin.bars(sorted(refetch), start=_EARLIEST_BAR, end=current.date())
    incremental = sorted(set(price_ids) - refetch)
    if incremental:
        fresh_rows += origin.bars(incremental, start=window_start, end=current.date())
    fresh = _frame(fresh_rows, _PRICE_COLUMNS)
    if existing is not None:
        keep = existing[existing["security_id"].isin(incremental) & (existing["trade_date"] < window_start.isoformat())]
        prices = pd.concat([keep, fresh], ignore_index=True)
    else:
        prices = fresh
    prices = (prices.drop_duplicates(["security_id", "trade_date"], keep="last")
              .sort_values(["security_id", "trade_date"]).reset_index(drop=True))
    manifest = target.write({
        T_SECURITIES: security_frame,
        T_MEMBERSHIPS: _frame(memberships, ("security_id", "ticker", "valid_from", "valid_to")),
        T_PRICES: prices,
        T_ACTIONS: actions,
    }, synced_at=current, is_full=is_full)
    log.info("local mirror synced full=%s securities=%d prices=%d refetched=%d through=%s",
             is_full, len(price_ids), len(prices), len(refetch), manifest.price_through)
    return SyncResult(manifest, is_full, len(price_ids), len(refetch))


__all__ = ["MirrorSource", "SyncResult", "supabase_source", "sync_local_mirror"]
