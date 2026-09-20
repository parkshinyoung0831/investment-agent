"""Ablation 재현: 운영 System 엔진을 변형별로 돌리고, 운영 원장에 쓰지 않으며, 미래를 본 ML은 거부한다."""
from __future__ import annotations

import random
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from investment_agent.research.system_validation.ablation import (
    ReplayRepository,
    default_variants,
    ml_artifact_lookahead,
    run_ablation,
)
from investment_agent.research.features.factors import FactorScore
from investment_agent.trading.risk.stress import STRESS_PROXIES

START_DAY = date(2025, 1, 1)
NAMES = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")


def _history() -> dict[str, list[dict]]:
    rng = random.Random(11)
    market = [0.0004 + rng.gauss(0, 0.009) for _ in range(420)]
    history: dict[str, list[dict]] = {}
    for name in sorted({*NAMES, "SPY", *STRESS_PROXIES}):
        price, rows = 100.0, []
        for offset in range(420):
            day = START_DAY + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            price *= 1 + 0.9 * market[offset] + rng.gauss(0, 0.011)
            rows.append({"trade_date": day.isoformat(), "open": price, "close": price, "volume": 5_000_000})
        history[name] = rows
    return history


class _Base:
    """운영 repository 흉내. 판단 기록 저장 메서드가 없으므로, 재현이 저장을 시도하면 바로 실패한다."""

    def __init__(self):
        self.history = _history()
        self.membership_calls = 0

    def market_prices(self, ticker, as_of_at, limit=260):
        rows = [row for row in self.history.get(ticker, []) if row["trade_date"] <= as_of_at.date().isoformat()]
        return rows[-limit:]

    def historical_sp500_membership(self, *, start_date, end_date):
        self.membership_calls += 1
        return [{"effective_date": start_date.isoformat(), "symbols": list(NAMES)}]

    def sp500_sector_map(self, tickers):
        return {ticker: ("tech" if ticker in {"AAA", "BBB", "CCC"} else "energy") for ticker in tickers}

    def macro_histories(self, series_ids, *, as_of_at, lookback_days=120):
        return {}

    def thesis_views(self, tickers, *, as_of_at, valid_days):
        return {}

    def rl_feature_snapshot_rows(self, *args, **kwargs):
        return []


def _cross_section(as_of_at: datetime):
    week = as_of_at.date() - timedelta(days=as_of_at.weekday())
    scores = {ticker: FactorScore(ticker, {"quality": 0.8, "momentum": 0.5, "value": 0.5}, value, True, None)
              for ticker, value in dict(AAA=0.95, BBB=0.9, CCC=0.85, DDD=0.4, EEE=0.3, FFF=0.2).items()}
    return week.isoformat(), scores


class AblationTest(unittest.TestCase):
    def test_variants_replay_the_production_engine_without_touching_the_ledger(self):
        base = _Base()
        variants = [variant for variant in default_variants() if variant.name in {"factor_only", "no_tail_risk"}]
        report = run_ablation(base, start=date(2025, 11, 1), end=date(2026, 1, 31), variants=variants,
                              cross_section=_cross_section)
        self.assertEqual(report["baseline"], "factor_only")
        self.assertGreater(report["sessions"], 40)
        by_name = {row["name"]: row for row in report["variants"]}
        self.assertEqual(set(by_name), {"factor_only", "no_tail_risk"})
        for row in by_name.values():
            self.assertEqual(row["status"], "completed")
            self.assertGreaterEqual(row["targets"], 1)
            self.assertGreater(row["summary"]["days"], 20)
            self.assertGreater(row["coverage"]["factor_snapshot_periods"], 1)
            self.assertGreater(row["coverage"]["risky_target_count"], 0)
            self.assertGreater(row["coverage"]["factor_category_periods"]["quality"], 1)
            self.assertIn("tail_risk_enabled_periods", row["coverage"])
            self.assertIn("tail_risk_bound_periods", row["coverage"])
            self.assertIn("market_risk_input_periods", row["coverage"])
        self.assertGreater(by_name["factor_only"]["coverage"]["tail_risk_enabled_periods"], 0)
        self.assertEqual(by_name["no_tail_risk"]["coverage"]["tail_risk_enabled_periods"], 0)
        self.assertEqual(by_name["factor_only"]["versus_baseline"]["total_return"], 0.0)
        self.assertFalse(by_name["no_tail_risk"]["system_policy"]["use_tail_risk"])
        self.assertFalse(by_name["no_tail_risk"]["alpha_policy"]["use_thesis"])
        self.assertEqual(
            by_name["factor_only"]["summary"]["start_date"],
            by_name["no_tail_risk"]["summary"]["start_date"],
        )
        self.assertGreater(base.membership_calls, 0)  # 종목은 판단 시각의 멤버십으로 정했다

    def test_ml_fit_on_data_after_the_replay_start_is_refused(self):
        early = {"artifact": {"train_period": ["2023-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"],
                              "validation_period": ["2024-01-02T00:00:00+00:00", "2024-06-01T00:00:00+00:00"],
                              "oos_period": ["2024-06-02T00:00:00+00:00", "2024-12-01T00:00:00+00:00"]}}
        replay_start = datetime(2025, 12, 1, 21, tzinfo=UTC)
        self.assertIsNone(ml_artifact_lookahead(early, replay_start=replay_start))
        late = {"artifact": {**early["artifact"], "oos_period": ["2024-06-02T00:00:00+00:00", "2025-12-20T00:00:00+00:00"]}}
        self.assertIn("after the replay start", ml_artifact_lookahead(late, replay_start=replay_start))

        base = _Base()
        variants = [variant for variant in default_variants() if variant.name in {"factor_only", "factor_ml"}]
        report = run_ablation(base, start=date(2025, 12, 1), end=date(2026, 1, 15), variants=variants,
                              ml_artifact=late, cross_section=_cross_section)
        by_name = {row["name"]: row for row in report["variants"]}
        self.assertEqual(by_name["factor_ml"]["status"], "refused")
        self.assertEqual(by_name["factor_only"]["status"], "completed")

    def test_replay_repository_reads_members_at_the_decision_time_and_drops_ledger_writes(self):
        base = _Base()
        repository = ReplayRepository(base, feature_rows=lambda start, end: [])
        with self.assertRaises(RuntimeError):
            repository.current_tracked_tickers()
        repository.now = datetime(2025, 6, 2, 21, tzinfo=UTC)
        self.assertEqual(repository.current_tracked_tickers(), sorted(NAMES))
        self.assertIsNone(repository.save_portfolio_proposal({"proposal_id": "x"}))
        self.assertIsNone(repository.factor_cross_section(repository.now))

    def test_default_variants_cover_the_requested_comparisons(self):
        variants = default_variants()
        names = {variant.name for variant in variants}
        self.assertTrue({"factor_only", "factor_ml", "factor_ml_thesis", "no_tail_risk", "no_market_risk",
                         "cvar_5", "cvar_12"} <= names)
        risk_variants = [variant for variant in variants if variant.name in {"no_tail_risk", "no_market_risk", "cvar_5", "cvar_12"}]
        self.assertTrue(all(not variant.alpha.use_ml and not variant.alpha.use_thesis for variant in risk_variants))

    def test_missing_ml_and_thesis_inputs_are_not_reported_as_completed(self):
        defaults = default_variants()
        factor_ml = next(variant for variant in defaults if variant.name == "factor_ml")
        factor_thesis = replace(
            next(variant for variant in defaults if variant.name == "factor_ml_thesis"),
            alpha=replace(factor_ml.alpha, use_ml=False, use_thesis=True),
        )
        report = run_ablation(
            _Base(), start=date(2025, 11, 1), end=date(2026, 1, 31),
            variants=(factor_ml, factor_thesis), cross_section=_cross_section,
        )
        by_name = {row["name"]: row for row in report["variants"]}
        self.assertEqual(by_name["factor_ml"]["status"], "insufficient_coverage")
        self.assertEqual(by_name["factor_ml"]["reason"], "ml_forecast_never_applied")
        self.assertEqual(by_name["factor_ml_thesis"]["status"], "insufficient_coverage")
        self.assertEqual(by_name["factor_ml_thesis"]["reason"], "thesis_view_never_observed")


if __name__ == "__main__":
    unittest.main()
