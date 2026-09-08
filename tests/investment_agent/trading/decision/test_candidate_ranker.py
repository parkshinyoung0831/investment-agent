"""S&P 500 후보 랭커의 coverage·시점·다중 도메인 규칙을 검증한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from investment_agent.trading.decision.candidate_ranker import (
    CandidateFeatures,
    assemble_candidate_features,
    rank_candidate_features,
    validate_live_candidate_as_of,
)
from investment_agent.trading.supabase_repository import (
    SupabaseRepository,
    _guru_candidate_signals,
    _segment_candidate_signals,
)
from investment_agent.trading.decision import portfolio_shadow, shadow_daily

_AS_OF = datetime(2026, 8, 21, 21, 0, tzinfo=timezone.utc)


def _feature(ticker: str, magnitude: float, *, last=None) -> CandidateFeatures:
    return CandidateFeatures(
        ticker=ticker,
        last_analyzed_at=last,
        return_20d=magnitude,
        volume_ratio_20d=1 + magnitude,
        rsi14=50 + 40 * magnitude,
        macd_spread_pct=magnitude / 10,
        revenue_growth_yoy=magnitude,
        operating_margin=magnitude,
        segment_concentration=min(1.0, magnitude),
        segment_quality=min(1.0, magnitude),
        guru_holder_count=10 * magnitude,
        guru_new_buy_count=magnitude,
        guru_add_count=magnitude,
        guru_hold_count=magnitude,
        guru_reduce_count=0.0,
        guru_exit_count=0.0,
        guru_total_value_usd=1_000_000 * magnitude,
        guru_avg_quantity_change_pct=10 * magnitude,
        guru_max_weight_pct=20 * magnitude,
        guru_consensus="accumulating",
    )


class CandidateAssemblyTest(unittest.TestCase):
    def test_assembles_five_domains_from_point_in_time_rows(self):
        market = [
            {
                "ticker": "AAPL",
                "trade_date": f"2026-07-{day:02d}",
                "close": 100 + day,
                "volume": 100,
            }
            for day in range(1, 22)
        ]
        market[-1]["volume"] = 200
        rows = assemble_candidate_features(
            ["AAPL"],
            last_analyzed_at={"AAPL": "2026-08-20T21:00:00+00:00"},
            market_rows=market,
            technical_rows=[{
                "ticker": "AAPL",
                "trade_date": "2026-08-21",
                "ingested_at": "2026-08-21T20:00:00+00:00",
                "rsi14": 72,
                "macd": 3,
                "macd_signal": 2,
            }],
            fundamental_rows=[
                {
                    "ticker": "AAPL", "fiscal_year": 2026, "fiscal_period": "Q2",
                    "filed_at": "2026-08-01", "period_end": "2026-06-30",
                    "revenue": 120, "operating_income_loss": 24,
                },
                {
                    "ticker": "AAPL", "fiscal_year": 2025, "fiscal_period": "Q2",
                    "filed_at": "2025-08-01", "period_end": "2025-06-30",
                    "revenue": 100, "operating_income_loss": 10,
                },
            ],
            segment_signals={"AAPL": {"concentration": 0.6, "quality": 0.9}},
            guru_signals={"AAPL": {
                "holder_count": 3,
                "new_buy_count": 1,
                "add_count": 2,
                "hold_count": 1,
                "reduce_count": 0,
                "exit_count": 0,
                "total_value_usd": 50_000,
                "avg_quantity_change_pct": 25,
                "max_weight_pct": 12.5,
                "consensus": "accumulating",
            }},
        )
        self.assertEqual(len(rows), 1)
        feature = rows[0]
        self.assertAlmostEqual(feature.return_20d, 121 / 101 - 1)
        self.assertAlmostEqual(feature.volume_ratio_20d, 2.0)
        self.assertEqual(feature.rsi14, 72)
        self.assertAlmostEqual(feature.macd_spread_pct, 1 / 121)
        self.assertAlmostEqual(feature.revenue_growth_yoy, 0.2)
        self.assertAlmostEqual(feature.operating_margin, 0.2)
        self.assertEqual(feature.segment_quality, 0.9)
        self.assertEqual(feature.guru_holder_count, 3)
        self.assertEqual(feature.guru_new_buy_count, 1)
        self.assertEqual(feature.guru_total_value_usd, 50_000)
        self.assertEqual(feature.guru_consensus, "accumulating")


class CandidateRankingTest(unittest.TestCase):
    def test_never_analyzed_precedes_recent_high_score(self):
        ranking = rank_candidate_features(
            [
                _feature("RECENT", 1.0, last=_AS_OF - timedelta(hours=1)),
                _feature("NEW", 0.01),
            ],
            as_of_at=_AS_OF,
            limit=1,
        )
        self.assertEqual(ranking[0].ticker, "NEW")

    def test_bullish_and_bearish_extremes_both_precede_quiet_name(self):
        ranking = rank_candidate_features(
            [
                _feature("QUIET", 0.01),
                _feature("BULL", 0.8),
                CandidateFeatures(
                    ticker="BEAR",
                    return_20d=-0.7,
                    volume_ratio_20d=0.3,
                    rsi14=15,
                    macd_spread_pct=-0.08,
                    revenue_growth_yoy=-0.6,
                    operating_margin=-0.4,
                    segment_concentration=0.9,
                    segment_quality=0.9,
                    guru_holder_count=5,
                    guru_new_buy_count=0,
                    guru_add_count=0,
                    guru_hold_count=1,
                    guru_reduce_count=3,
                    guru_exit_count=2,
                    guru_total_value_usd=900_000,
                    guru_avg_quantity_change_pct=-35,
                    guru_max_weight_pct=15,
                    guru_consensus="distributing",
                ),
            ],
            as_of_at=_AS_OF,
            limit=3,
        )
        self.assertEqual({row.ticker for row in ranking[:2]}, {"BULL", "BEAR"})
        self.assertEqual(ranking[-1].ticker, "QUIET")

    def test_every_member_is_covered_before_any_repeat(self):
        features = {
            f"T{i:02d}": _feature(f"T{i:02d}", (i + 1) / 20)
            for i in range(12)
        }
        selected: list[str] = []
        for batch_index in range(4):
            ranking = rank_candidate_features(
                list(features.values()),
                as_of_at=_AS_OF + timedelta(days=batch_index),
                limit=3,
            )
            for row in ranking:
                selected.append(row.ticker)
                original = features[row.ticker]
                features[row.ticker] = CandidateFeatures(
                    **{
                        **original.__dict__,
                        "last_analyzed_at": _AS_OF + timedelta(days=batch_index),
                    }
                )
        self.assertEqual(len(selected), 12)
        self.assertEqual(len(set(selected)), 12)

    def test_future_coverage_history_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "exceeds"):
            rank_candidate_features(
                [_feature("AAPL", 0.5, last=_AS_OF + timedelta(seconds=1))],
                as_of_at=_AS_OF,
                limit=1,
            )

    def test_ties_are_deterministic_by_ticker(self):
        ranking = rank_candidate_features(
            [_feature("MSFT", 0.5), _feature("AAPL", 0.5)],
            as_of_at=_AS_OF,
            limit=2,
        )
        self.assertEqual([row.ticker for row in ranking], ["AAPL", "MSFT"])


class CandidateLiveCutoffTest(unittest.TestCase):
    def test_recent_cutoff_is_allowed(self):
        result = validate_live_candidate_as_of(
            _AS_OF - timedelta(hours=23), now_at=_AS_OF
        )
        self.assertEqual(result, _AS_OF - timedelta(hours=23))

    def test_historical_cutoff_fails_before_database_read(self):
        with self.assertRaisesRegex(ValueError, "live-only"):
            validate_live_candidate_as_of(
                _AS_OF - timedelta(hours=24, seconds=1), now_at=_AS_OF
            )

    def test_future_cutoff_beyond_clock_skew_fails(self):
        with self.assertRaisesRegex(ValueError, "future"):
            validate_live_candidate_as_of(
                _AS_OF + timedelta(minutes=6), now_at=_AS_OF
            )

    def test_legacy_shadow_explicit_ticker_cannot_bypass_live_cutoff(self):
        with mock.patch.object(shadow_daily, "SupabaseRepository") as repository:
            with self.assertRaisesRegex(ValueError, "live-only"):
                shadow_daily.main([
                    "--ticker", "AAPL", "--as-of", "2020-01-01T00:00:00+00:00",
                    "--dry-run",
                ])
        repository.assert_not_called()

    def test_tradingagents_explicit_ticker_cannot_bypass_live_cutoff(self):
        with mock.patch.object(portfolio_shadow, "SupabaseRepository") as repository:
            with self.assertRaisesRegex(ValueError, "live-only"):
                portfolio_shadow.main([
                    "--ticker", "AAPL", "--as-of", "2020-01-01T00:00:00+00:00",
                    "--dry-run",
                ])
        repository.assert_not_called()


class CandidateDomainSummaryTest(unittest.TestCase):
    def test_repository_loads_segment_signals_from_fundamentals_owner(self):
        repository = SupabaseRepository()
        with mock.patch(
            "investment_agent.trading.supabase_repository.fundamentals_segments"
        ) as segments:
            segments.segment_snapshots_as_of.return_value = {
                "AAPL": {
                    "filings": [
                        {"ticker": "AAPL", "accession_no": "new", "filing_date": "2026-01-01"}
                    ],
                    "metrics": [
                        {
                            "ticker": "AAPL",
                            "accession_no": "new",
                            "segment_type": "business",
                            "axis": "core",
                            "revenue": 100,
                            "coverage_ratio": 1,
                            "quality_status": "verified",
                        }
                    ],
                }
            }

            result = repository._candidate_segment_signals(("AAPL",), _AS_OF)

        self.assertEqual(result["AAPL"]["concentration"], 1.0)
        self.assertEqual(result["AAPL"]["quality"], 1.0)
        # 종목 수와 무관하게 한 번이다 — 종목마다 부르면 왕복이 종목 수에 붙는다.
        segments.segment_snapshots_as_of.assert_called_once_with(["AAPL"], _AS_OF)

    def test_segment_summary_uses_latest_parsed_accession(self):
        result = _segment_candidate_signals(
            [
                {"ticker": "AAPL", "accession_no": "old", "filing_date": "2025-01-01"},
                {"ticker": "AAPL", "accession_no": "new", "filing_date": "2026-01-01"},
            ],
            [
                {
                    "accession_no": "old", "segment_type": "business", "axis": "old",
                    "revenue": 100, "coverage_ratio": 1, "quality_status": "verified",
                },
                {
                    "accession_no": "new", "segment_type": "business", "axis": "core",
                    "revenue": 75, "coverage_ratio": 1, "quality_status": "verified",
                },
                {
                    "accession_no": "new", "segment_type": "business", "axis": "core",
                    "revenue": 25, "coverage_ratio": 1, "quality_status": "verified",
                },
            ],
        )
        self.assertAlmostEqual(result["AAPL"]["concentration"], 0.625)
        self.assertEqual(result["AAPL"]["quality"], 1.0)

    def test_guru_summary_uses_effective_current_and_previous_portfolios(self):
        result = _guru_candidate_signals(
            {"manager": {"effective_accession_no": "new"}},
            {"manager": {"effective_accession_no": "old"}},
            [
                {
                    "effective_accession_no": "old", "ticker": "AAPL",
                    "mapping_status": "mapped", "position_kind": "SHARES",
                    "quantity_type": "SH", "quantity": 100, "value_usd": 999,
                },
                {
                    "effective_accession_no": "new", "ticker": "AAPL",
                    "mapping_status": "mapped", "position_kind": "SHARES",
                    "quantity_type": "SH", "quantity": 150, "value_usd": 123,
                },
                {
                    "effective_accession_no": "new", "ticker": "AAPL",
                    "mapping_status": "mapped", "position_kind": "CALL",
                    "quantity_type": "SH", "quantity": 1, "value_usd": 999_999,
                },
            ],
        )
        self.assertEqual(result["AAPL"]["holder_count"], 1)
        self.assertEqual(result["AAPL"]["add_count"], 1)
        self.assertEqual(result["AAPL"]["total_value_usd"], 123)
        self.assertEqual(result["AAPL"]["avg_quantity_change_pct"], 50)
        self.assertEqual(result["AAPL"]["consensus"], "accumulating")


class CandidateCoverageRepositoryTest(unittest.TestCase):
    """후보 coverage는 로컬 runtime 판단 원장에서 읽는다.

    전에는 Postgres `trading.security_decisions`를 읽었는데 그 스키마는 선언에
    없다. 여기서는 저장소가 아니라 **동작**을 굳힌다 — 성공한 판단만, 요청한
    종목만, as_of 이전 것만, 그중 가장 최근 것.
    """

    @staticmethod
    def _coverage(rows, tickers=("AAPL", "MSFT", "NVDA")):
        with mock.patch(
            "investment_agent.reporting.readers.runtime.read_local_rows",
            return_value=rows,
        ):
            return SupabaseRepository()._candidate_last_analyzed(
                list(tickers), as_of_at=_AS_OF
            )

    def test_the_latest_successful_case_wins_per_ticker(self):
        coverage = self._coverage([
            {"case_key": "a-old", "ticker": "AAPL",
             "as_of_at": "2026-08-19T21:00:00+00:00", "status": "completed"},
            {"case_key": "a-new", "ticker": "AAPL",
             "as_of_at": "2026-08-20T21:00:00+00:00", "status": "abstained"},
            {"case_key": "m", "ticker": "MSFT",
             "as_of_at": "2026-08-18T21:00:00+00:00", "status": "completed"},
        ])
        self.assertEqual({"AAPL", "MSFT"}, set(coverage))
        self.assertEqual(datetime(2026, 8, 20, 21, tzinfo=timezone.utc), coverage["AAPL"])

    def test_a_failed_case_does_not_count_as_coverage(self):
        """실패한 판단을 coverage로 세면 그 종목이 다시 분석되지 않는다."""
        self.assertEqual({}, self._coverage([
            {"case_key": "bad", "ticker": "NVDA",
             "as_of_at": "2026-08-20T21:00:00+00:00", "status": "failed"},
        ]))

    def test_a_ticker_outside_the_request_is_ignored(self):
        self.assertEqual({}, self._coverage(
            [{"case_key": "x", "ticker": "TSLA",
              "as_of_at": "2026-08-20T21:00:00+00:00", "status": "completed"}],
            tickers=("AAPL",),
        ))

    def test_a_case_after_as_of_is_not_visible(self):
        """as_of 이후의 판단이 보이면 그 시점 재현이 아니다."""
        self.assertEqual({}, self._coverage([
            {"case_key": "future", "ticker": "AAPL",
             "as_of_at": "2099-01-01T00:00:00+00:00", "status": "completed"},
        ]))


if __name__ == "__main__":
    unittest.main()
