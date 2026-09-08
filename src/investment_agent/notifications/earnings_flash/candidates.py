"""8-K 실적 속보 알림 대상 후보 선정."""
from __future__ import annotations

import os
from datetime import date, timedelta

from investment_agent.reporting.notifications.earnings_flash import EarningsFlashStore
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)
_DEFAULT_LOOKBACK_DAYS = 7


def _lookback_days() -> int:
    try:
        return int(os.environ.get("FLASH_NOTIFY_LOOKBACK_DAYS", _DEFAULT_LOOKBACK_DAYS))
    except ValueError:
        return _DEFAULT_LOOKBACK_DAYS


def _cutoff() -> str:
    return (date.today() - timedelta(days=_lookback_days())).isoformat()


def load_pending_flash(
    store: EarningsFlashStore,
    tickers: set[str] | None = None,
) -> list[dict]:
    """관심종목의 미발송 8-K 실적 속보 목록."""
    members = store.watchlist_members()
    if tickers is not None:
        members = [member for member in members if str(member.get("ticker") or "") in tickers]
    selected_tickers = [str(member["ticker"]) for member in members]
    if not selected_tickers:
        log.info("flash: 활성 관심종목 없음 — 조회 생략")
        return []

    forced = os.environ.get("NOTIFY_FLASH_FORCE", "").lower() in ("true", "1")
    processed = set() if forced else store.processed_flash_keys()
    global_cutoff = _cutoff()
    member_cutoffs = {
        str(member["ticker"]): max(global_cutoff, str(member.get("watch_from") or global_cutoff))
        for member in members
    }
    names = store.load_names(selected_tickers)

    out: list[dict] = []
    for row in store.load_flash_rows(selected_tickers, global_cutoff):
        ticker = str(row.get("ticker") or "")
        accession_no = str(row.get("accession_no") or "")
        filed = str(row.get("filed_at") or row.get("filing_date") or "")
        cutoff = member_cutoffs.get(ticker)
        if not cutoff or not filed or filed < cutoff:
            continue
        if (ticker, accession_no) in processed:
            continue
        out.append({"flash": {**row, "filed_at": filed}, "names": names.get(ticker, {})})
    return out


def pending_count(store: EarningsFlashStore) -> int:
    """렌더 의존성 설치 전 preflight용 대기 건수."""
    return len(load_pending_flash(store))


__all__ = ["load_pending_flash", "pending_count"]
