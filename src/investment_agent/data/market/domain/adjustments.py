"""분할·배당으로 과거 가격을 조정한다.

## 왜 저장하지 않고 계산하는가

조정가를 저장하면 **분할이 하나 새로 들어올 때마다 과거 행 전체를 다시 써야 한다.**
그 재작성이 실패하거나 일부만 되면, 같은 표 안에 서로 다른 규칙으로 만들어진 값이
섞이는데 그것을 구분할 방법이 없다. 그래서 저장소는 관측한 값만 담고, 조정은 필요한
쪽이 그 시점의 규칙으로 만든다.

## 되돌아보는 조정(back-adjustment)이다

**최신 가격이 기준**이고 과거를 그쪽으로 맞춘다. 반대로 하면 오늘 가격이 어제와
달라져 화면과 알림이 실제와 다른 수를 말하게 된다.

## 배당 조정은 선택이다

가격 수익률만 볼 때는 분할만 조정한다. 총수익(배당 재투자)을 볼 때만 배당을 넣는다.
둘을 섞으면 "이 종목이 얼마나 올랐나"에 두 가지 답이 생기는데, 어느 쪽인지 표시가
없으면 비교가 조용히 틀린다.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Iterable, Sequence

from investment_agent.data.market.domain.models import DailyBar, DividendEvent, SplitEvent


def split_factors(
    bars: Sequence[DailyBar], splits: Iterable[SplitEvent]
) -> dict[date, float]:
    """거래일마다 곱할 분할 계수.

    분할 당일(`action_date`)의 가격은 이미 분할 후 가격이다. 따라서 조정 대상은
    **그 전날까지**다. 경계를 하루 잘못 잡으면 분할일 하나가 몇십 퍼센트 점프로
    보이고, 그 점프는 수익률 계산에 그대로 들어간다.
    """
    if not bars:
        return {}
    ordered = sorted(splits, key=lambda event: event.action_date)
    factors: dict[date, float] = {}
    factor = 1.0
    # 뒤에서 앞으로 걸으며, 아직 겪지 않은 분할을 누적한다.
    for bar in sorted(bars, key=lambda item: item.trade_date, reverse=True):
        while ordered and ordered[-1].action_date > bar.trade_date:
            factor /= ordered.pop().split_ratio
        factors[bar.trade_date] = factor
    return factors


def dividend_factors(
    bars: Sequence[DailyBar], dividends: Iterable[DividendEvent]
) -> dict[date, float]:
    """거래일마다 곱할 배당 계수(총수익 기준).

    배당락일 전날 종가를 기준으로 `1 - 배당/종가`를 누적한다. 종가를 모르면 그 배당은
    건너뛴다 — 임의의 값을 넣으면 그 종목만 조용히 다른 수익률을 갖게 된다.
    """
    if not bars:
        return {}
    by_date = {bar.trade_date: bar for bar in bars}
    ordered_dates = sorted(by_date)
    ordered = sorted(dividends, key=lambda event: event.ex_date)

    factors: dict[date, float] = {}
    factor = 1.0
    for trade_date in reversed(ordered_dates):
        while ordered and ordered[-1].ex_date > trade_date:
            event = ordered.pop()
            previous = _previous_close(by_date, ordered_dates, event.ex_date)
            if previous is None or previous <= 0 or event.div_amount <= 0:
                continue
            ratio = 1.0 - event.div_amount / previous
            # 배당이 종가보다 크면 계수가 0 이하가 된다. 데이터 오류이므로 무시한다.
            if ratio > 0:
                factor *= ratio
        factors[trade_date] = factor
    return factors


def _previous_close(
    by_date: dict[date, DailyBar], ordered_dates: list[date], ex_date: date
) -> float | None:
    """배당락일 **직전 거래일**의 종가. 휴장을 건너뛰어야 하므로 목록을 거슬러 찾는다."""
    for trade_date in reversed(ordered_dates):
        if trade_date < ex_date:
            return by_date[trade_date].close
    return None


def adjust(
    bars: Sequence[DailyBar],
    *,
    splits: Iterable[SplitEvent] = (),
    dividends: Iterable[DividendEvent] | None = None,
) -> list[DailyBar]:
    """조정된 봉을 새로 만든다. 원본은 건드리지 않는다.

    `dividends`를 주지 않으면 **가격 수익률**(분할만 조정), 주면 **총수익**이다.
    부르는 쪽이 무엇을 보고 있는지 인자에 드러나게 했다.
    """
    if not bars:
        return []
    splits_by_date = split_factors(bars, splits)
    dividends_by_date = dividend_factors(bars, dividends or ()) if dividends is not None else {}

    adjusted: list[DailyBar] = []
    for bar in sorted(bars, key=lambda item: item.trade_date):
        factor = splits_by_date.get(bar.trade_date, 1.0) * dividends_by_date.get(bar.trade_date, 1.0)
        if factor == 1.0:
            adjusted.append(bar)
            continue
        adjusted.append(replace(
            bar,
            open=bar.open * factor,
            high=bar.high * factor,
            low=bar.low * factor,
            close=bar.close * factor,
            # 분할하면 주식 수가 늘어 거래량도 함께 변한다. 가격만 조정하면
            # 거래대금(가격×거래량)이 분할 전후로 어긋난다.
            volume=int(round(bar.volume / splits_by_date.get(bar.trade_date, 1.0))),
        ))
    return adjusted


__all__ = ["adjust", "dividend_factors", "split_factors"]
