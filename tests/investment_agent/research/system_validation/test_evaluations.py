"""System 승격 증거 — 재현·운영 NAV가 게이트가 읽는 평가 행이 되고, 모르는 것은 통과로 적지 않는가."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from investment_agent.research.promotion.gate import ManualPromotionGate, aggregate_evaluations
from investment_agent.research.system_validation.evaluations import (
    MAX_SURVIVORSHIP_MISSING_SHARE,
    artifact_window,
    forward_evaluation_rows,
    replay_evaluation_rows,
    window_metrics,
)


def _history(start: date, days: int, *, daily: float = 0.0006, bench: float = 0.0004) -> list[dict]:
    rows, nav, benchmark, day = [], 100.0, 100.0, start
    while len(rows) < days:
        if day.weekday() < 5:
            rows.append({"trade_date": day.isoformat(), "nav": nav, "benchmark_nav": benchmark, "turnover": 0.002})
            nav *= 1 + daily
            benchmark *= 1 + bench
        day += timedelta(days=1)
    return rows


def _replay(history, **overrides):
    return replay_evaluation_rows(**{"artifact_id": "artifact_a", "history": history, "nav_unexplained_days": 0,
                                     "survivorship_missing_share": 0.01, "ml_lookahead_refused": False,
                                     "policy_version": "system-target-v4", **overrides})


class ReplayRowsTest(unittest.TestCase):
    def test_full_window_is_a_backtest_and_each_full_year_is_a_walk_forward_window(self):
        rows = _replay(_history(date(2021, 9, 13), 1000))
        kinds = [(row["evaluation_kind"], row["metrics"].get("window")) for row in rows]
        self.assertEqual(("backtest", None), kinds[0])
        # 2021년(약 80거래일)은 120일에 못 미쳐 창이 아니다. 2025년은 140일이라 창이다.
        self.assertEqual(["2022", "2023", "2024", "2025"], [window for kind, window in kinds if kind == "walk_forward"])
        self.assertTrue(all(row["metrics"]["thesis_replayed"] is False for row in rows))
        self.assertTrue(all(row["research_only"] is False for row in rows))

    def test_rewriting_the_same_window_keeps_the_same_identity(self):
        first, second = _replay(_history(date(2022, 1, 3), 300)), _replay(_history(date(2022, 1, 3), 300))
        self.assertEqual([row["evaluation_id"] for row in first], [row["evaluation_id"] for row in second])
        self.assertEqual(len({row["record_key"] for row in first}), len(first))

    def test_survivorship_above_the_tolerance_or_unknown_is_an_incident(self):
        for share in (MAX_SURVIVORSHIP_MISSING_SHARE + 0.01, None):
            rows = _replay(_history(date(2022, 1, 3), 300), survivorship_missing_share=share)
            self.assertTrue(all(not row["survivorship_check_passed"] for row in rows), share)
            self.assertGreater(aggregate_evaluations(rows).survivorship_incidents, 0)

    def test_drawdown_is_negative_and_excess_is_against_the_window_start(self):
        metrics = window_metrics([
            {"trade_date": "d1", "nav": 100.0, "benchmark_nav": 100.0, "turnover": 0.5},
            {"trade_date": "d2", "nav": 90.0, "benchmark_nav": 100.0, "turnover": 0.1},
            {"trade_date": "d3", "nav": 99.0, "benchmark_nav": 110.0, "turnover": 0.1},
        ])
        self.assertAlmostEqual(-0.10, metrics["max_drawdown"])
        self.assertAlmostEqual(-0.11, metrics["excess_return"])
        self.assertAlmostEqual(0.2, metrics["turnover"])  # 창 첫날의 편입은 창의 회전이 아니다


class ForwardRowsTest(unittest.TestCase):
    def test_the_window_starts_at_this_artifacts_first_application_and_stops_at_another(self):
        history = [{"trade_date": f"2026-10-{day:02d}", "applied_target_id": None} for day in range(1, 11)]
        history[2]["applied_target_id"] = "t_old"
        history[4]["applied_target_id"] = "t_new"
        history[6]["applied_target_id"] = "t_new2"
        history[8]["applied_target_id"] = "t_other"
        artifact_of = {"t_old": "a0", "t_new": "a1", "t_new2": "a1", "t_other": "a2"}
        window = artifact_window(history, artifact_of, "a1")
        self.assertEqual(["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"], [mark["trade_date"] for mark in window])

    def test_live_nav_before_paper_approval_is_out_of_sample_and_after_is_paper(self):
        history = _history(date(2026, 9, 24), 90)
        paper_since = history[60]["trade_date"]
        rows = forward_evaluation_rows(artifact_id="artifact_a", history=history, paper_since=paper_since,
                                       nav_unexplained_days=0)
        self.assertEqual(["out_of_sample", "paper"], [row["evaluation_kind"] for row in rows])
        summary = aggregate_evaluations(rows)
        self.assertGreaterEqual(summary.out_of_sample_days, 60)
        self.assertGreater(summary.paper_days, 0)


class GateReadsTheRowsTest(unittest.TestCase):
    def test_clean_evidence_passes_the_gate_to_paper_and_one_bad_year_blocks_it(self):
        replay = _replay(_history(date(2022, 1, 3), 800))
        forward = forward_evaluation_rows(artifact_id="artifact_a", history=_history(date(2026, 9, 24), 70),
                                          paper_since=None, nav_unexplained_days=0)
        gate = ManualPromotionGate()
        decision = gate.propose(artifact_id="artifact_a", from_stage="walk_forward", to_stage="paper",
                                summary=aggregate_evaluations(replay + forward))
        self.assertEqual((), decision.violations)
        losing_year = _replay(_history(date(2022, 1, 3), 800, daily=0.0001))
        decision = gate.propose(artifact_id="artifact_a", from_stage="walk_forward", to_stage="paper",
                                summary=aggregate_evaluations(losing_year + forward))
        self.assertIn("excess return is not positive", decision.violations)


if __name__ == "__main__":
    unittest.main()
