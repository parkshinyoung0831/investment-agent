"""AI 판단 대상을 현재 범용 수집 게이트 구성종목으로 제한한다."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence

from investment_agent.trading.contracts import ContractError


class UniverseRepository(Protocol):
    def current_tracked_tickers(self) -> list[str]: ...

    def candidate_tickers(self, limit: int = 50, *, as_of_at: datetime) -> list[str]: ...


@dataclass(frozen=True)
class UniverseSelection:
    """한 실행에서 검증된 tracked 전체 집합과 실제 분석 대상을 함께 보존한다."""

    members: frozenset[str]
    selected: tuple[str, ...]


def normalize_ticker(value: object) -> str:
    """universe의 Yahoo식 표기(BRK-B)에 맞춘다."""
    return str(value or "").strip().upper().replace(".", "-")


def rotate_after_latest_cases(
    tickers: Sequence[str],
    recent_cases: Sequence[dict],
    *,
    limit: int,
) -> list[str]:
    """가장 최근 실행의 마지막 종목 다음부터 순환한다."""
    ordered = sorted({normalize_ticker(ticker) for ticker in tickers if normalize_ticker(ticker)})
    if not ordered:
        return []
    start = 0
    if recent_cases:
        latest_at = str(recent_cases[0].get("as_of_at") or "")
        latest_tickers = sorted({
            normalize_ticker(row.get("ticker"))
            for row in recent_cases
            if str(row.get("as_of_at") or "") == latest_at
        })
        anchors = [ticker for ticker in latest_tickers if ticker in ordered]
        if anchors:
            indices = sorted(ordered.index(ticker) for ticker in anchors)
            if len(indices) == 1:
                anchor_index = indices[0]
            else:
                # ZZZ→AAA처럼 배열 끝을 넘긴 실행도 가장 큰 미선택 gap의 앞을
                # 실제 batch 끝으로 본다. 단순 max ticker는 AAA 쪽을 다시 고른다.
                gaps = [
                    (
                        (indices[(position + 1) % len(indices)] - current) % len(ordered),
                        current,
                    )
                    for position, current in enumerate(indices)
                ]
                anchor_index = max(gaps, key=lambda item: (item[0], item[1]))[1]
            start = (anchor_index + 1) % len(ordered)
    return (ordered[start:] + ordered[:start])[:limit]


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
        raise ContractError("no tracked tickers were selected")
    return UniverseSelection(members=members, selected=selected[:limit])
