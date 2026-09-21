"""PIT 밸류에이션 입력과 관측값의 순수 계산 계약."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from investment_agent.platform.serialization import ContractError, canonical_json, parse_datetime


_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
_SOURCE_KINDS = {"live_shadow", "historical_replay"}


def _decimal(value: object, field_name: str) -> Decimal:
    """유한한 수치만 Decimal로 정규화한다."""
    if isinstance(value, bool):
        raise ContractError(f"{field_name} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ContractError(f"{field_name} must be numeric") from exc
    if not result.is_finite():
        raise ContractError(f"{field_name} must be finite")
    return result


@dataclass(frozen=True)
class PITScalar:
    """하나의 수치와 그것을 당시 알 수 있었음을 보이는 근거다."""

    value: Decimal | int | float | None
    observed_at: str | None
    available_at: str | None
    evidence_ids: tuple[str, ...] = ()
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        if self.value is None:
            if not self.missing_reason:
                raise ContractError("missing PIT scalar requires missing_reason")
            if self.observed_at or self.available_at or self.evidence_ids:
                raise ContractError("missing PIT scalar cannot carry timing or evidence")
            return
        normalized = _decimal(self.value, "PIT scalar value")
        if not self.observed_at or not self.available_at:
            raise ContractError("known PIT scalar requires observed_at and available_at")
        observed_at = parse_datetime(self.observed_at)
        available_at = parse_datetime(self.available_at)
        if available_at < observed_at:
            raise ContractError("PIT scalar available_at cannot precede observed_at")
        ids = tuple(sorted({item.strip() for item in self.evidence_ids if item.strip()}))
        if not ids:
            raise ContractError("known PIT scalar requires evidence_ids")
        if self.missing_reason is not None:
            raise ContractError("known PIT scalar cannot have missing_reason")
        object.__setattr__(self, "value", normalized)
        object.__setattr__(self, "observed_at", observed_at.isoformat())
        object.__setattr__(self, "available_at", available_at.isoformat())
        object.__setattr__(self, "evidence_ids", ids)

    @property
    def is_known(self) -> bool:
        return self.value is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "observed_at": self.observed_at,
            "available_at": self.available_at,
            "evidence_ids": list(self.evidence_ids),
            "missing_reason": self.missing_reason,
        }


@dataclass(frozen=True)
class PITValuationInputs:
    """한 거래일의 PER·PBR·PSR·FCF yield를 위한 원천 입력 계약."""

    ticker: str
    as_of_at: str
    source_kind: str
    price: PITScalar
    shares_outstanding: PITScalar
    earnings_ttm: PITScalar
    book_value: PITScalar
    revenue_ttm: PITScalar
    free_cash_flow_ttm: PITScalar

    def __post_init__(self) -> None:
        if not _TICKER_RE.fullmatch(self.ticker):
            raise ContractError(f"invalid ticker: {self.ticker}")
        if self.source_kind not in _SOURCE_KINDS:
            raise ContractError(f"invalid valuation source_kind: {self.source_kind}")
        as_of_at = parse_datetime(self.as_of_at)
        for field_name, item in self._items().items():
            if item.available_at and parse_datetime(item.available_at) > as_of_at:
                raise ContractError(f"future valuation input rejected: {field_name}")
        object.__setattr__(self, "as_of_at", as_of_at.isoformat())

    def _items(self) -> dict[str, PITScalar]:
        return {
            "price": self.price,
            "shares_outstanding": self.shares_outstanding,
            "earnings_ttm": self.earnings_ttm,
            "book_value": self.book_value,
            "revenue_ttm": self.revenue_ttm,
            "free_cash_flow_ttm": self.free_cash_flow_ttm,
        }

    @property
    def input_evidence_ids(self) -> tuple[str, ...]:
        return tuple(sorted({evidence_id for item in self._items().values() for evidence_id in item.evidence_ids}))

    @property
    def available_at(self) -> str | None:
        values = [item.available_at for item in self._items().values() if item.available_at]
        return max(values) if values else None

    @property
    def input_hash(self) -> str:
        payload = {
            "ticker": self.ticker,
            "as_of_at": self.as_of_at,
            "source_kind": self.source_kind,
            "inputs": {name: item.to_dict() for name, item in self._items().items()},
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PITValuationObservation:
    """PIT 입력에서 계산된 저장 후보 관측값이다."""

    ticker: str
    as_of_at: str
    available_at: str | None
    source_kind: str
    price: Decimal | None
    shares_outstanding: Decimal | None
    market_cap: Decimal | None
    pe_ttm: Decimal | None
    pb: Decimal | None
    ps_ttm: Decimal | None
    fcf_yield: Decimal | None
    # 아래 둘은 **부호가 살아 있는** 수익률이다. 비율(pe/fcf_yield)은 분모가 0 이하면
    # 정의되지 않아 `None`이 되는데, 적자·현금소진은 결측이 아니라 **나쁜 관측**이다.
    # 둘을 같은 `None`으로 접으면 순위에서 빠져 오히려 유리해진다(감사 RR2-01).
    # 분모가 시가총액이라 항상 양수이므로 여기서는 값이 음수로 남는다.
    earnings_to_market_cap: Decimal | None
    fcf_to_market_cap: Decimal | None
    is_meaningful_pe_ttm: bool
    is_meaningful_pb: bool
    is_meaningful_ps_ttm: bool
    is_meaningful_fcf_yield: bool
    missing_reasons: dict[str, str]
    input_evidence_ids: tuple[str, ...]
    input_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "as_of_at": self.as_of_at,
            "available_at": self.available_at,
            "source_kind": self.source_kind,
            "price": self.price,
            "shares_outstanding": self.shares_outstanding,
            "market_cap": self.market_cap,
            "pe_ttm": self.pe_ttm,
            "pb": self.pb,
            "ps_ttm": self.ps_ttm,
            "fcf_yield": self.fcf_yield,
            "earnings_to_market_cap": self.earnings_to_market_cap,
            "fcf_to_market_cap": self.fcf_to_market_cap,
            "is_meaningful_pe_ttm": self.is_meaningful_pe_ttm,
            "is_meaningful_pb": self.is_meaningful_pb,
            "is_meaningful_ps_ttm": self.is_meaningful_ps_ttm,
            "is_meaningful_fcf_yield": self.is_meaningful_fcf_yield,
            "missing_reasons": dict(sorted(self.missing_reasons.items())),
            "input_evidence_ids": list(self.input_evidence_ids),
            "input_hash": self.input_hash,
        }


def _missing(item: PITScalar, name: str, reasons: dict[str, str]) -> bool:
    if item.value is not None:
        return False
    reasons.setdefault(name, item.missing_reason or f"{name}_missing")
    return True


def _ratio(
    *,
    metric: str,
    numerator: Decimal | None,
    denominator: PITScalar,
    denominator_name: str,
    reasons: dict[str, str],
) -> Decimal | None:
    if numerator is None:
        reasons.setdefault(metric, "market_cap_missing")
        return None
    if _missing(denominator, denominator_name, reasons):
        reasons.setdefault(metric, reasons[denominator_name])
        return None
    assert denominator.value is not None
    if denominator.value <= 0:
        reasons.setdefault(metric, f"{denominator_name}_nonpositive")
        return None
    return numerator / denominator.value


def build_pit_valuation(inputs: PITValuationInputs) -> PITValuationObservation:
    """미래 입력을 차단하고 의미 있는 밸류에이션 비율만 계산한다."""
    reasons: dict[str, str] = {}
    price_missing = _missing(inputs.price, "price", reasons)
    shares_missing = _missing(inputs.shares_outstanding, "shares_outstanding", reasons)
    market_cap: Decimal | None = None
    if not price_missing and not shares_missing:
        assert inputs.price.value is not None and inputs.shares_outstanding.value is not None
        if inputs.price.value <= 0:
            reasons["market_cap"] = "price_nonpositive"
        elif inputs.shares_outstanding.value <= 0:
            reasons["market_cap"] = "shares_outstanding_nonpositive"
        else:
            market_cap = inputs.price.value * inputs.shares_outstanding.value
    else:
        reasons["market_cap"] = "price_or_shares_outstanding_missing"

    pe_ttm = _ratio(
        metric="pe_ttm", numerator=market_cap, denominator=inputs.earnings_ttm,
        denominator_name="earnings_ttm", reasons=reasons,
    )
    pb = _ratio(
        metric="pb", numerator=market_cap, denominator=inputs.book_value,
        denominator_name="book_value", reasons=reasons,
    )
    ps_ttm = _ratio(
        metric="ps_ttm", numerator=market_cap, denominator=inputs.revenue_ttm,
        denominator_name="revenue_ttm", reasons=reasons,
    )
    fcf_yield: Decimal | None = None
    if market_cap is None:
        reasons.setdefault("fcf_yield", "market_cap_missing")
    elif _missing(inputs.free_cash_flow_ttm, "free_cash_flow_ttm", reasons):
        reasons.setdefault("fcf_yield", reasons["free_cash_flow_ttm"])
    else:
        assert inputs.free_cash_flow_ttm.value is not None
        if inputs.free_cash_flow_ttm.value <= 0:
            reasons.setdefault("fcf_yield", "free_cash_flow_ttm_nonpositive")
        else:
            fcf_yield = inputs.free_cash_flow_ttm.value / market_cap

    # 부호를 보존하는 수익률. 분모는 시가총액(>0)이므로 적자·음의 FCF가 음수로 남는다.
    # 순위 매김은 이 값을 쓴다 — 비율(pe_ttm·fcf_yield)의 `None`이 "미공시"와
    # "적자"를 구별하지 못하는 것이 RR2-01의 원인이었다.
    earnings_to_market_cap: Decimal | None = None
    fcf_to_market_cap: Decimal | None = None
    if market_cap is not None:
        if inputs.earnings_ttm.value is not None:
            earnings_to_market_cap = inputs.earnings_ttm.value / market_cap
        if inputs.free_cash_flow_ttm.value is not None:
            fcf_to_market_cap = inputs.free_cash_flow_ttm.value / market_cap

    return PITValuationObservation(
        ticker=inputs.ticker,
        as_of_at=inputs.as_of_at,
        available_at=inputs.available_at,
        source_kind=inputs.source_kind,
        price=inputs.price.value,
        shares_outstanding=inputs.shares_outstanding.value,
        market_cap=market_cap,
        pe_ttm=pe_ttm,
        pb=pb,
        ps_ttm=ps_ttm,
        fcf_yield=fcf_yield,
        earnings_to_market_cap=earnings_to_market_cap,
        fcf_to_market_cap=fcf_to_market_cap,
        is_meaningful_pe_ttm=pe_ttm is not None,
        is_meaningful_pb=pb is not None,
        is_meaningful_ps_ttm=ps_ttm is not None,
        is_meaningful_fcf_yield=fcf_yield is not None,
        missing_reasons=dict(sorted(reasons.items())),
        input_evidence_ids=inputs.input_evidence_ids,
        input_hash=inputs.input_hash,
    )
