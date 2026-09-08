"""하나의 개인 관심 기업 목록을 관리하는 universe 저장소.

밖에서 들어오는 이름은 ticker지만 저장 키는 발행사 CIK다 — 관심은 종목이 아니라
회사에 대한 것이고, ticker는 바뀌지만 CIK는 바뀌지 않는다.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from investment_agent.data.universe.domain.identifiers import normalize_ticker as _normalize_ticker
from investment_agent.data.universe.repository import UniverseRepository
from investment_agent.platform.db.postgres import Database, sb

WATCHLIST_NAME = "fundamentals"

_database: Database | None = None


def configure(db: Database | None) -> None:
    global _database
    _database = db


def _db() -> Database:
    return _database or Database(sb)


def normalize_ticker(ticker: str) -> str:
    normalized = _normalize_ticker(ticker)
    if normalized is None:
        raise ValueError("ticker는 비어 있거나 universe 표기가 아닙니다")
    return normalized


normalize_watchlist_ticker = normalize_ticker


def _member_rows(*, include_inactive: bool) -> list[dict[str, Any]]:
    rows = UniverseRepository(_db()).watchlist_member_rows(include_inactive=include_inactive)
    return sorted(rows, key=lambda row: row["ticker"])


def _cik(ticker: str) -> str:
    """ticker를 발행사 CIK로 바꾼다. tracked가 아니거나 발행사를 모르면 거절한다."""
    normalized = normalize_ticker(ticker)
    found = UniverseRepository(_db()).securities_by_ticker([normalized]).get(normalized)
    if found is None or not found.is_tracked:
        raise ValueError(f"ticker is not a tracked universe security: {normalized}")
    if not found.cik:
        raise ValueError(f"security has no issuer CIK: {normalized}")
    return str(found.cik)


def _member_row(cik: str) -> dict[str, Any] | None:
    return UniverseRepository(_db()).watchlist_member_row(cik)


def _upsert_member(*, cik: str, sources: list[str], watch_from: str, removed_at: str | None) -> None:
    UniverseRepository(_db()).upsert_watchlist_member(
        cik=cik, sources=sources, watch_from=watch_from, removed_at=removed_at,
    )


def active_members(purpose: str = WATCHLIST_NAME) -> list[dict[str, Any]]:
    if purpose != WATCHLIST_NAME:
        raise ValueError(f"지원하지 않는 관심종목 용도: {purpose}")
    return _member_rows(include_inactive=False)


def add_member(ticker: str, *, watch_from: date | None = None) -> str:
    cik = _cik(ticker)
    current = _member_row(cik)
    sources = set(current.get("sources") or ()) if current else set()
    sources.add("manual")
    _upsert_member(
        cik=cik, sources=sorted(sources), removed_at=None,
        watch_from=watch_from.isoformat() if watch_from else str((current or {}).get("watch_from") or date.today().isoformat()),
    )
    return cik


def remove_member(ticker: str) -> bool:
    cik = _cik(ticker)
    current = _member_row(cik)
    if current is None:
        return False
    sources = [source for source in current.get("sources") or [] if source != "manual"]
    _upsert_member(cik=cik, sources=sources, watch_from=str(current.get("watch_from") or date.today().isoformat()), removed_at=None if sources else datetime.now(timezone.utc).isoformat())
    return True


def set_watch_from(watch_from: date, tickers: list[str] | None = None) -> int:
    wanted = {normalize_ticker(ticker) for ticker in tickers} if tickers is not None else None
    changed = 0
    for row in _member_rows(include_inactive=True):
        if wanted is None or row["ticker"] in wanted:
            _upsert_member(cik=row["cik"], sources=row["sources"], watch_from=watch_from.isoformat(), removed_at=row.get("removed_at"))
            changed += 1
    return changed


def list_members(*, include_inactive: bool = False) -> list[dict[str, Any]]:
    return _member_rows(include_inactive=include_inactive)


def sync_toss_members(tickers: list[str]) -> dict[str, Any]:
    requested = sorted({normalize_ticker(ticker) for ticker in tickers})
    found = UniverseRepository(_db()).securities_by_ticker(requested) if requested else {}
    # 보유는 종목 단위로 오지만 관심은 회사 단위다. 같은 회사의 두 클래스를 들고
    # 있어도 관심 기업은 하나다.
    tracked = {
        ticker: str(security.cik)
        for ticker, security in found.items()
        if security.is_tracked and security.cik
    }
    target_ciks = set(tracked.values())
    added = removed = unchanged = 0
    members = _member_rows(include_inactive=True)
    present_ciks = {row["cik"] for row in members}
    for row in members:
        sources = set(row["sources"])
        had = "toss" in sources
        if row["cik"] in target_ciks:
            sources.add("toss")
            added += int(not had)
            unchanged += int(had)
        else:
            sources.discard("toss")
            removed += int(had)
            unchanged += int(not had)
        _upsert_member(cik=row["cik"], sources=sorted(sources), watch_from=str(row.get("watch_from") or date.today().isoformat()), removed_at=None if sources else datetime.now(timezone.utc).isoformat())
    for cik in sorted(target_ciks - present_ciks):
        _upsert_member(cik=cik, sources=["toss"], watch_from=date.today().isoformat(), removed_at=None)
        added += 1
    return {"source": "toss", "requested": len(requested), "active": len(target_ciks), "added": added, "removed": removed, "unchanged": unchanged, "skipped_tickers": sorted(set(requested) - set(tracked))}


__all__ = ["WATCHLIST_NAME", "active_members", "add_member", "list_members", "normalize_ticker", "normalize_watchlist_ticker", "remove_member", "set_watch_from", "sync_toss_members"]
