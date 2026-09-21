"""8-K 실적 속보 알림 대상 후보 선정."""
from __future__ import annotations

from datetime import timedelta

from investment_agent.platform.clock import kst_today
from investment_agent.platform.env import env_int
from investment_agent.reporting.notifications.earnings_flash import EarningsFlashStore
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)
_DEFAULT_LOOKBACK_DAYS = 7


def _lookback_days() -> int:
    return env_int("FLASH_NOTIFY_LOOKBACK_DAYS", _DEFAULT_LOOKBACK_DAYS, minimum=1, maximum=365)


def _cutoff() -> str:
    return (kst_today() - timedelta(days=_lookback_days())).isoformat()


def load_flash_candidates(
    store: EarningsFlashStore,
    tickers: set[str] | None = None,
) -> list[dict]:
    """관심종목의 최근 8-K 실적 속보. 등록일 이전 공시는 뺀다 — 이미 보냈는지는 원장이 가른다."""
    members = store.watchlist_members()
    if tickers is not None:
        members = [member for member in members if str(member.get("ticker") or "") in tickers]
    selected_tickers = [str(member["ticker"]) for member in members]
    if not selected_tickers:
        log.info("flash: 활성 관심종목 없음 — 조회 생략")
        return []

    global_cutoff = _cutoff()
    member_cutoffs = {
        str(member["ticker"]): max(global_cutoff, str(member.get("watch_from") or global_cutoff))
        for member in members
    }
    names = store.load_names(selected_tickers)

    out: list[dict] = []
    for row in store.load_flash_rows(selected_tickers, global_cutoff):
        ticker = str(row.get("ticker") or "")
        filed = str(row.get("filed_at") or row.get("filing_date") or "")
        cutoff = member_cutoffs.get(ticker)
        if not cutoff or not filed or filed < cutoff:
            continue
        out.append({"flash": {**row, "filed_at": filed}, "names": names.get(ticker, {})})
    return out


__all__ = ["load_flash_candidates"]
