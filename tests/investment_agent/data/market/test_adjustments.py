"""분할·배당 조정이 경계를 하루도 어긋나지 않아야 한다."""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.data.market.domain.adjustments import adjust, split_factors
from investment_agent.data.market.domain.models import DailyBar, DividendEvent, SplitEvent


def _bar(day: int, close: float, volume: int = 1000) -> DailyBar:
    return DailyBar(
        security_id=1,
        trade_date=date(2026, 9, day),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=volume,
    )


class SplitAdjustmentTest(unittest.TestCase):
    def setUp(self) -> None:
        # 9/3까지 400달러, 9/4에 4:1 분할로 100달러.
        self.bars = [_bar(2, 400.0), _bar(3, 400.0), _bar(4, 100.0), _bar(7, 102.0)]
        self.split = SplitEvent(security_id=1, action_date=date(2026, 9, 4), split_ratio=4.0)

    def test_prices_before_the_split_are_scaled_down(self) -> None:
        by_date = {bar.trade_date: bar for bar in adjust(self.bars, splits=[self.split])}
        self.assertAlmostEqual(100.0, by_date[date(2026, 9, 3)].close)

    def test_the_split_day_itself_is_already_post_split(self) -> None:
        """경계를 하루 잘못 잡으면 분할일이 몇십 퍼센트 점프로 보인다."""
        by_date = {bar.trade_date: bar for bar in adjust(self.bars, splits=[self.split])}
        self.assertAlmostEqual(100.0, by_date[date(2026, 9, 4)].close)

    def test_prices_after_the_split_are_untouched(self) -> None:
        """최신 가격이 기준이다. 오늘 값이 달라지면 화면이 실제와 다른 수를 말한다."""
        by_date = {bar.trade_date: bar for bar in adjust(self.bars, splits=[self.split])}
        self.assertAlmostEqual(102.0, by_date[date(2026, 9, 7)].close)

    def test_the_series_has_no_jump_at_the_split(self) -> None:
        closes = [bar.close for bar in adjust(self.bars, splits=[self.split])]
        for previous, current in zip(closes, closes[1:]):
            self.assertLess(abs(current / previous - 1), 0.10)

    def test_volume_moves_the_other_way(self) -> None:
        """가격만 조정하면 거래대금이 분할 전후로 어긋난다."""
        by_date = {bar.trade_date: bar for bar in adjust(self.bars, splits=[self.split])}
        self.assertEqual(4000, by_date[date(2026, 9, 3)].volume)
        self.assertEqual(1000, by_date[date(2026, 9, 7)].volume)

    def test_two_splits_compound(self) -> None:
        second = SplitEvent(security_id=1, action_date=date(2026, 9, 7), split_ratio=2.0)
        factors = split_factors(self.bars, [self.split, second])
        self.assertAlmostEqual(1 / 8, factors[date(2026, 9, 3)])
        self.assertAlmostEqual(1 / 2, factors[date(2026, 9, 4)])
        self.assertAlmostEqual(1.0, factors[date(2026, 9, 7)])

    def test_no_splits_leaves_the_bars_alone(self) -> None:
        self.assertEqual(self.bars, adjust(self.bars))

    def test_empty_input_is_empty_output(self) -> None:
        self.assertEqual([], adjust([], splits=[self.split]))


class DividendAdjustmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.bars = [_bar(2, 100.0), _bar(3, 100.0), _bar(4, 99.0), _bar(7, 99.0)]
        self.dividend = DividendEvent(security_id=1, ex_date=date(2026, 9, 4), div_amount=1.0)

    def test_dividends_are_ignored_unless_asked_for(self) -> None:
        """가격 수익률과 총수익을 섞으면 '얼마나 올랐나'에 답이 둘 생긴다."""
        self.assertEqual(self.bars, adjust(self.bars))

    def test_prices_before_the_ex_date_are_scaled_by_the_yield(self) -> None:
        by_date = {bar.trade_date: bar for bar in adjust(self.bars, dividends=[self.dividend])}
        self.assertAlmostEqual(99.0, by_date[date(2026, 9, 3)].close)

    def test_the_ex_date_itself_already_dropped(self) -> None:
        by_date = {bar.trade_date: bar for bar in adjust(self.bars, dividends=[self.dividend])}
        self.assertAlmostEqual(99.0, by_date[date(2026, 9, 4)].close)

    def test_a_dividend_bigger_than_the_price_is_ignored(self) -> None:
        """계수가 0 이하가 되면 그 뒤 값이 전부 무의미해진다. 데이터 오류로 본다."""
        broken = DividendEvent(security_id=1, ex_date=date(2026, 9, 4), div_amount=500.0)
        by_date = {bar.trade_date: bar for bar in adjust(self.bars, dividends=[broken])}
        self.assertAlmostEqual(100.0, by_date[date(2026, 9, 3)].close)

    def test_a_dividend_before_every_bar_is_ignored(self) -> None:
        """직전 종가를 모르면 임의의 값을 넣지 않는다."""
        early = DividendEvent(security_id=1, ex_date=date(2026, 8, 1), div_amount=1.0)
        self.assertEqual(
            [bar.close for bar in self.bars],
            [bar.close for bar in adjust(self.bars, dividends=[early])],
        )

    def test_dividends_and_splits_compose(self) -> None:
        split = SplitEvent(security_id=1, action_date=date(2026, 9, 4), split_ratio=2.0)
        by_date = {
            bar.trade_date: bar
            for bar in adjust(self.bars, splits=[split], dividends=[self.dividend])
        }
        # 분할 0.5 × 배당 0.99 = 0.495
        self.assertAlmostEqual(49.5, by_date[date(2026, 9, 3)].close)


if __name__ == "__main__":
    unittest.main()
