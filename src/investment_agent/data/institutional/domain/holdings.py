"""13F 보유 신고를 읽는 규칙.

## 정정이 원본을 대체하는 방식이 두 가지다

13F 정정(13F-HR/A)에는 두 종류가 있고, 처리가 정반대다.

* `RESTATEMENT` — **그 분기 전체를 다시 낸 것.** 원본을 무시하고 이것만 본다.
* `NEW HOLDINGS` — **빠뜨린 것을 덧붙인 것.** 원본에 더한다.

이 구분을 놓치면 한쪽은 보유가 두 배로 세지고, 다른 쪽은 절반이 사라진다. 둘 다
예외를 던지지 않는다.

## 보유는 옵션과 섞이면 안 된다

`position_kind`가 `PUT`/`CALL`인 행은 주식 보유가 아니다. 합쳐서 "이 매니저가 들고
있는 종목"이라고 부르면 풋 포지션이 매수로 둔갑한다.

## 값은 분기말 기준이다

13F는 분기말(`period_end`) 상태를 45일 안에 낸다. **`filing_date`가 아니라
`period_end`가 그 숫자가 말하는 시점**이고, PIT 조회는 공시가 나온 뒤에만 그것을
쓸 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

from investment_agent.platform.clock import as_date
from investment_agent.platform.serialization import finite_float

AMENDMENT_RESTATEMENT = "RESTATEMENT"
AMENDMENT_NEW_HOLDINGS = "NEW HOLDINGS"

POSITION_KINDS = ("SHARES", "PUT", "CALL")
SHARE_KIND = "SHARES"


class HoldingsError(ValueError):
    """13F 행이 계약을 어겼다."""


@dataclass(frozen=True)
class Filing13F:
    """한 매니저의 한 분기 신고."""

    accession_no: str
    manager_cik: str
    period_end: date
    form_type: str
    filing_date: date
    amendment_type: str | None = None
    amendment_no: int | None = None
    reported_value_usd: float = 0.0

    @property
    def is_amendment(self) -> bool:
        return self.form_type.endswith("/A")

    @property
    def replaces_original(self) -> bool:
        """이 신고가 원본을 통째로 대체하는가."""
        return self.amendment_type == AMENDMENT_RESTATEMENT

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Filing13F":
        period_end = as_date(row.get("period_end"))
        filing_date = as_date(row.get("filing_date"))
        if period_end is None or filing_date is None:
            raise HoldingsError(f"{row.get('accession_no')}: unreadable dates")
        if period_end > filing_date:
            # 분기말 뒤에 내는 것이 13F다. 뒤집혀 있으면 그 행은 미래를 보고한 것이다.
            raise HoldingsError(f"{row.get('accession_no')}: period_end is after filing_date")
        return cls(
            accession_no=str(row["accession_no"]),
            manager_cik=str(row["manager_cik"]),
            period_end=period_end,
            form_type=str(row.get("form_type") or "13F-HR"),
            filing_date=filing_date,
            amendment_type=row.get("amendment_type"),
            amendment_no=row.get("amendment_no"),
            reported_value_usd=finite_float(row.get("reported_value_usd"), 0.0) or 0.0,
        )


@dataclass(frozen=True)
class Position:
    """신고서의 한 줄. `identifier`는 CUSIP이라 종목 매핑은 universe가 한다."""

    accession_no: str
    source_row_no: int
    issuer_name: str
    identifier: str
    value_usd: float
    quantity: int
    position_kind: str = SHARE_KIND

    @property
    def is_share_position(self) -> bool:
        """주식 보유인가. 옵션과 섞으면 풋이 매수로 둔갑한다."""
        return self.position_kind == SHARE_KIND

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Position":
        kind = str(row.get("position_kind") or SHARE_KIND)
        if kind not in POSITION_KINDS:
            raise HoldingsError(f"unknown position_kind: {kind!r}")
        value = finite_float(row.get("value_usd"))
        if value is None or value < 0:
            raise HoldingsError(f"{row.get('accession_no')}: value_usd is not usable")
        return cls(
            accession_no=str(row["accession_no"]),
            source_row_no=int(row["source_row_no"]),
            issuer_name=str(row.get("issuer_name") or ""),
            identifier=str(row.get("identifier") or "").strip().upper(),
            value_usd=value,
            quantity=int(row.get("quantity") or 0),
            position_kind=kind,
        )


def effective_filings(filings: Iterable[Filing13F]) -> list[Filing13F]:
    """한 매니저·한 분기에서 **실제로 유효한** 신고들.

    `RESTATEMENT`가 있으면 그것 하나만, 없으면 원본과 `NEW HOLDINGS` 정정을 함께 쓴다.
    이 구분을 놓치면 보유가 두 배로 세지거나 절반이 사라진다.
    """
    by_quarter: dict[tuple[str, date], list[Filing13F]] = {}
    for filing in filings:
        by_quarter.setdefault((filing.manager_cik, filing.period_end), []).append(filing)

    effective: list[Filing13F] = []
    for group in by_quarter.values():
        restatements = [item for item in group if item.replaces_original]
        if restatements:
            # 여러 번 다시 낸 경우 마지막 것만 유효하다.
            effective.append(max(restatements, key=lambda item: (item.filing_date, item.accession_no)))
            continue
        effective.extend(sorted(group, key=lambda item: (item.filing_date, item.accession_no)))
    return sorted(effective, key=lambda item: (item.manager_cik, item.period_end, item.filing_date))


def share_positions(positions: Iterable[Position]) -> list[Position]:
    """주식 보유만. 옵션은 성격이 달라 같은 목록에 두지 않는다."""
    return [item for item in positions if item.is_share_position]


def portfolio_weights(positions: Sequence[Position]) -> dict[str, float]:
    """CUSIP별 비중. 합이 0이면 빈 결과 — 0으로 나누지 않는다.

    비중은 신고된 시장가치 기준이다. 주식수 기준으로 하면 가격이 다른 종목을 같은
    무게로 세게 된다.
    """
    shares = share_positions(positions)
    total = sum(item.value_usd for item in shares)
    if total <= 0:
        return {}
    weights: dict[str, float] = {}
    for item in shares:
        # 같은 CUSIP이 여러 줄로 나뉘어 오는 일이 있다(운용 재량별 분리 보고).
        weights[item.identifier] = weights.get(item.identifier, 0.0) + item.value_usd / total
    return weights


__all__ = [
    "AMENDMENT_NEW_HOLDINGS",
    "AMENDMENT_RESTATEMENT",
    "Filing13F",
    "HoldingsError",
    "POSITION_KINDS",
    "Position",
    "SHARE_KIND",
    "effective_filings",
    "portfolio_weights",
    "share_positions",
]
