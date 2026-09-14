"""연구 산출물을 만들 종목 집합.

운영(`live_shadow`)은 지금 추적 중인 종목이다. 과거 재현(`historical_replay`)은 **그 시점의
S&P 500 멤버**다. 과거 시점에 지금의 종목 목록을 쓰면 그 사이 편출·상장폐지된 기업이 빠져,
살아남은 기업만으로 학습·검증하는 생존 편향이 예외 없이 생긴다.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol, Sequence

from investment_agent.data.market.domain.calendar import MARKET_TIMEZONE


class UniverseRepository(Protocol):
    def current_tracked_tickers(self) -> list[str]: ...
    def historical_sp500_membership(self, *, start_date: Any, end_date: Any) -> list[dict[str, Any]]: ...


def research_universe(
    repository: UniverseRepository,
    *,
    as_of_at: datetime,
    source_kind: str,
) -> list[str]:
    """source_kind에 맞는 종목 목록. 과거 멤버십을 모르면 조용히 현재 목록으로 대체하지 않는다."""
    if source_kind == "live_shadow":
        return sorted({str(ticker).upper() for ticker in repository.current_tracked_tickers()})
    if source_kind != "historical_replay":
        raise ValueError(f"unsupported source_kind: {source_kind}")
    if as_of_at.tzinfo is None:
        raise ValueError("as_of_at must include timezone")
    day = as_of_at.astimezone(MARKET_TIMEZONE).date()
    snapshots: Sequence[dict[str, Any]] = repository.historical_sp500_membership(start_date=day, end_date=day)
    if not snapshots:
        raise RuntimeError(f"no point-in-time S&P 500 membership for {day.isoformat()}")
    return sorted({str(ticker).upper() for ticker in snapshots[-1]["symbols"]})


def members_over_window(repository: UniverseRepository, *, start: date, end: date) -> tuple[str, ...]:
    """창 안에서 한 번이라도 S&P 500이었던 종목과 지금 추적 중인 종목.

    학습 dataset·label을 현재 종목으로만 모으면 창 안에서 빠진 기업의 표본이 통째로 사라진다.
    """
    symbols = {str(ticker).upper() for ticker in repository.current_tracked_tickers()}
    if hasattr(repository, "historical_sp500_membership"):
        for snapshot in repository.historical_sp500_membership(start_date=start, end_date=end):
            symbols.update(str(ticker).upper() for ticker in snapshot["symbols"])
    return tuple(sorted(symbols))


__all__ = ["members_over_window", "research_universe"]
