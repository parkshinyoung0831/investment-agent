"""저장된 원천 행에서 PIT 밸류에이션 입력을 조립하는 순수 계층.

`valuation.py`가 "비율을 어떻게 계산하는가"라면 이 모듈은 "그 값을 그 시점에 정말
알 수 있었는가"를 책임진다. DB를 직접 호출하지 않고 이미 읽어온 행만 받는다.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from investment_agent.data.fundamentals.domain.filing import filing_available_at as _filing_available_at
from investment_agent.data.fundamentals.domain.periods import are_consecutive_quarters
from investment_agent.data.market.domain.calendar import bar_available_at
from investment_agent.platform.serialization import parse_datetime
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
    """일자 정밀도 공시의 가용 시각. 규칙은 fundamentals owner가 소유한다."""
    return _filing_available_at(str(filed_at))


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
    if not are_consecutive_quarters(row["period_end"] for row in quarters):
        return {name: _missing("ttm_quarters_not_consecutive") for name in names}

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
    """cutoff에 확정돼 있던 가장 최근 종가.

    가격 저장소의 봉에는 적재 시각이 없다. 그것을 필수로 요구하면 모든 종목의 가격이
    결측이 되고 시가총액·PER이 전부 조용히 빈다. 가용 시각은 market owner의 세션 규칙
    (`bar_available_at`)이 정하고, 적재 시각이 있으면 그보다 이르게 보지 않는다.
    이 종가는 **현재 분할 기준**으로 정규화된 값이다 — 주식 수를 같은 기준으로 맞추는 일은
    `shares_scalar`가 한다.
    """
    ordered = sorted(rows, key=lambda item: str(item.get("trade_date") or ""), reverse=True)
    for row in ordered:
        close = _decimal(row.get("close"))
        if close is None or close <= 0 or not row.get("trade_date"):
            continue
        available_at = bar_available_at(str(row["trade_date"]), row.get("ingested_at"))
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


def split_factor_after(split_rows: Sequence[Mapping[str, Any]], observed_on: date) -> Decimal:
    """`observed_on` **뒤에** 일어난 분할 비율의 곱.

    저장 종가는 수집 시점의 분할 기준으로 과거까지 정규화돼 있다. 그 시절 공시의 주식 수를
    그대로 곱하면 이후 분할만큼 시가총액이 작아진다(10:1 분할이면 1/10). 주식 수에 이 곱을
    곱해 가격과 같은 기준으로 맞춘다. 미래 분할을 쓰지만 새 정보가 아니다 — 가격에 이미
    들어가 있는 조정을 주식 수에도 똑같이 적용할 뿐이다.
    """
    factor = Decimal(1)
    for row in split_rows:
        ratio = _decimal(row.get("split_ratio"))
        action = row.get("action_date")
        if ratio is None or ratio <= 0 or not action:
            continue
        if date.fromisoformat(str(action)[:10]) > observed_on:
            factor *= ratio
    return factor


def shares_scalar(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of_at: datetime,
    split_rows: Sequence[Mapping[str, Any]] = (),
) -> PITScalar:
    """공개가 끝난 발행주식수 snapshot을 고르고 가격과 같은 분할 기준으로 맞춘다.

    값은 **회사 전체(모든 주식 종류) 주식수**다. 가치가 다른 종류(BRK A/B)는 근사다.

    `accepted_at`이 있으면 그 시각을 쓰고, 없으면 공시일 date-only 정책을 따른다.
    coverage가 475/503이라 결측이 정상적으로 발생한다 — 0으로 채우지 않는다.
    """
    best: tuple[datetime, Decimal, str, date] | None = None
    for row in rows:
        # 시가총액은 회사 전체 값이다. 조회 계층이 붙인 전 종류 합계를 우선하고, 없으면(단일 종류·옛
        # 표본) 그 행의 값을 쓴다. 한 종류만 쓰면 GOOGL 같은 다종류 회사의 시총이 절반이 된다.
        shares = _decimal(row.get("company_shares_outstanding"))
        if shares is None or shares <= 0:
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
            observed_on = date.fromisoformat(
                str(row.get("as_of_date") or row.get("filed_at"))[:10]
            )
            best = (
                available_at, shares,
                f"fundamentals.share_class_snapshots:{accession}:{key}",
                observed_on,
            )
    if best is None:
        return _missing("no_shares_outstanding_available_at_cutoff")
    available_at, shares, evidence_id, observed_on = best
    return PITScalar(
        value=shares * split_factor_after(split_rows, observed_on),
        observed_at=available_at.isoformat(),
        available_at=available_at.isoformat(),
        evidence_ids=(evidence_id,),
    )


def build_valuation_inputs(
    *,
    ticker: str,
    as_of_at: datetime,
    price_rows: Sequence[Mapping[str, Any]],
    fundamental_rows: Sequence[Mapping[str, Any]],
    share_rows: Sequence[Mapping[str, Any]],
    split_rows: Sequence[Mapping[str, Any]] = (),
    source_kind: str = "live_shadow",
) -> PITValuationInputs:
    """네 원천을 하나의 PIT 입력 계약으로 묶는다."""
    ttm = ttm_scalars(fundamental_rows, as_of_at=as_of_at)
    return PITValuationInputs(
        ticker=ticker.upper(),
        as_of_at=as_of_at.isoformat(),
        source_kind=source_kind,
        price=price_scalar(price_rows, as_of_at=as_of_at),
        shares_outstanding=shares_scalar(share_rows, as_of_at=as_of_at, split_rows=split_rows),
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
    "split_factor_after",
    "ttm_scalars",
]
