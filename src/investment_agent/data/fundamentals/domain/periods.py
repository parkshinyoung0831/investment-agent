"""회계기간의 규칙.

## 달력 분기가 아니다

회사마다 회계연도 끝이 다르다(애플은 9월, 마이크로소프트는 6월). `period_end`가
2026-06-30이라는 사실만으로는 그것이 Q2인지 FY인지 알 수 없고, **회사의 회계력을
알아야** 정해진다. 그래서 여기서는 기간을 추측하지 않는다 — 공시가 말한 것을 그대로
쓰고, 모양이 맞는지만 본다.

## Q4는 대개 보고되지 않는다

미국 상장사는 4분기를 따로 내지 않고 연간(10-K)만 낸다. Q4가 필요하면 **FY에서
Q1~Q3를 빼서** 만드는데, 그렇게 만든 값은 보고된 값과 성격이 다르다. 그것을 표시 없이
섞으면 "이 회사의 분기 매출 추세"가 조용히 틀린다 — 그래서 파생 여부를 값과 함께
들고 다닌다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Sequence

QUARTERS = ("Q1", "Q2", "Q3", "Q4")
FISCAL_PERIODS = ("Q1", "Q2", "Q3", "Q4", "FY")


class PeriodError(ValueError):
    """회계기간이 계약을 어겼다."""


@dataclass(frozen=True, order=True)
class FiscalPeriod:
    """회사 회계력 위의 한 지점. 정렬하면 시간 순이 된다."""

    fiscal_year: int
    fiscal_period: str

    def __post_init__(self) -> None:
        if not 1900 <= self.fiscal_year <= 2200:
            raise PeriodError(f"fiscal_year out of range: {self.fiscal_year}")
        if self.fiscal_period not in FISCAL_PERIODS:
            raise PeriodError(f"unknown fiscal_period: {self.fiscal_period!r}")

    @property
    def is_annual(self) -> bool:
        return self.fiscal_period == "FY"

    @property
    def label(self) -> str:
        """사람이 읽는 표기. 카드와 화면이 같은 문자열을 쓰게 한다."""
        return f"{self.fiscal_year} {self.fiscal_period}"

    def previous_quarter(self) -> "FiscalPeriod":
        """직전 분기. 연간에는 정의되지 않는다 — FY의 '직전'은 분기가 아니다."""
        if self.is_annual:
            raise PeriodError("FY has no previous quarter")
        index = QUARTERS.index(self.fiscal_period)
        if index == 0:
            return FiscalPeriod(self.fiscal_year - 1, "Q4")
        return FiscalPeriod(self.fiscal_year, QUARTERS[index - 1])

    def year_ago(self) -> "FiscalPeriod":
        """1년 전 같은 기간. 계절성이 큰 사업에서 전분기 대비는 의미가 없다."""
        return FiscalPeriod(self.fiscal_year - 1, self.fiscal_period)


def parse_period(value: object) -> str:
    """공시가 말한 기간 표기를 우리 표기로. 모르면 예외 — 추측하지 않는다."""
    text = str(value or "").strip().upper()
    if text in FISCAL_PERIODS:
        return text
    # SEC은 연간을 'FY'로도 'Q4'로도 쓰지 않고 빈 값으로 두는 일이 있다.
    if text in {"ANNUAL", "YEAR", "A"}:
        return "FY"
    raise PeriodError(f"unknown fiscal period: {value!r}")


def trailing_quarters(latest: FiscalPeriod, count: int) -> list[FiscalPeriod]:
    """최근 분기부터 거슬러 `count`개. 카드의 추세 차트가 쓰는 구간이다."""
    if latest.is_annual:
        raise PeriodError("trailing_quarters needs a quarterly period")
    if count < 1:
        raise PeriodError("count must be >= 1")
    periods = [latest]
    while len(periods) < count:
        periods.append(periods[-1].previous_quarter())
    return list(reversed(periods))


def derive_fourth_quarter(
    annual: float | None, quarters: Sequence[float | None]
) -> float | None:
    """FY에서 Q1~Q3를 빼 Q4를 만든다. 하나라도 없으면 `None`.

    **부분합으로 채우지 않는다.** Q1과 Q2만 있는데 빼면 Q4가 실제보다 크게 나오고,
    그 값은 예외 없이 추세 차트에 실린다. 모르는 것은 모른다고 두는 편이 낫다.
    """
    if annual is None or len(quarters) != 3 or any(value is None for value in quarters):
        return None
    return annual - sum(float(value) for value in quarters)  # type: ignore[arg-type]


def period_end_is_plausible(period_end: date, filing_date: date) -> bool:
    """회계기간말이 공시일보다 뒤면 그 행은 미래를 보고한 것이다.

    실제로 소스가 연도를 잘못 붙여 보내는 일이 있고, 그 행은 PIT 조회에서 미래
    데이터로 새어 들어간다.
    """
    return period_end <= filing_date


def sorted_periods(periods: Iterable[FiscalPeriod]) -> list[FiscalPeriod]:
    """시간 순. `FY`는 같은 해 분기들 뒤에 온다 — 연간은 그 해가 끝나야 나온다."""
    order = {"Q1": 0, "Q2": 1, "Q3": 2, "Q4": 3, "FY": 4}
    return sorted(periods, key=lambda p: (p.fiscal_year, order[p.fiscal_period]))


__all__ = [
    "FISCAL_PERIODS",
    "FiscalPeriod",
    "PeriodError",
    "QUARTERS",
    "derive_fourth_quarter",
    "parse_period",
    "period_end_is_plausible",
    "sorted_periods",
    "trailing_quarters",
]
