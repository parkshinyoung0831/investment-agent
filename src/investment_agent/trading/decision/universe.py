"""AI 판단 대상을 현재 범용 수집 게이트 구성종목으로 제한한다."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence

from investment_agent.trading.contracts import ContractError


class UniverseRepository(Protocol):
    def current_tracked_tickers(self) -> list[str]: ...

    def candidate_tickers(self, limit: int = 50, *, as_of_at: datetime) -> list[str]: ...


class NoCandidatesDue(ContractError):
    """자동 선정에서 지금 다시 판단할 종목이 없다. 오류가 아니라 '이번 회차는 할 일 없음'이다."""


@dataclass(frozen=True)
class UniverseSelection:
    """한 실행에서 검증된 tracked 전체 집합과 실제 분석 대상을 함께 보존한다."""

    members: frozenset[str]
    selected: tuple[str, ...]


def normalize_ticker(value: object) -> str:
    """universe의 Yahoo식 표기(BRK-B)에 맞춘다."""
    return str(value or "").strip().upper().replace(".", "-")


def select_tracked_tickers(
    repository: UniverseRepository,
    requested: Sequence[str] | None,
    *,
    limit: int,
    as_of_at: datetime,
) -> UniverseSelection:
    """명시 종목도 현재 tracked universe 밖이면 fail-closed 한다."""
    if as_of_at.tzinfo is None:
        raise ContractError("candidate as_of_at must include timezone")
    members = frozenset(
        ticker for ticker in (
            normalize_ticker(value) for value in repository.current_tracked_tickers()
        ) if ticker
    )
    if not members:
        raise ContractError("current tracked universe is empty")

    if requested:
        selected = tuple(sorted({
            normalize_ticker(ticker)
            for ticker in requested
            if str(ticker).strip()
        }))
        outside = sorted(set(selected) - members)
        if outside:
            raise ContractError(
                "requested tickers are outside the current tracked universe: " + ", ".join(outside)
            )
    else:
        selected = tuple(
            ticker for ticker in (
                normalize_ticker(value)
                for value in repository.candidate_tickers(limit, as_of_at=as_of_at)
            ) if ticker
        )
        outside = sorted(set(selected) - members)
        if outside:
            raise ContractError(
                "candidate selection escaped the current tracked universe: " + ", ".join(outside)
            )
        if not selected:
            raise NoCandidatesDue("no tracked tickers are due for analysis")

    if not selected:
        raise ContractError("no tracked tickers were selected")
    return UniverseSelection(members=members, selected=selected[:limit])
