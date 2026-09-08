"""시세와 corporate action의 모양.

저장소가 CHECK로 막는 것과 **같은 규칙**을 여기서도 본다. 두 번 검사하는 이유는
실패하는 자리를 앞으로 당기기 위해서다 — 저장소가 거부하면 그 배치 전체가 죽고
어느 행이 문제였는지 메시지로만 알 수 있지만, 여기서 걸리면 그 행만 골라낼 수 있다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from investment_agent.platform.clock import as_date
from investment_agent.platform.serialization import finite_float


class MarketDataError(ValueError):
    """시세 행이 계약을 어겼다. 그 행만 버리고 나머지는 계속 간다."""


@dataclass(frozen=True)
class DailyBar:
    """하루치 봉. **조정가는 담지 않는다** — 조정은 읽는 쪽이 그때의 규칙으로 한다."""

    security_id: int
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    is_repaired: bool = False

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "DailyBar":
        trade_date = as_date(row.get("trade_date"))
        if trade_date is None:
            raise MarketDataError(f"unreadable trade_date: {row.get('trade_date')!r}")
        prices = {}
        for name in ("open", "high", "low", "close"):
            value = finite_float(row.get(name))
            # 0이나 음수는 가격이 아니다. NaN은 numeric에 들어가고 이후 집계를 전부 오염시킨다.
            if value is None or value <= 0:
                raise MarketDataError(f"{trade_date}: {name} is not a usable price ({row.get(name)!r})")
            prices[name] = value
        volume = row.get("volume")
        if volume is None or int(volume) < 0:
            raise MarketDataError(f"{trade_date}: volume is not usable ({volume!r})")
        bar = cls(
            security_id=int(row["security_id"]),
            trade_date=trade_date,
            volume=int(volume),
            is_repaired=bool(row.get("is_repaired", False)),
            **prices,
        )
        bar.validate()
        return bar

    def validate(self) -> None:
        """OHLC가 서로 모순이면 그 봉은 어떤 계산에도 쓸 수 없다."""
        if self.high < max(self.open, self.low, self.close):
            raise MarketDataError(f"{self.trade_date}: high {self.high} is below another price")
        if self.low > min(self.open, self.high, self.close):
            raise MarketDataError(f"{self.trade_date}: low {self.low} is above another price")

    def as_row(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "trade_date": self.trade_date.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "is_repaired": self.is_repaired,
        }


@dataclass(frozen=True)
class SplitEvent:
    """주식분할. 비율 1은 분할이 아니다 — 그런 행은 조정을 아무것도 안 하면서
    '분할이 있었다'고 말한다."""

    security_id: int
    action_date: date
    split_ratio: float

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "SplitEvent":
        action_date = as_date(row.get("action_date"))
        ratio = finite_float(row.get("split_ratio"))
        if action_date is None:
            raise MarketDataError(f"unreadable action_date: {row.get('action_date')!r}")
        if ratio is None or ratio <= 0 or math.isclose(ratio, 1.0):
            raise MarketDataError(f"{action_date}: split_ratio {row.get('split_ratio')!r} is not a split")
        return cls(
            security_id=int(row["security_id"]),
            action_date=action_date,
            split_ratio=ratio,
        )

    def as_row(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "action_date": self.action_date.isoformat(),
            "split_ratio": self.split_ratio,
        }


@dataclass(frozen=True)
class DividendEvent:
    """배당락일과 금액. 0은 허용한다 — 소스가 0으로 '배당 없음'을 말하는 날이 있다."""

    security_id: int
    ex_date: date
    div_amount: float

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "DividendEvent":
        ex_date = as_date(row.get("ex_date"))
        amount = finite_float(row.get("div_amount"))
        if ex_date is None:
            raise MarketDataError(f"unreadable ex_date: {row.get('ex_date')!r}")
        if amount is None or amount < 0:
            raise MarketDataError(f"{ex_date}: div_amount {row.get('div_amount')!r} is not usable")
        return cls(
            security_id=int(row["security_id"]),
            ex_date=ex_date,
            div_amount=amount,
        )

    def as_row(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "ex_date": self.ex_date.isoformat(),
            "div_amount": self.div_amount,
        }


__all__ = ["DailyBar", "DividendEvent", "MarketDataError", "SplitEvent"]
