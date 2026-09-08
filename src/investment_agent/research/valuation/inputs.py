"""저장된 원천 행에서 PIT 밸류에이션 입력을 조립하는 순수 계층.

`valuation.py`가 "비율을 어떻게 계산하는가"라면 이 모듈은 "그 값을 그 시점에 정말
알 수 있었는가"를 책임진다. DB를 직접 호출하지 않고 이미 읽어온 행만 받는다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from investment_agent.trading.contracts import parse_datetime
from investment_agent.research.valuation.engine import PITScalar, PITValuationInputs

# TTM은 직전 4개 분기의 합이다. financials의 분기 행은 Q1~Q4로 구분한다.
TTM_QUARTERS = 4

# 자기자본은 flow가 아니라 잔액이다 — 4분기를 더하면 4배가 되므로 최근 분기 값만 쓴다.
_EQUITY_FIELD = "common_equity"


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None
    return result if result.is_finite() else None


def filing_available_at(filed_at: Any) -> datetime:
    """일자 정밀도 공시를 **다음 날 0시 UTC**로 보수적으로 환산한다.

    `filings.filing_date`는 date라 그날 몇 시에 공개됐는지 알 수 없다. 그날
    0시로 잡으면 실제보다 이르게 "알 수 있었다"고 주장하게 되므로, 하루를 넘겨
    확정된 것으로 본다. 같은 날 공시는 다음 실행에서 잡힌다.
    """
    parsed = date.fromisoformat(str(filed_at)[:10])
    return datetime(
        parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc,
    ) + timedelta(days=1)


def _quarter_key(row: Mapping[str, Any]) -> tuple[int, str]:
    return int(row["fiscal_year"]), str(row["fiscal_period"])


def select_ttm_quarters(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of_at: datetime,
) -> list[dict[str, Any]]:
    """as_of 시점에 공개가 끝난 분기 중 최근 4개를 중복 없이 고른다.

    같은 분기가 정정으로 여러 번 나오면 **먼저 공개된 행**을 쓴다. 나중 정정본을
    쓰면 그 시점에 알 수 없던 값이 섞인다.
    """
    by_quarter: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        if row.get("fiscal_year") is None or not row.get("fiscal_period"):
            continue
        if not row.get("period_end") or not row.get("filed_at"):
            continue
        if filing_available_at(row["filed_at"]) > as_of_at:
            continue
        key = _quarter_key(row)
        current = by_quarter.get(key)
        if current is None or str(row["filed_at"]) < str(current["filed_at"]):
            by_quarter[key] = dict(row)
    ordered = sorted(
        by_quarter.values(),
        key=lambda row: (str(row["period_end"]), _quarter_key(row)),
        reverse=True,
    )
    return ordered[:TTM_QUARTERS]


def _missing(reason: str) -> PITScalar:
    return PITScalar(value=None, observed_at=None, available_at=None, missing_reason=reason)


def _evidence_id(row: Mapping[str, Any]) -> str:
    accession = str(row.get("accession_no") or "").strip()
    if accession:
        return f"fundamentals.financials:{accession}"
    return f"fundamentals.financials:{row.get('ticker')}:{row.get('period_end')}"


def ttm_scalars(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of_at: datetime,
) -> dict[str, PITScalar]:
    """TTM 순이익·매출·FCF와 최신 자기자본을 근거·가용시각과 함께 만든다."""
    quarters = select_ttm_quarters(rows, as_of_at=as_of_at)
    names = ("earnings_ttm", "revenue_ttm", "free_cash_flow_ttm", "book_value")
    if len(quarters) < TTM_QUARTERS:
        reason = f"ttm_incomplete_{len(quarters)}_of_{TTM_QUARTERS}_quarters"
        return {name: _missing(reason) for name in names}

    available_at = max(filing_available_at(row["filed_at"]) for row in quarters)
    observed_at = max(
        datetime.combine(
            date.fromisoformat(str(row["period_end"])[:10]), datetime.min.time(), timezone.utc,
        )
        for row in quarters
    )
    evidence_ids = tuple(sorted({_evidence_id(row) for row in quarters}))
    latest = quarters[0]

    def _known(value: Decimal) -> PITScalar:
        return PITScalar(
            value=value,
            observed_at=observed_at.isoformat(),
            available_at=available_at.isoformat(),
            evidence_ids=evidence_ids,
        )

    def _sum(field: str) -> Decimal | None:
        total = Decimal(0)
        for row in quarters:
            value = _decimal(row.get(field))
            if value is None:
                return None
            total += value
        return total

    result: dict[str, PITScalar] = {}
    earnings = _sum("net_income")
    result["earnings_ttm"] = _known(earnings) if earnings is not None else _missing("net_income_missing_in_ttm_window")
    revenue = _sum("revenue")
    result["revenue_ttm"] = _known(revenue) if revenue is not None else _missing("revenue_missing_in_ttm_window")

    operating = _sum("net_cash_from_operating_activities")
    capex = _sum("capital_expenses")
    if operating is None:
        result["free_cash_flow_ttm"] = _missing("operating_cash_flow_missing_in_ttm_window")
    elif capex is None:
        result["free_cash_flow_ttm"] = _missing("capital_expenses_missing_in_ttm_window")
    else:
        # capital_expenses는 유출을 양수로 적재하므로 절대값을 뺀다.
        result["free_cash_flow_ttm"] = _known(operating - abs(capex))

    equity = _decimal(latest.get(_EQUITY_FIELD))
    if equity is None:
        result["book_value"] = _missing("common_equity_missing")
    else:
        result["book_value"] = PITScalar(
            value=equity,
            observed_at=datetime.combine(
                date.fromisoformat(str(latest["period_end"])[:10]),
                datetime.min.time(), timezone.utc,
            ).isoformat(),
            available_at=filing_available_at(latest["filed_at"]).isoformat(),
            evidence_ids=(_evidence_id(latest),),
        )
    return result


def price_scalar(rows: Sequence[Mapping[str, Any]], *, as_of_at: datetime) -> PITScalar:
    """가장 최근 종가를 실제 적재 시각과 함께 만든다."""
    for row in rows:
        close = _decimal(row.get("close"))
        ingested = row.get("ingested_at")
        if close is None or close <= 0 or not ingested:
            continue
        available_at = parse_datetime(str(ingested))
        if available_at > as_of_at:
            continue
        return PITScalar(
            value=close,
            observed_at=datetime.combine(
                date.fromisoformat(str(row["trade_date"])[:10]),
                datetime.min.time(), timezone.utc,
            ).isoformat(),
            available_at=available_at.isoformat(),
            evidence_ids=(f"market.prices_daily:{row.get('ticker')}:{row.get('trade_date')}",),
        )
    return _missing("no_price_available_at_cutoff")


def shares_scalar(rows: Sequence[Mapping[str, Any]], *, as_of_at: datetime) -> PITScalar:
    """공개가 끝난 발행주식수 snapshot을 고른다.

    `accepted_at`이 있으면 그 시각을 쓰고, 없으면 공시일 date-only 정책을 따른다.
    coverage가 475/503이라 결측이 정상적으로 발생한다 — 0으로 채우지 않는다.
    """
    best: tuple[datetime, Decimal, str] | None = None
    for row in rows:
        shares = _decimal(row.get("shares_outstanding"))
        if shares is None or shares <= 0:
            continue
        accepted = row.get("accepted_at")
        available_at = (
            parse_datetime(str(accepted)) if accepted
            else filing_available_at(row.get("filed_at") or row.get("as_of_date"))
        )
        if available_at > as_of_at:
            continue
        if best is None or available_at > best[0]:
            accession = str(row.get("accession_no") or "").strip()
            key = str(row.get("share_class_key") or "")
            best = (
                available_at, shares,
                f"fundamentals.share_class_snapshots:{accession}:{key}",
            )
    if best is None:
        return _missing("no_shares_outstanding_available_at_cutoff")
    available_at, shares, evidence_id = best
    return PITScalar(
        value=shares,
        observed_at=available_at.isoformat(),
        available_at=available_at.isoformat(),
        evidence_ids=(evidence_id,),
    )


def build_valuation_inputs(
    *,
    ticker: str,
    as_of_at: datetime,
    source_version: str,
    price_rows: Sequence[Mapping[str, Any]],
    fundamental_rows: Sequence[Mapping[str, Any]],
    share_rows: Sequence[Mapping[str, Any]],
    source_kind: str = "live_shadow",
) -> PITValuationInputs:
    """네 원천을 하나의 PIT 입력 계약으로 묶는다."""
    ttm = ttm_scalars(fundamental_rows, as_of_at=as_of_at)
    return PITValuationInputs(
        ticker=ticker.upper(),
        as_of_at=as_of_at.isoformat(),
        source_kind=source_kind,
        source_version=source_version,
        price=price_scalar(price_rows, as_of_at=as_of_at),
        shares_outstanding=shares_scalar(share_rows, as_of_at=as_of_at),
        earnings_ttm=ttm["earnings_ttm"],
        book_value=ttm["book_value"],
        revenue_ttm=ttm["revenue_ttm"],
        free_cash_flow_ttm=ttm["free_cash_flow_ttm"],
    )


__all__ = [
    "TTM_QUARTERS",
    "build_valuation_inputs",
    "filing_available_at",
    "price_scalar",
    "select_ttm_quarters",
    "shares_scalar",
    "ttm_scalars",
]
