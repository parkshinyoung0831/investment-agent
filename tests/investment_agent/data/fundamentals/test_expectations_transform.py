"""컨센서스 수집기의 변환 규칙을 외부 의존성 없이 검증한다."""
from __future__ import annotations

import sys
import types
import unittest
from datetime import date
from typing import ClassVar

import pandas as pd

if "supabase" not in sys.modules:
    supabase = types.ModuleType("supabase")
    supabase.Client = object
    supabase.create_client = lambda *_args, **_kwargs: None
    sys.modules["supabase"] = supabase

from investment_agent.data.fundamentals.domain.services import map_fiscal_periods as periods
from investment_agent.data.fundamentals.infrastructure.yahoo_finance import consensus as yfin

_TODAY = date(2026, 8, 15)


class _FakeTicker:
    """yfinance Ticker의 속성 접근만 흉내 낸다."""

    def __init__(self, **frames):
        self._frames = frames

    def __getattr__(self, name):
        if name not in self._frames:
            raise AttributeError(name)
        value = self._frames[name]
        if isinstance(value, Exception):
            raise value
        return value

    def get_earnings_dates(self, *, limit: int):
        del limit
        value = self._frames.get("earnings_dates")
        if isinstance(value, Exception):
            raise value
        return value


def _earnings_estimate() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "avg": [2.083, 2.352],
            "low": [2.031, 2.130],
            "high": [2.20, 2.63],
            "yearAgoEps": [1.05, 1.30],
            "numberOfAnalysts": [40, 40],
            "growth": [0.9838, 0.8095],
            "currency": ["USD", "USD"],
        },
        index=["0q", "+1q"],
    )


def _revenue_estimate() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "avg": [91_846_098_240, 103_131_206_160],
            "low": [90_302_000_000, 91_996_000_000],
            "high": [96_655_000_000, 110_657_391_000],
            "numberOfAnalysts": [42, 40],
            "yearAgoRevenue": [46_743_000_000, 57_006_000_000],
            "growth": [0.9649, 0.8091],
            "currency": ["USD", "USD"],
        },
        index=["0q", "+1q"],
    )


def _history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "epsActual": [1.62, 1.87],
            "epsEstimate": [1.53812, 1.77191],
            "epsDifference": [0.08, 0.10],
            "surprisePercent": [0.0532, 0.0554],
        },
        index=pd.to_datetime(["2026-01-31", "2026-04-30"]),
    )


def _fetch(**overrides) -> dict:
    frames = {
        "earnings_estimate": _earnings_estimate(),
        "revenue_estimate": _revenue_estimate(),
        "eps_trend": pd.DataFrame(
            {
                "current": [2.083],
                "7daysAgo": [2.083],
                "30daysAgo": [2.080],
                "60daysAgo": [2.079],
                "90daysAgo": [1.952],
                "currency": ["USD"],
            },
            index=["0q"],
        ),
        "eps_revisions": pd.DataFrame(
            {
                "upLast7days": [2],
                "upLast30days": [4],
                "downLast30days": [0],
                "downLast7Days": [0],
            },
            index=["0q"],
        ),
        "earnings_history": _history(),
        "analyst_price_targets": {
            "current": 225.16, "high": 500.0, "low": 180.0,
            "mean": 302.82758, "median": 300.0,
        },
        "recommendations": pd.DataFrame({
            "period": ["0m", "-1m"],
            "strongBuy": [10, 9], "buy": [48, 47], "hold": [2, 3],
            "sell": [1, 1], "strongSell": [0, 0],
        }),
        "upgrades_downgrades": pd.DataFrame(
            {
                "Firm": ["Keybanc", ""],
                "ToGrade": ["Overweight", "Buy"],
                "FromGrade": ["Overweight", "Buy"],
                "Action": ["main", "main"],
                "priceTargetAction": ["Raises", "Maintains"],
                "currentPriceTarget": [330.0, 270.0],
                "priorPriceTarget": [310.0, 270.0],
            },
            index=pd.to_datetime(["2026-07-14 11:17:59", "2026-06-02 16:40:48"]),
        ),
        "calendar": {"Earnings Date": [date(2026, 8, 27)]},
        "earnings_dates": None,
        "info": {"isEarningsDateEstimate": True},
    }
    frames.update(overrides)
    original = yfin._ticker
    yfin._ticker = lambda _symbol: _FakeTicker(**frames)
    try:
        return yfin.fetch_consensus("TEST", today=_TODAY)
    finally:
        yfin._ticker = original


class ConsensusSnapshots(unittest.TestCase):
    def test_horizons_and_values(self):
        """소스 라벨(0q/+1q)을 우리 horizon 어휘(q+0/q+1)로 옮겨 담는지."""
        rows = {row["horizon"]: row for row in _fetch()["snapshots"]}

        self.assertEqual(sorted(rows), ["q+0", "q+1"])
        current = rows["q+0"]
        self.assertAlmostEqual(current["eps_avg"], 2.083)
        self.assertEqual(current["eps_analysts"], 40)
        self.assertEqual(current["revenue_analysts"], 42)
        self.assertEqual(current["revisions_up_30d"], 4)
        self.assertEqual(current["snapshot_date"], "2026-08-15")
        self.assertNotIn("currency", current)

    def test_target_period_is_projected_from_last_reported_quarter(self):
        """직전 보고 분기말 2026-04-30 → q+0은 07-31, q+1은 10-31."""
        rows = {row["horizon"]: row for row in _fetch()["snapshots"]}

        self.assertEqual(rows["q+0"]["target_period_end"], "2026-07-31")
        self.assertEqual(rows["q+1"]["target_period_end"], "2026-10-31")

    def test_expected_report_date_ignores_past_dates(self):
        """Yahoo가 지난 발표일을 그대로 두는 종목이 있어 미래 날짜만 채택한다."""
        stale = _fetch(calendar={"Earnings Date": [date(2026, 7, 30)]})
        self.assertIsNone(stale["snapshots"][0]["expected_report_date"])

        fresh = _fetch()
        self.assertEqual(fresh["snapshots"][0]["expected_report_date"], "2026-08-27")

    def test_missing_frames_do_not_break_collection(self):
        result = _fetch(
            revenue_estimate=None,
            eps_revisions=None,
            analyst_price_targets={},
            upgrades_downgrades=None,
        )

        self.assertTrue(result["snapshots"])
        self.assertIsNone(result["snapshots"][0]["revenue_avg"])
        self.assertIsNotNone(result["analyst_snapshot"])

    def test_provider_exception_is_visible_with_partial_rows(self):
        result = _fetch(revenue_estimate=RuntimeError("endpoint unavailable"))

        self.assertTrue(result["snapshots"])
        self.assertIn(
            "revenue_estimate",
            {failure["stage"] for failure in result["source_failures"]},
        )


class TrendSeed(unittest.TestCase):
    def test_seed_rows_are_backdated(self):
        seeds = {row["snapshot_date"]: row for row in _fetch()["trend_seed"]}

        self.assertEqual(
            sorted(seeds),
            ["2026-05-17", "2026-06-16", "2026-07-16", "2026-08-08"],
        )
        self.assertAlmostEqual(seeds["2026-05-17"]["eps_avg"], 1.952)
        self.assertEqual(seeds["2026-05-17"]["source"], "yfinance:eps_trend")


class AnalystSnapshot(unittest.TestCase):
    def test_reported_surprises_are_not_collected(self):
        """발표 결과 bucket은 소비자가 없어 수집하지 않는다.

        조정 EPS를 company_financials에 병합하지 않으며, 서프라이즈는
        reporting.earnings_surprise가 earnings_estimates를 시점 조인해 계산한다.
        """
        self.assertNotIn("surprises", _fetch())

    def test_analyst_snapshot_uses_current_recommendation_only(self):
        rec = _fetch()["analyst_snapshot"]

        self.assertEqual(rec["strong_buy"], 10)
        self.assertEqual(rec["hold"], 2)
        self.assertNotIn("currency", rec)
        self.assertNotIn("price_current", rec)


class FiscalPeriodNormalization(unittest.TestCase):
    _CALENDAR: ClassVar[list[dict]] = [
        {"ticker": "TEST", "fiscal_year": 2026, "fiscal_period": "Q1", "period_end": "2026-01-31"},
        {"ticker": "TEST", "fiscal_year": 2026, "fiscal_period": "Q2", "period_end": "2026-04-30"},
    ]

    def test_quarter_and_year_horizons_become_readable_fiscal_keys(self):
        raw = _fetch()["snapshots"] + [{
            "ticker": "TEST", "snapshot_date": "2026-08-15", "horizon": "fy+0",
            "eps_avg": 8.0,
        }]
        consensus, schedules, unmapped = periods.normalize_consensus(
            raw, self._CALENDAR, collected_on=_TODAY,
        )
        by_horizon = {row["source_horizon"]: row for row in consensus}

        self.assertEqual(unmapped, [])
        self.assertEqual(by_horizon["q+0"]["target_fiscal_period"], "Q3")
        self.assertEqual(by_horizon["q+0"]["target_fiscal_year"], 2026)
        self.assertEqual(by_horizon["fy+0"]["target_fiscal_period"], "FY")
        self.assertEqual(by_horizon["fy+0"]["target_fiscal_year"], 2026)
        self.assertEqual(len(schedules), 1)
        # 저장하는 사실은 시각 하나다. 발표일은 DB 생성 컬럼이 ET 기준으로 파생한다.
        self.assertNotIn("expected_report_date", schedules[0])
        self.assertTrue(schedules[0]["expected_report_at"].startswith("2026-08-27"))

    def test_reconstructed_seed_is_marked_and_never_masquerades_as_observed(self):
        consensus, _, unmapped = periods.normalize_consensus(
            _fetch()["trend_seed"], self._CALENDAR, collected_on=_TODAY,
        )

        self.assertEqual(unmapped, [])
        self.assertTrue(consensus)
        self.assertEqual({row["snapshot_kind"] for row in consensus}, {"reconstructed"})

    def test_missing_yahoo_target_uses_the_next_reported_fiscal_quarter(self):
        raw = [{**_fetch()["snapshots"][0], "target_period_end": None}]
        consensus, schedules, unmapped = periods.normalize_consensus(
            raw, self._CALENDAR, collected_on=_TODAY,
        )

        self.assertEqual(unmapped, [])
        self.assertEqual(consensus[0]["target_fiscal_period"], "Q3")
        self.assertEqual(consensus[0]["target_fiscal_year"], 2026)
        self.assertEqual(len(schedules), 1)

    def test_schedule_is_saved_even_when_consensus_frames_are_empty(self):
        result = _fetch(
            earnings_estimate=None,
            revenue_estimate=None,
            eps_trend=None,
            eps_revisions=None,
        )
        consensus, schedules, unmapped = periods.normalize_consensus(
            result["snapshots"], self._CALENDAR, collected_on=_TODAY,
        )

        self.assertEqual(unmapped, [])
        self.assertEqual(consensus, [])
        self.assertEqual(len(schedules), 1)
        self.assertEqual(schedules[0]["target_fiscal_period"], "Q3")

    def test_schedule_before_target_period_end_is_rejected(self):
        raw = [{
            **_fetch()["snapshots"][0],
            "target_period_end": "2026-10-31",
            "expected_report_date": "2026-08-20",
        }]
        _, schedules, unmapped = periods.normalize_consensus(
            raw, self._CALENDAR, collected_on=_TODAY,
        )

        self.assertEqual(unmapped, [])
        self.assertEqual(schedules, [])


if __name__ == "__main__":
    unittest.main()
