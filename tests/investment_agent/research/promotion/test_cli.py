from __future__ import annotations

import unittest
from unittest.mock import patch

from investment_agent.research.promotion.cli import main
from investment_agent.research.promotion.gate import EvaluationSummary


def _clean_summary() -> EvaluationSummary:
    return EvaluationSummary(
        out_of_sample_days=90,
        walk_forward_windows=3,
        paper_days=0,
        excess_return=0.04,
        max_drawdown=-0.08,
        turnover=0.5,
        evaluation_count=4,
        evaluation_ids=(1, 2, 3, 4),
    )


class _Repository:
    def __init__(self, summary=None):
        self.summary = summary or _clean_summary()
        self.rejected = []
        self.approved = []

    def model_artifact(self, artifact_id):
        return {"artifact_id": artifact_id}

    def model_stage(self, artifact_id):
        return "shadow"

    def model_evaluation_summary(self, artifact_id):
        return self.summary

    def save_promotion(self, row):
        self.rejected.append(row)

    def approve_model_promotion(self, decision, *, confirmation):
        self.approved.append((decision, confirmation))
        return {"promotion_id": 9, "status": "approved"}


class PromoteModelEntryTest(unittest.TestCase):
    def test_exact_stage_scoped_confirmation_promotes_once(self):
        repository = _Repository()
        with patch(
            "investment_agent.research.promotion.cli.SupabaseRepository",
            return_value=repository,
        ):
            result = main([
                "--artifact-id", "artifact-1",
                "--to-stage", "backtest",
                "--approved-by", "operator-1",
                "--confirm", "PROMOTE artifact-1 shadow->backtest",
            ])
        self.assertEqual(result, 0)
        self.assertEqual(len(repository.approved), 1)
        self.assertFalse(repository.rejected)

    def test_research_only_is_audited_as_rejected(self):
        summary = _clean_summary()
        repository = _Repository(EvaluationSummary(
            **{
                **summary.__dict__,
                "research_only": True,
            }
        ))
        with patch(
            "investment_agent.research.promotion.cli.SupabaseRepository",
            return_value=repository,
        ):
            with self.assertRaisesRegex(RuntimeError, "research-only"):
                main([
                    "--artifact-id", "artifact-1",
                    "--to-stage", "backtest",
                    "--approved-by", "operator-1",
                    "--confirm", "PROMOTE artifact-1 shadow->backtest",
                ])
        self.assertEqual(repository.rejected[0]["status"], "rejected")
        self.assertFalse(repository.approved)

    def test_skipping_paper_stage_fails_closed(self):
        repository = _Repository()
        with patch(
            "investment_agent.research.promotion.cli.SupabaseRepository",
            return_value=repository,
        ):
            with self.assertRaisesRegex(RuntimeError, "one step"):
                main([
                    "--artifact-id", "artifact-1",
                    "--to-stage", "live",
                    "--approved-by", "operator-1",
                    "--confirm", "PROMOTE artifact-1 shadow->live",
                ])
        self.assertFalse(repository.approved)


if __name__ == "__main__":
    unittest.main()
