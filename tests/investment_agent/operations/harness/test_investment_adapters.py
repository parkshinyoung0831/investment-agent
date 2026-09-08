from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from threading import Event

from investment_agent.operations.harness.commands import CommandResult
from investment_agent.operations.harness.contracts import StageContext
from investment_agent.operations.harness_adapters import ProductionInvestmentAdapters, SessionWindow

UTC = timezone.utc
OPEN = datetime(2026, 8, 24, 14, 0, tzinfo=UTC)
BATCH = "signal_batch_" + "a" * 24
RISK = "risk_" + "b" * 24
INTENT = "intent_" + "c" * 24
APPROVAL = "approval_" + "d" * 32


class FakeRunner:
    def __init__(self):
        self.commands = []

    def run(self, command, *, stop_event):
        self.commands.append(command)
        return CommandResult(command.module, 0, 0.1)


class FakeDecisionRepository:
    def __init__(self):
        self.requested_as_of = None

    def signal_batch_id_for_as_of(self, *, as_of_at):
        self.requested_as_of = as_of_at
        return BATCH

    def latest_signal_batch_id(self, *, as_of_at):
        return BATCH


class FakeApprovalRepository:
    def __init__(self):
        self.approval = None

    def approval_for_intent(self, intent_id):
        return self.approval


def context(stage_id: str, completed=None) -> StageContext:
    return StageContext(
        job_id="investment_pipeline",
        run_id="run_123",
        stage_id=stage_id,
        attempt=1,
        idempotency_key="key",
        now=OPEN,
        stop_event=Event(),
        prior_metadata={},
        completed_metadata=dict(completed or {}),
    )


class InvestmentAdaptersTest(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner()
        self.decision_repository = FakeDecisionRepository()
        self.approval_repository = FakeApprovalRepository()
        self.construct_calls = []
        self.intent_calls = []

        def construct(**kwargs):
            self.construct_calls.append(kwargs)
            return SimpleNamespace(
                proposal_id="proposal_" + "1" * 24,
                risk_decision_id=RISK,
                account_snapshot_id="execution_snapshot_1",
                is_approved=True,
            )

        def create_intent(**kwargs):
            self.intent_calls.append(kwargs)
            return SimpleNamespace(intent_id=INTENT, expires_at=(OPEN + timedelta(minutes=15)).isoformat())

        self.adapters = ProductionInvestmentAdapters(
            command_runner=self.runner,
            decision_repository=self.decision_repository,
            approval_repository=self.approval_repository,
            construct_portfolio=construct,
            create_execution_intent=create_intent,
            now=lambda: OPEN,
        )

    def test_exact_ids_flow_from_analysis_to_approval_without_raw_db_selection(self):
        analysis = self.adapters.analysis(context("analysis"))
        self.assertEqual(analysis.metadata["batch_id"], BATCH)
        self.assertEqual(self.decision_repository.requested_as_of, OPEN)

        selected = self.adapters.select_signal(context("select_signal"))
        portfolio = self.adapters.portfolio(context(
            "portfolio", {"select_signal": selected.metadata},
        ))
        self.assertEqual(portfolio.metadata["risk_decision_id"], RISK)
        self.assertEqual(self.construct_calls[0]["batch_id"], BATCH)

        intent = self.adapters.execution_intent(context(
            "execution_intent", {"portfolio": portfolio.metadata},
        ))
        self.assertEqual(intent.metadata["intent_id"], INTENT)
        self.assertEqual(self.intent_calls[0]["confirmation"], RISK)

        self.approval_repository.approval = SimpleNamespace(
            approval_id=APPROVAL,
            intent_id=INTENT,
            status="pending",
            discord_message_id="123456789",
            expires_at=(OPEN + timedelta(minutes=15)).isoformat(),
        )
        approval = self.adapters.approval_request(context(
            "approval_request", {"execution_intent": intent.metadata},
        ))
        self.assertEqual(approval.metadata["approval_id"], APPROVAL)
        self.assertEqual(self.runner.commands[-1].module, "investment_agent.operations.commands.request_toss_approval")

    def test_pending_waits_and_approved_captures_risk_before_exact_execution(self):
        completed = {
            "approval_request": {
                "approval_id": APPROVAL,
                "intent_id": INTENT,
                "expires_at": (OPEN + timedelta(minutes=15)).isoformat(),
            }
        }
        self.approval_repository.approval = SimpleNamespace(
            approval_id=APPROVAL,
            status="pending",
            discord_message_id="123456789",
            expires_at=(OPEN + timedelta(minutes=15)).isoformat(),
        )
        waiting = self.adapters.approval_worker(context("approval_worker", completed))
        self.assertEqual(waiting.status, "waiting")
        self.assertEqual(self.runner.commands, [])

        self.approval_repository.approval.status = "approved"
        executed = self.adapters.approval_worker(context("approval_worker", completed))
        self.assertEqual(executed.status, "succeeded")
        self.assertEqual(
            [item.module for item in self.runner.commands],
            [
                "investment_agent.operations.commands.capture_toss_risk_snapshot",
                "investment_agent.operations.commands.execute_toss_live",
            ],
        )
        self.assertEqual(
            self.runner.commands[-1].arguments,
            ("--approval-id", APPROVAL),
        )

    def test_risk_rejection_skips_every_mutating_stage(self):
        rejected = {"risk_approved": False, "risk_decision_id": RISK}
        intent = self.adapters.execution_intent(context(
            "execution_intent", {"portfolio": rejected},
        ))
        approval = self.adapters.approval_request(context(
            "approval_request", {"execution_intent": intent.metadata},
        ))
        worker = self.adapters.approval_worker(context(
            "approval_worker", {"approval_request": approval.metadata},
        ))
        self.assertEqual([intent.status, approval.status, worker.status], [
            "skipped", "skipped", "skipped",
        ])
        self.assertEqual(self.runner.commands, [])

    def test_earnings_watch_runs_the_canonical_entry_without_a_trading_window(self):
        """수집은 거래 창과 무관하다 — 창으로 자르면 BMO·AMC 발표를 통째로 놓친다."""
        saturday = datetime(2026, 8, 22, 3, 0, tzinfo=UTC)  # 거래 창 밖(주말 새벽)
        outcome = self.adapters.watch(StageContext(
            job_id="earnings_watch",
            run_id="run_watch",
            stage_id="watch",
            attempt=1,
            idempotency_key="key",
            now=saturday,
            stop_event=Event(),
            prior_metadata={},
            completed_metadata={},
        ))

        self.assertEqual(outcome.status, "succeeded")
        self.assertEqual(
            [item.module for item in self.runner.commands],
            ["investment_agent.operations.commands.watch_earnings"],
        )
        self.assertEqual(
            self.runner.commands[0].arguments,
            ("--session", "auto", "--notify", "--report-notify"),
        )

    def test_weekend_waits_until_new_york_weekday_window(self):
        saturday = datetime(2026, 8, 22, 14, 0, tzinfo=UTC)
        self.assertFalse(SessionWindow().is_open(saturday))
        self.assertGreater(SessionWindow().seconds_until_open(saturday), 24 * 60 * 60)


if __name__ == "__main__":
    unittest.main()
