from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.research.promotion.gate import (
    PROMOTION_PATH,
    EvaluationSummary,
    ManualPromotionGate,
    PromotionCriteria,
    PromotionDecision,
    aggregate_evaluations,
    approval_audit_row,
    approval_confirmation,
    has_approved_chain,
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

    def test_turnover_is_annualized_so_window_length_does_not_decide_the_verdict(self):
        """5년 백테스트의 누적 turnover 8과 3개월 창의 0.5는 같은 연 1.6이다(RS-6)."""
        def summary_for(days: int, turnover: float):
            return aggregate_evaluations([{
                "evaluation_id": 1, "proposal_id": "p", "evaluation_kind": "backtest",
                "start_at": "2020-01-01T00:00:00+00:00",
                "end_at": (datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=days)).isoformat(),
                "excess_return": 0.1, "max_drawdown": -0.05, "turnover": turnover, "metrics": {},
                "research_only": False, "survivorship_check_passed": True,
                "leakage_check_passed": True, "data_integrity_check_passed": True,
            }])

        long_window = summary_for(365 * 5, 8.0)
        short_window = summary_for(91, 0.4)
        self.assertAlmostEqual(1.6, long_window.turnover, places=2)
        self.assertAlmostEqual(1.6, short_window.turnover, delta=0.02)
        self.assertLessEqual(long_window.turnover, PromotionCriteria().max_turnover)
        self.assertLessEqual(short_window.turnover, PromotionCriteria().max_turnover)

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


def _audit(artifact_id: str, from_stage: str, to_stage: str, **overrides: object) -> dict:
    row = {
        "artifact_id": artifact_id, "from_stage": from_stage, "to_stage": to_stage,
        "status": "approved", "confirmation_text": approval_confirmation(artifact_id, from_stage, to_stage),
    }
    return {**row, **overrides}


def _chain(artifact_id: str, *, upto: str) -> list[dict]:
    stop = PROMOTION_PATH.index(upto)
    return [_audit(artifact_id, a, b) for a, b in zip(PROMOTION_PATH[:stop], PROMOTION_PATH[1:stop + 1])]


class ApprovedChainTest(unittest.TestCase):
    """실주문 직전 검사(`has_approved_chain`)가 승격 규칙과 같은 원본을 쓰는지 고정한다."""

    def test_lifecycle_is_the_declared_order_and_transitions_follow_it(self):
        self.assertEqual(("shadow", "backtest", "out_of_sample", "walk_forward", "paper", "live"), PROMOTION_PATH)

    def test_lifecycle_matches_the_trading_stage_vocabulary(self):
        # Research와 Trading은 서로 import할 수 없어 같은 목록을 각자 선언한다. 갈라지면 여기서 실패한다.
        from investment_agent.trading.run_context import STAGES

        self.assertEqual(tuple(STAGES), PROMOTION_PATH)

    def test_confirmation_text_is_one_definition_for_gate_and_chain_check(self):
        decision = ManualPromotionGate().propose(
            "model-1", from_stage="paper", to_stage="live",
            summary=EvaluationSummary(
                out_of_sample_days=100, walk_forward_windows=4, paper_days=30,
                excess_return=0.03, max_drawdown=-0.08, turnover=0.7, evaluation_count=6,
            ),
        )
        self.assertEqual(approval_confirmation("model-1", "paper", "live"), ManualPromotionGate.confirmation_text(decision))
        self.assertEqual("PROMOTE model-1 paper->live", approval_confirmation("model-1", "paper", "live"))

    def test_complete_chain_reaches_paper_and_live_at_or_above_the_target_stage(self):
        for target in ("paper", "live"):
            self.assertTrue(has_approved_chain(
                artifact_id="m", current_stage="live", to_stage=target, audits=_chain("m", upto="live"),
            ), target)
        self.assertTrue(has_approved_chain(
            artifact_id="m", current_stage="paper", to_stage="paper", audits=_chain("m", upto="paper"),
        ))

    def test_missing_middle_transition_fails_closed(self):
        audits = [row for row in _chain("m", upto="live") if row["to_stage"] != "walk_forward"]
        self.assertFalse(has_approved_chain(artifact_id="m", current_stage="live", to_stage="live", audits=audits))

    def test_live_needs_the_paper_to_live_transition_but_paper_does_not(self):
        audits = _chain("m", upto="paper")
        self.assertTrue(has_approved_chain(artifact_id="m", current_stage="live", to_stage="paper", audits=audits))
        self.assertFalse(has_approved_chain(artifact_id="m", current_stage="live", to_stage="live", audits=audits))

    def test_unapproved_or_mistyped_audits_do_not_count(self):
        for override in ({"status": "proposed"}, {"status": "rejected"}, {"confirmation_text": "yes"},
                         {"confirmation_text": "PROMOTE other paper->live"}):
            audits = _chain("m", upto="live")
            audits[-1] = {**audits[-1], **override}
            self.assertFalse(has_approved_chain(
                artifact_id="m", current_stage="live", to_stage="live", audits=audits,
            ), override)

    def test_artifact_must_currently_be_at_or_above_the_target_stage(self):
        audits = _chain("m", upto="live")
        for current in ("shadow", "backtest", "out_of_sample", "walk_forward"):
            self.assertFalse(has_approved_chain(artifact_id="m", current_stage=current, to_stage="paper", audits=audits))
        self.assertFalse(has_approved_chain(artifact_id="m", current_stage="paper", to_stage="live", audits=audits))

    def test_only_execution_stages_and_known_current_stages_pass(self):
        audits = _chain("m", upto="live")
        for target in ("shadow", "backtest", "out_of_sample", "walk_forward", "unknown"):
            self.assertFalse(has_approved_chain(artifact_id="m", current_stage="live", to_stage=target, audits=audits), target)
        self.assertFalse(has_approved_chain(artifact_id="m", current_stage="unknown", to_stage="paper", audits=audits))
        self.assertFalse(has_approved_chain(artifact_id="m", current_stage=None, to_stage="paper", audits=audits))


def _approved_decision(from_stage: str = "shadow", to_stage: str = "backtest") -> "PromotionDecision":
    gate = ManualPromotionGate()
    proposed = gate.propose(
        "model-1", from_stage=from_stage, to_stage=to_stage,
        summary=EvaluationSummary(
            out_of_sample_days=100, walk_forward_windows=4, paper_days=30,
            excess_return=0.03, max_drawdown=-0.08, turnover=0.7, evaluation_count=6,
        ),
    )
    return gate.approve(
        proposed, approved_by="operator", confirmation=approval_confirmation("model-1", from_stage, to_stage),
    )


class ApprovalAuditRowTest(unittest.TestCase):
    """승인 감사 행을 만들기 전의 fail-closed 검증. 원장에는 이 행만 쓴다."""

    def test_builds_the_audit_row_the_ledger_stores(self):
        decision = _approved_decision()
        row = approval_audit_row(
            decision, confirmation="PROMOTE model-1 shadow->backtest",
            model_artifact={"artifact_id": "model-1"}, model_stage="shadow",
        )
        self.assertEqual("approved", row["status"])
        self.assertEqual("operator", row["approved_by"])
        self.assertEqual("PROMOTE model-1 shadow->backtest", row["confirmation_text"])
        self.assertEqual(("model-1", "shadow", "backtest"), (row["artifact_id"], row["from_stage"], row["to_stage"]))
        self.assertEqual(decision.to_record()["evidence"], row["evidence"])

    def test_undecided_or_rejected_decisions_are_not_persisted(self):
        proposed = ManualPromotionGate().propose(
            "model-1", from_stage="shadow", to_stage="backtest",
            summary=EvaluationSummary(0, 0, 0, 0.0, -1.0, 0.0, evaluation_count=0),
        )
        with self.assertRaisesRegex(ValueError, "only a manually"):
            approval_audit_row(proposed, confirmation="x", model_artifact={"a": 1}, model_stage="shadow")

    def test_missing_artifact_or_moved_stage_fails_closed(self):
        decision = _approved_decision()
        confirmation = "PROMOTE model-1 shadow->backtest"
        with self.assertRaisesRegex(RuntimeError, "artifact not found"):
            approval_audit_row(decision, confirmation=confirmation, model_artifact=None, model_stage="shadow")
        with self.assertRaisesRegex(RuntimeError, "stage changed"):
            approval_audit_row(decision, confirmation=confirmation, model_artifact={"a": 1}, model_stage="backtest")
        with self.assertRaisesRegex(RuntimeError, "stage changed"):
            approval_audit_row(decision, confirmation=confirmation, model_artifact={"a": 1}, model_stage=None)

    def test_confirmation_must_match_exactly(self):
        with self.assertRaisesRegex(ValueError, "confirmation must exactly match"):
            approval_audit_row(
                _approved_decision(), confirmation="PROMOTE model-1 shadow->paper",
                model_artifact={"a": 1}, model_stage="shadow",
            )


if __name__ == "__main__":
    unittest.main()
