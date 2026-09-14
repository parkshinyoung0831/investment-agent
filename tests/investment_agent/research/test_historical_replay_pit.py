"""과거 재현 학습이 조용히 부풀거나 비지 않게 하는 시점·단위 계약."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from investment_agent.data.market.domain.calendar import bar_available_at
from investment_agent.research.commands.build_labels import _label_symbols
from investment_agent.research.commands.build_valuations import build_valuations
from investment_agent.research.datasets.universe import research_universe
from investment_agent.research.features.layer import _close_returns, _fundamental
from investment_agent.research.valuation.inputs import price_scalar, shares_scalar
from investment_agent.trading.evidence.tools import fundamental_statistics


class PriceAvailabilityTest(unittest.TestCase):
    def test_bar_without_ingestion_time_is_usable_after_new_york_finalization(self):
        # 2026-08-20 18:00 EDT = 22:00 UTC
        self.assertEqual(bar_available_at("2026-08-20"), datetime(2026, 8, 20, 22, tzinfo=timezone.utc))
        self.assertEqual(
            bar_available_at("2026-08-20", "2026-08-21T01:00:00+00:00"),
            datetime(2026, 8, 21, 1, tzinfo=timezone.utc),
        )

    def test_valuation_price_does_not_require_an_ingestion_timestamp(self):
        """가격 저장소의 봉에는 적재 시각이 없다. 그것을 요구하면 모든 시가총액이 빈다."""
        rows = [
            {"ticker": "AAA", "trade_date": "2026-08-18", "close": 40.0},
            {"ticker": "AAA", "trade_date": "2026-08-19", "close": 45.0},
            {"ticker": "AAA", "trade_date": "2026-08-20", "close": 50.0},
        ]
        before_close = price_scalar(rows, as_of_at=datetime(2026, 8, 20, 21, tzinfo=timezone.utc))
        after_close = price_scalar(rows, as_of_at=datetime(2026, 8, 20, 22, tzinfo=timezone.utc))
        # 오름차순으로 와도 cutoff에 확정된 **가장 최근** 종가를 고른다.
        self.assertEqual(float(before_close.value), 45.0)
        self.assertEqual(float(after_close.value), 50.0)


class SplitBasisTest(unittest.TestCase):
    """저장 종가는 이미 현재 분할 기준이다(market이 새 분할마다 전체 이력을 다시 받는다)."""

    def test_feature_returns_use_stored_split_normalized_closes_as_is(self):
        # NVDA 2024-06-10 10:1 분할 전후의 실제 저장값: 분할일에 점프가 없다.
        rows = [{"trade_date": f"2024-06-{day:02d}", "close": close, "split_ratio": ratio}
                for day, close, ratio in ((7, 120.89, None), (10, 121.79, 10.0))]
        rows += [{"trade_date": f"2024-05-{day:02d}", "close": 120.0} for day in range(1, 22)]
        returns = _close_returns(rows)
        self.assertAlmostEqual(returns["price_return_1d"], 121.79 / 120.89 - 1.0)

    def test_historical_share_count_is_restated_to_the_price_split_basis(self):
        """2021년 공시 주식 수에 이후 4:1·10:1 분할을 곱해야 분할 기준 종가와 시가총액이 맞는다."""
        splits = [
            {"action_date": "2021-07-20", "split_ratio": 4.0},
            {"action_date": "2024-06-10", "split_ratio": 10.0},
            {"action_date": "2020-01-01", "split_ratio": 2.0},
        ]
        share_rows = [{
            "shares_outstanding": 620_000_000, "accession_no": "0001045810-21-000078",
            "share_class_key": "common", "as_of_date": "2021-05-19", "filed_at": "2021-05-26",
            "accepted_at": "2021-05-26T20:00:00+00:00",
        }]
        scalar = shares_scalar(
            share_rows, as_of_at=datetime(2021, 6, 30, 22, tzinfo=timezone.utc), split_rows=splits,
        )
        # 표지 기준일 이후 분할만 곱한다(2020년 분할은 이미 주식 수에 들어 있다).
        self.assertEqual(float(scalar.value), 620_000_000 * 40)
        self.assertEqual(float(shares_scalar(share_rows, as_of_at=datetime(2021, 6, 30, tzinfo=timezone.utc)).value),
                         620_000_000)


class FundamentalGrowthTest(unittest.TestCase):
    def test_growth_is_year_over_year_for_the_same_fiscal_period(self):
        rows = [
            {"fiscal_year": 2026, "fiscal_period": "Q1", "revenue": 110.0, "net_income": 12.0},
            {"fiscal_year": 2025, "fiscal_period": "Q4", "revenue": 200.0, "net_income": 40.0},
            {"fiscal_year": 2025, "fiscal_period": "Q3", "revenue": 100.0, "net_income": 10.0},
            {"fiscal_year": 2025, "fiscal_period": "Q2", "revenue": 100.0, "net_income": 10.0},
            {"fiscal_year": 2025, "fiscal_period": "Q1", "revenue": 100.0, "net_income": 10.0},
        ]
        stats = fundamental_statistics(rows)
        features = _fundamental({"statistics": stats, "filings": rows[:4]})
        # 직전 분기(Q4 계절 매출) 대비 -45%가 아니라 전년 같은 분기 대비 +10%다.
        self.assertAlmostEqual(features["fundamental_revenue_growth"], 0.10)
        self.assertAlmostEqual(features["fundamental_net_income_growth"], 0.20)

    def test_loss_to_profit_growth_keeps_the_improvement_positive(self):
        rows = [
            {"fiscal_year": 2026, "fiscal_period": "Q1", "revenue": 100.0, "net_income": 5.0},
            {"fiscal_year": 2025, "fiscal_period": "Q1", "revenue": 100.0, "net_income": -5.0},
        ]
        self.assertAlmostEqual(fundamental_statistics(rows)["net_income_growth_yoy"], 2.0)


class _MembershipRepository:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.calls = []

    def current_tracked_tickers(self):
        return ["AAPL", "NVDA"]

    def historical_sp500_membership(self, *, start_date, end_date):
        self.calls.append((start_date, end_date))
        return self.snapshots


class ReplayUniverseTest(unittest.TestCase):
    def test_historical_replay_uses_the_members_of_that_new_york_day(self):
        repository = _MembershipRepository([{"symbols": ["AAPL", "OLD"]}])
        # 2016-03-01 02:00 UTC는 뉴욕 2월 29일이다.
        members = research_universe(
            repository, as_of_at=datetime(2016, 3, 1, 2, tzinfo=timezone.utc), source_kind="historical_replay",
        )
        self.assertEqual(members, ["AAPL", "OLD"])
        self.assertEqual(repository.calls, [(date(2016, 2, 29), date(2016, 2, 29))])

    def test_missing_membership_does_not_fall_back_to_todays_survivors(self):
        with self.assertRaises(RuntimeError):
            research_universe(
                _MembershipRepository([]), as_of_at=datetime(2016, 3, 1, tzinfo=timezone.utc),
                source_kind="historical_replay",
            )

    def test_labels_cover_members_that_left_during_the_window(self):
        repository = _MembershipRepository([{"symbols": ["AAPL", "GONE"]}, {"symbols": ["AAPL", "NEW"]}])
        symbols = _label_symbols(repository, start=date(2026, 6, 1), end=date(2026, 9, 1))
        self.assertEqual(symbols, ("AAPL", "GONE", "NEW", "NVDA"))


class _ValuationRepository:
    def __init__(self):
        self.saved = []

    def market_prices(self, ticker, as_of_at, limit=260):
        return [{"ticker": ticker, "trade_date": "2016-02-26", "close": 50.0}]

    def fundamentals_pit(self, ticker, as_of_at, limit=12):
        return []

    def share_class_snapshots_pit(self, ticker, as_of_at, limit=24):
        return []

    def save_valuation_observations(self, rows):
        self.saved.extend(rows)


class HistoricalValuationTest(unittest.TestCase):
    def test_source_kind_is_recorded_as_historical_replay(self):
        repository = _ValuationRepository()
        build_valuations(
            as_of_at=datetime(2016, 2, 29, 23, tzinfo=timezone.utc), tickers=["AAA"],
            source_kind="historical_replay", repository=repository,
        )
        self.assertEqual(repository.saved[0]["source_kind"], "historical_replay")
        self.assertEqual(repository.saved[0]["price"], 50.0)

    def test_entry_restates_shares_with_the_market_split_history(self):
        repository = _ValuationRepository()
        repository.share_class_snapshots_pit = lambda ticker, as_of_at, limit=24: [{
            "shares_outstanding": 100, "accession_no": "0000000001-16-000001", "share_class_key": "common",
            "as_of_date": "2016-01-15", "filed_at": "2016-01-20", "accepted_at": "2016-01-20T20:00:00+00:00",
        }]
        repository.split_history = lambda ticker: [{"action_date": "2020-08-31", "split_ratio": 4.0}]
        build_valuations(
            as_of_at=datetime(2016, 2, 29, 23, tzinfo=timezone.utc), tickers=["AAA"],
            source_kind="historical_replay", repository=repository,
        )
        self.assertEqual(repository.saved[0]["shares_outstanding"], 400.0)
        self.assertEqual(repository.saved[0]["market_cap"], 20000.0)

    def test_unknown_source_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            build_valuations(
                as_of_at=datetime(2016, 2, 29, tzinfo=timezone.utc), tickers=["AAA"],
                source_kind="backtest", repository=_ValuationRepository(),
            )


if __name__ == "__main__":
    unittest.main()
