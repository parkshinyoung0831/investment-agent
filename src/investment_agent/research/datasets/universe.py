"""연구 산출물을 만들 종목 집합.

운영(`live_shadow`)은 지금 추적 중인 종목이다. 과거 재현(`historical_replay`)은 **그 시점의
S&P 500 멤버**다. 과거 시점에 지금의 종목 목록을 쓰면 그 사이 편출·상장폐지된 기업이 빠져,
살아남은 기업만으로 학습·검증하는 생존 편향이 예외 없이 생긴다.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol, Sequence

from investment_agent.data.universe import persistence as universe_data
from investment_agent.data.market.domain.calendar import MARKET_TIMEZONE
from investment_agent.platform.serialization import parse_datetime


class UniverseRepository(Protocol):
    def current_tracked_tickers(self) -> list[str]: ...
    def historical_sp500_membership(self, *, start_date: Any, end_date: Any) -> list[dict[str, Any]]: ...


class DataUniverseReader:
    """Research가 사용하는 universe 입력을 canonical Data owner에서 읽는다.

    Historical replay가 명시적으로 repository를 주입하는 경로는 이 reader로 바꾸지 않는다.
    기본 live command만 Data owner를 직접 소비해 Trading façade를 경유하지 않게 한다.
    """

    def current_tracked_tickers(self) -> list[str]:
        return sorted({str(ticker).upper() for ticker in universe_data.select_tracked_tickers()})

    def historical_sp500_membership(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        return universe_data.select_sp500_membership_snapshots(
            start_date=start_date,
            end_date=end_date,
        )

    def rl_historical_membership_rows(
        self,
        *,
        start_as_of: str,
        end_as_of: str,
    ) -> list[dict[str, Any]]:
        """기존 RL MembershipTimeline 입력 계약으로 PIT snapshot을 변환한다."""
        start = parse_datetime(start_as_of)
        end = parse_datetime(end_as_of)
        if end < start:
            raise ValueError("membership end_as_of must not precede start_as_of")
        snapshots = self.historical_sp500_membership(
            start_date=start.date(),
            end_date=end.date(),
        )
        return [
            {
                "effective_at": f"{row['effective_date']}T00:00:00+00:00",
                "symbols": list(row["symbols"]),
                "source_id": str(row.get("source_hash") or row.get("source") or ""),
                "source_kind": "historical_point_in_time",
            }
            for row in snapshots
        ]


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


__all__ = ["DataUniverseReader", "members_over_window", "research_universe"]
