"""universe가 다루는 사실의 모양.

저장소 행(dict)과 코드가 쓰는 값을 나누는 자리다. dict를 그대로 들고 다니면
컬럼 이름 오타가 `None`으로 조용히 흡수되고, 그 `None`은 한참 뒤에 다른 곳에서
터진다. dataclass는 그것을 만드는 자리에서 막는다.

`from_row()`는 저장소 컬럼명을 **한 곳에서만** 안다. 스키마가 바뀌면 여기만 고친다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

from investment_agent.data.universe.domain.identifiers import (
    normalize_cik,
    normalize_ticker,
)
from investment_agent.platform.clock import as_date


class UniverseDataError(ValueError):
    """저장소 행이 universe의 계약을 어겼다."""


@dataclass(frozen=True)
class Entity:
    """발행사. 회사 사실은 CIK에 한 번만 있다."""

    cik: str
    company_name: str
    company_name_ko: str | None = None
    sic_code: str | None = None
    # SIC는 GICS 섹터가 아니다. 이름이 그것을 말하게 둔다.
    sic_industry_name: str | None = None
    sic_division_name: str | None = None
    fiscal_year_end: str | None = None
    entity_type: str | None = None
    state_of_incorporation: str | None = None
    former_names: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Entity":
        cik = normalize_cik(row.get("cik"))
        if cik is None:
            raise UniverseDataError(f"unreadable cik: {row.get('cik')!r}")
        name = str(row.get("company_name") or "").strip()
        if not name:
            raise UniverseDataError(f"entity {cik} has no company_name")
        return cls(
            cik=cik,
            company_name=name,
            company_name_ko=row.get("company_name_ko"),
            sic_code=row.get("sic_code"),
            sic_industry_name=row.get("sic_industry_name"),
            sic_division_name=row.get("sic_division_name"),
            fiscal_year_end=row.get("fiscal_year_end"),
            entity_type=row.get("entity_type"),
            state_of_incorporation=row.get("state_of_incorporation"),
            former_names=tuple(row.get("former_names") or ()),
        )


@dataclass(frozen=True)
class Security:
    """상장 종목. identity는 `security_id`이고 `ticker`는 현재 표기다."""

    security_id: int
    ticker: str
    cik: str | None
    exchange_code: str | None = None
    security_type: str = "common_stock"
    security_title: str | None = None
    is_active_listing: bool = True
    is_tracked: bool = False

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Security":
        ticker = normalize_ticker(row.get("ticker"))
        if ticker is None:
            raise UniverseDataError(f"unreadable ticker: {row.get('ticker')!r}")
        security_id = row.get("security_id")
        if security_id is None:
            raise UniverseDataError(f"{ticker} has no security_id")
        return cls(
            security_id=int(security_id),
            ticker=ticker,
            # cik는 없을 수 있다(비상장·미매핑). 그 사실을 예외로 만들지 않는다.
            cik=normalize_cik(row.get("cik")),
            exchange_code=row.get("exchange_code"),
            security_type=str(row.get("security_type") or "common_stock"),
            security_title=row.get("security_title"),
            is_active_listing=bool(row.get("is_active_listing", True)),
            is_tracked=bool(row.get("is_tracked", False)),
        )


@dataclass(frozen=True)
class MembershipSnapshot:
    """그날 지수에 무엇이 있었는가.

    이것이 없으면 backtest가 생존 편향에 걸린다 — 지금 살아남은 종목만 과거에
    넣게 되기 때문이다. 그래서 "오늘의 목록"이 아니라 날짜별 원장으로 다룬다.
    """

    index_code: str
    effective_date: date
    tickers: tuple[str, ...] = field(default_factory=tuple)
    source: str = ""

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "MembershipSnapshot":
        effective = as_date(row.get("effective_date"))
        if effective is None:
            raise UniverseDataError(f"unreadable effective_date: {row.get('effective_date')!r}")
        raw = row.get("tickers") or []
        if not isinstance(raw, (list, tuple)):
            raise UniverseDataError("tickers must be an array")
        tickers = tuple(sorted({t for t in (normalize_ticker(v) for v in raw) if t}))
        declared = row.get("member_count")
        # 선언된 수와 실제가 다르면 목록이 잘렸거나 중복이 있었다는 뜻이다. 그 상태로
        # backtest에 넣으면 그날 하루가 통째로 틀린다.
        if declared is not None and int(declared) != len(tickers):
            raise UniverseDataError(
                f"{row.get('index_code')} {effective}: member_count {declared} "
                f"but {len(tickers)} readable tickers"
            )
        return cls(
            index_code=str(row.get("index_code") or ""),
            effective_date=effective,
            tickers=tickers,
            source=str(row.get("source") or ""),
        )


@dataclass(frozen=True)
class WatchlistMember:
    """더 깊이 볼 회사. 알림 여부는 여기서 정하지 않는다(notifications의 몫).

    관심의 identity는 `cik`다. `ticker`·`security_id`는 그 회사의 대표 종목을
    읽기 경계에서 붙인 표시용 값이다 — 회사가 클래스를 나눠 상장해도 관심은 하나다.
    """

    cik: str
    ticker: str
    security_id: int
    sources: tuple[str, ...]
    watch_from: date | None

    @property
    def is_active(self) -> bool:
        """출처가 하나라도 남아 있으면 계속 본다.

        토스 보유가 빠져도 수동 등록이 남아 있으면 활성이다. 저장소도 같은 식으로
        `is_active`를 만든다 — 정의가 두 군데 있으면 언젠가 갈라진다.
        """
        return bool(self.sources)

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "WatchlistMember":
        ticker = normalize_ticker(row.get("ticker"))
        if ticker is None:
            raise UniverseDataError(f"unreadable ticker: {row.get('ticker')!r}")
        return cls(
            cik=str(row["cik"]),
            ticker=ticker,
            security_id=int(row["security_id"]),
            sources=tuple(row.get("sources") or ()),
            watch_from=as_date(row.get("watch_from")),
        )


__all__ = [
    "Entity",
    "MembershipSnapshot",
    "Security",
    "UniverseDataError",
    "WatchlistMember",
]
