"""여러 버전 중 "그 시점의 최신"을 고르는 규칙.

## 왜 고르는 일이 따로 있어야 하나

v1은 정정공시가 원본을 덮지 않는다. 같은 `(cik, period_end)`에 원본과 정정이 나란히
남으므로, **무엇이 최신인가는 저장이 아니라 조회가 정한다.** 그 규칙이 여기 있다.

규칙을 저장소 쿼리 안에만 두지 않은 이유는 두 가지다. 첫째, DB 없이 검증할 수 있어야
한다. 둘째, 같은 규칙을 화면·카드·학습이 각자 다시 쓰면 서로 다른 답을 낸다.

## 두 시각을 모두 본다

`filing_date`는 SEC에 제출된 날, `available_at`은 우리가 그것을 손에 넣은 시각이다.
as-of 조회는 **`available_at`으로 자른다** — 제출 당일 즉시 알았다고 가정하면 수집이
늦은 만큼 미래를 보게 된다. 그러고 나서 남은 것 중 제출이 가장 늦은 것을 고른다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, Sequence

from investment_agent.platform.clock import ensure_aware
from investment_agent.platform.serialization import parse_datetime

# `available_at`이 없는 버전을 정렬에서 뒤로 미는 데 쓰는 하한.
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class VersionKey:
    """버전 하나를 고르는 데 필요한 것 전부."""

    accession_no: str
    filing_date: date
    # 없으면 "언제 알았는지 모른다"는 뜻이다. as-of 조회에서는 제외된다.
    available_at: datetime | None = None

    def __post_init__(self) -> None:
        """PostgREST는 timestamptz를 **문자열**로 준다.

        그대로 두면 비교하는 순간에야 터지는데, 그 자리는 저장소에서 한참 떨어져 있어
        원인을 찾기 어렵다. 만드는 자리에서 datetime으로 맞춘다.
        """
        if isinstance(self.available_at, str):
            object.__setattr__(self, "available_at", parse_datetime(self.available_at))

    def known_at(self, as_of: datetime) -> bool:
        if self.available_at is None:
            return False
        return ensure_aware(self.available_at) <= ensure_aware(as_of)


def latest(versions: Iterable[VersionKey]) -> VersionKey | None:
    """지금 기준 최신. 제출일이 늦은 것, 같으면 나중에 손에 넣은 것.

    제출일이 같은 정정이 실제로 있다(같은 날 두 번 낸다). 그때 `available_at`이
    없으면 순서가 정해지지 않으므로, 없는 것은 뒤로 민다.
    """
    ordered = sorted(
        versions,
        key=lambda version: (
            version.filing_date,
            ensure_aware(version.available_at) if version.available_at else _EPOCH,
            version.accession_no,
        ),
    )
    return ordered[-1] if ordered else None


def latest_known_at(versions: Iterable[VersionKey], as_of: datetime) -> VersionKey | None:
    """`as_of` 시점에 우리가 알고 있던 것 중 최신.

    이것이 v1이 정정 이력을 남기는 이유 그 자체다 — "2026년 3월에 우리가 알던 2025 Q4
    매출"에 답하려면 그때 손에 없던 정정을 빼야 한다.
    """
    return latest(version for version in versions if version.known_at(as_of))


def restatement_count(versions: Sequence[VersionKey]) -> int:
    """원본 이후 몇 번 고쳤는가. 0이면 정정이 없었다는 뜻이다.

    회사가 숫자를 자주 고친다는 사실 자체가 신호라, 세는 것이 값어치가 있다.
    """
    return max(len(versions) - 1, 0)


__all__ = ["VersionKey", "latest", "latest_known_at", "restatement_count"]
