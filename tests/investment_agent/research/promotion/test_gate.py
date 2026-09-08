from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.research.promotion.gate import (
    EvaluationSummary,
    ManualPromotionGate,
    aggregate_evaluations,
)


class PromotionGateTest(unittest.TestCase):
    def test_clean_metrics_still_require_manual_approval(self):
        gate = ManualPromotionGate()
        proposed = gate.propose(
            "model-1", from_stage="shadow", to_stage="backtest",
            summary=EvaluationSummary(
                out_of_sample_days=100, walk_forward_windows=4, paper_days=0,
                excess_return=0.05, max_drawdown=-0.10, turnover=1.0,
                evaluation_count=5, evaluation_ids=(1, 2, 3, 4, 5),
            ),
        )
        self.assertEqual(proposed.status, "proposed")
        self.assertIsNone(proposed.approved_by)
        with self.assertRaises(ValueError):
            gate.approve(proposed, approved_by="operator", confirmation="wrong")
        approved = gate.approve(
            proposed,
            approved_by="operator",
            confirmation="PROMOTE model-1 shadow->backtest",
        )
        self.assertEqual(approved.status, "approved")

    def test_lookahead_incident_rejects_promotion(self):
        decision = ManualPromotionGate().propose(
            "model-1", from_stage="shadow", to_stage="backtest",
            summary=EvaluationSummary(
                out_of_sample_days=100, walk_forward_windows=4, paper_days=0,
                excess_return=0.05, max_drawdown=-0.1, turnover=1.0,
                lookahead_incidents=1,
                evaluation_count=5,
            ),
        )
        self.assertEqual(decision.status, "rejected")

    def test_paper_to_live_requires_paper_duration_and_exact_confirmation(self):
        gate = ManualPromotionGate()
        proposed = gate.propose(
            "model-1",
            from_stage="paper",
            to_stage="live",
            summary=EvaluationSummary(
                out_of_sample_days=100,
                walk_forward_windows=4,
                paper_days=30,
                excess_return=0.03,
                max_drawdown=-0.08,
                turnover=0.7,
                evaluation_count=6,
                evaluation_ids=(1, 2, 3, 4, 5, 6),
            ),
        )
        self.assertEqual(proposed.status, "proposed")
        approved = gate.approve(
            proposed,
            approved_by="operator",
            confirmation="PROMOTE model-1 paper->live",
        )
        self.assertEqual(approved.to_stage, "live")

    def test_current_cohort_research_result_cannot_be_promoted(self):
        decision = ManualPromotionGate().propose(
            "model-1", from_stage="shadow", to_stage="backtest",
            summary=EvaluationSummary(
                out_of_sample_days=100, walk_forward_windows=4, paper_days=30,
                excess_return=0.10, max_drawdown=-0.05, turnover=0.5,
                research_only=True,
                evaluation_count=5,
            ),
        )
        self.assertEqual(decision.status, "rejected")
        self.assertIn("research-only evidence cannot support promotion", decision.violations)

    def test_aggregate_uses_all_persisted_safety_attestations(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = []
        for evaluation_id, kind, offset, days in (
            (1, "out_of_sample", 0, 61),
            (2, "walk_forward", 70, 10),
            (3, "walk_forward", 90, 10),
            (4, "walk_forward", 110, 10),
        ):
            row_start = start + timedelta(days=offset)
            rows.append({
                "evaluation_id": evaluation_id,
                "proposal_id": f"proposal-{evaluation_id}",
                "evaluation_kind": kind,
                "start_at": row_start.isoformat(),
                "end_at": (row_start + timedelta(days=days)).isoformat(),
                "excess_return": 0.01 * evaluation_id,
                "max_drawdown": -0.05,
                "turnover": 0.5,
                "metrics": {},
                "research_only": False,
                "survivorship_check_passed": True,
                "leakage_check_passed": True,
                "data_integrity_check_passed": True,
            })
        summary = aggregate_evaluations(rows)
        self.assertEqual(summary.out_of_sample_days, 61)
        self.assertEqual(summary.walk_forward_windows, 3)
        self.assertEqual(summary.evaluation_ids, (1, 2, 3, 4))
        self.assertEqual(summary.excess_return, 0.01)
        self.assertEqual(summary.data_integrity_incidents, 0)

    def test_missing_integrity_attestation_fails_closed(self):
        summary = aggregate_evaluations([{
            "evaluation_id": 1,
            "proposal_id": "proposal-1",
            "evaluation_kind": "out_of_sample",
            "start_at": "2026-01-01T00:00:00+00:00",
            "end_at": "2026-04-01T00:00:00+00:00",
            "excess_return": 0.1,
            "max_drawdown": -0.05,
            "turnover": 0.2,
            "metrics": {},
            "research_only": False,
            "survivorship_check_passed": True,
            "leakage_check_passed": True,
            "data_integrity_check_passed": False,
        }])
        decision = ManualPromotionGate().propose(
            "model-1",
            from_stage="shadow",
            to_stage="backtest",
            summary=summary,
        )
        self.assertEqual(decision.status, "rejected")
        self.assertGreater(summary.data_integrity_incidents, 0)


if __name__ == "__main__":
    unittest.main()
