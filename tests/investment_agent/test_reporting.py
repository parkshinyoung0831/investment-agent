"""공통 조회 계약을 실제 페이지네이션과 오프라인 응답으로 검증한다."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from investment_agent.execution.approval.ledger import ApprovalRequest
from investment_agent.execution.db import ExecutionRepository
from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.db.sqlite import runtime_connection
from investment_agent.reporting.readers.runtime import LOCAL_VIEWS
from investment_agent.reporting.readers.financial import ReportingQueries, VIEWS
from tests.investment_agent.fakes import FakeDatabase


class Builder:
    def __init__(self, client):
        self.client = client
        self.filters = []
        self.orders = []

    def select(self, columns):
        self.columns = columns.split(",")
        return self

    def eq(self, column, value):
        self.filters.append((column, "eq", value))
        return self

    def in_(self, column, values):
        self.filters.append((column, "in", tuple(values)))
        return self

    def gte(self, column, value):
        self.filters.append((column, "gte", value))
        return self

    def lte(self, column, value):
        self.filters.append((column, "lte", value))
        return self

    def range(self, start, end):
        self.bounds = (start, end)
        return self

    def order(self, column):
        self.orders.append(column)
        return self

    def execute(self):
        if self.client.error:
            raise self.client.error
        rows = self.client.rows
        for column, operation, value in self.filters:
            if operation == "eq":
                rows = [r for r in rows if r[column] == value]
            elif operation == "in":
                rows = [r for r in rows if r[column] in value]
            elif operation == "gte":
                rows = [r for r in rows if r[column] >= value]
            else:
                rows = [r for r in rows if r[column] <= value]
        for column in reversed(self.orders):
            rows = sorted(rows, key=lambda r: (r[column] is None, r[column]))
        start, end = self.bounds
        return SimpleNamespace(data=rows[start:end+1])


class Client:
    def __init__(self, rows=(), error=None):
        self.rows = list(rows)
        self.error = error
        self.builders = []
        self.tables = []

    def schema(self, schema):
        assert schema == "reporting"
        return self

    def table(self, name):
        self.tables.append(name)
        builder = Builder(self)
        self.builders.append(builder)
        return builder


def row_for(view, **values):
    return dict.fromkeys(VIEWS[view].columns.split(",")) | values


class ReportingTest(unittest.TestCase):
    def test_all_views_preserve_values_and_explicit_columns(self):
        """LOCAL_VIEWS는 Postgres가 아니라 로컬 runtime.sqlite3가 소유한다 —
        별도 real-SQLite 계약은 LocalRuntimeViewTest가 검증한다."""
        for view, spec in VIEWS.items():
            if view in LOCAL_VIEWS:
                continue
            with self.subTest(view=view):
                row = row_for(view)
                filters = {spec.scope_column: "scope"} if spec.scope_column else {}
                row.update(filters)
                client = Client([row])
                result = ReportingQueries(Database(client)).read(view, equals=filters)
                self.assertEqual("ok", result.status)
                self.assertEqual([row], result.rows)
                self.assertEqual(spec.columns.split(","), client.builders[0].columns)
                self.assertIsNone(result.observed_at)
                self.assertEqual("reporting." + view, result.source)

    def test_three_pages_have_no_missing_rows(self):
        rows = [row_for("securities", ticker=f"T{i:04}") for i in range(2105)]
        client = Client(reversed(rows))
        result = ReportingQueries(Database(client)).read("securities")
        self.assertEqual(rows, result.rows)
        self.assertEqual([(0, 999), (1000, 1999), (2000, 2999)], [b.bounds for b in client.builders])
        self.assertTrue(all(b.orders == ["ticker"] for b in client.builders))

    def test_filters_survive_every_page_and_range_is_inclusive(self):
        rows = [row_for("prices_daily", ticker="A", trade_date=f"2026-09-{i:02}") for i in (1, 2, 3)]
        client = Client(rows + [row_for("prices_daily", ticker="B", trade_date="2026-09-02")])
        result = ReportingQueries(Database(client)).read("prices_daily", equals={"ticker": "A"}, start="2026-09-01", end="2026-09-02")
        self.assertEqual(rows[:2], result.rows)

    def test_membership_filters_are_scoped_and_explicit(self):
        rows = [
            row_for("macro_observations", series_id="A", obs_date="2026-09-01"),
            row_for("macro_observations", series_id="B", obs_date="2026-09-01"),
        ]
        client = Client(rows)
        result = ReportingQueries(Database(client)).read(
            "macro_observations",
            in_values={"series_id": ("A", "B")},
            start="2026-09-01",
            end="2026-09-01",
        )
        self.assertEqual(rows, result.rows)
        self.assertIn(("series_id", "in", ("A", "B")), client.builders[0].filters)

    def test_failures_are_not_empty_or_secret_messages(self):
        for error in (RuntimeError("token=secret https://private.example"), ConnectionError("secret")):
            result = ReportingQueries(Database(Client(error=error))).read("securities")
            self.assertEqual("error", result.status)
            self.assertNotIn("secret", result.message)
            self.assertEqual([], result.rows)
        self.assertEqual("empty", ReportingQueries(Database(Client())).read("securities").status)

    def test_offline_and_unconfigured_do_not_connect(self):
        client = Client(error=AssertionError("must not connect"))
        self.assertEqual("offline", ReportingQueries(Database(client), is_offline=True).read("securities").status)
        self.assertEqual([], client.tables)
        self.assertEqual("unconfigured", ReportingQueries(None).read("securities").status)

    def test_invalid_queries_fail_before_connection(self):
        cases = [
            ("orders", {}), ("prices_daily", {}),
            ("securities", {"equals": {"security_id": "x"}}),
            ("prices_daily", {"equals": {"ticker": ""}}),
            ("prices_daily", {"start": "2026-01-01"}),
            ("prices_daily", {"start": "2026-02-01", "end": "2026-01-01"}),
            ("securities", {"start": "2026-01-01", "end": "2026-02-01"}),
            ("prices_daily", {"start": "bad", "end": "bad"}),
            ("security_decisions", {"start": "2026-01-01T00:00:00", "end": "2026-02-01T00:00:00"}),
        ]
        client = Client()
        for view, kwargs in cases:
            with self.subTest(view=view, kwargs=kwargs), self.assertRaises(ValueError):
                ReportingQueries(Database(client)).read(view, **kwargs)
        self.assertEqual([], client.tables)

    def test_unexpected_or_missing_columns_are_contract_errors(self):
        for row in ({"ticker": "A"}, row_for("securities", security_id="private")):
            result = ReportingQueries(Database(Client([row]))).read("securities")
            self.assertEqual("error", result.status)
            self.assertEqual([], result.rows)

    def test_surprise_numbers_are_not_recalculated(self):
        row = row_for("earnings_surprise", ticker="A", eps_surprise_pct=0.15, revenue_surprise_pct=None)
        result = ReportingQueries(Database(Client([row]))).read("earnings_surprise", equals={"ticker": "A"})
        self.assertEqual(0.15, result.rows[0]["eps_surprise_pct"])
        self.assertIsNone(result.rows[0]["revenue_surprise_pct"])


class LocalRuntimeViewTest(unittest.TestCase):
    """LOCAL_VIEWS는 Postgres가 아니라 실행 컴퓨터의 runtime.sqlite3가 소유한다 —
    ReportingQueries.read()의 로컬 분기를 실제 SQLite 임시 파일로 검증한다."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "runtime.sqlite3"
        env = patch.dict("os.environ", {"AI_INVESTOR_RUNTIME_DB_PATH": str(self.path)})
        env.start()
        self.addCleanup(env.stop)

    @staticmethod
    def _live_intent(*, intent_id: str = "intent-1", risk_decision_id: str = "risk-1") -> ExecutionIntent:
        now = datetime.now(timezone.utc)
        return ExecutionIntent(
            intent_id=intent_id, proposal_id="proposal-1", risk_decision_id=risk_decision_id,
            execution_mode="live", target_weights={"AAPL": 0.5, "CASH": 0.5}, input_hash="a" * 64,
            not_before=now - timedelta(minutes=1), expires_at=now + timedelta(hours=1),
        )

    def test_execution_control_state_reflects_the_latest_control_value(self) -> None:
        control = {
            "scope": "global", "kill_switch_on": True, "durable_lockdown_on": True,
            "live_enabled": False, "live_autonomy_enabled": False, "version": 1,
            "reason": "fail-closed default", "updated_at": "2026-09-01T00:00:00+00:00",
        }
        with runtime_connection() as connection:
            connection.execute(
                "INSERT INTO execution_control(control_key,control_value,updated_at) VALUES(?,?,?)",
                ("global", json.dumps(control), control["updated_at"]),
            )
        result = ReportingQueries(None).read("execution_control_state")
        self.assertEqual("ok", result.status)
        self.assertEqual([control], result.rows)

    def test_execution_intents_projects_the_payload_and_ledger_columns(self) -> None:
        intent = self._live_intent()
        ExecutionRepository().save_intent(intent.as_row())
        result = ReportingQueries(None).read("execution_intents")
        self.assertEqual("ok", result.status)
        self.assertEqual("intent-1", result.rows[0]["intent_id"])
        self.assertEqual({"AAPL": 0.5, "CASH": 0.5}, result.rows[0]["target_weights"])

    def _consumed_approval(self, intent: ExecutionIntent) -> ApprovalRequest:
        repo = ExecutionRepository()
        repo.save_intent(intent.as_row())
        now = datetime.now(timezone.utc)
        request = ApprovalRequest.create(
            intent_id=intent.intent_id, proposal_id=intent.proposal_id,
            risk_decision_id=intent.risk_decision_id, execution_mode="live",
            proposal_hash="a" * 64, risk_hash="b" * 64, manifest_hash="c" * 64,
            account_seq=7, allowed_client_order_ids=["order-1"],
            discord_guild_id="1510267057885941840", discord_channel_id="1539250099999999999",
            allowed_approver_user_ids=["1537373837350404146"], requested_at=now,
        )
        repo.create_approval(request)
        return request

    def test_execution_approvals_projects_the_current_status(self) -> None:
        request = self._consumed_approval(self._live_intent())
        result = ReportingQueries(None).read("execution_approvals")
        self.assertEqual("ok", result.status)
        self.assertEqual(request.approval_id, result.rows[0]["approval_id"])
        self.assertEqual("pending", result.rows[0]["status"])

    def test_execution_orders_projects_ticker_and_status(self) -> None:
        intent = self._live_intent()
        repo = ExecutionRepository()
        repo.save_intent(intent.as_row())
        universe = FakeDatabase({("universe", "securities"): [{"security_id": 1, "ticker": "AAPL"}]})
        with patch("investment_agent.execution.db.sb", universe._client):
            repo.create_planned_order({
                "client_order_id": "order-1", "intent_id": intent.intent_id,
                "account_seq": 7, "ticker": "AAPL", "status": "planned",
            })
        result = ReportingQueries(None).read("execution_orders")
        self.assertEqual("ok", result.status)
        self.assertEqual("AAPL", result.rows[0]["ticker"])
        self.assertEqual("planned", result.rows[0]["status"])

    def test_execution_fills_projects_quantity_and_price(self) -> None:
        ExecutionRepository().save_fill({
            "broker_fill_id": "fill-1", "broker_order_id": "broker-1",
            "filled_at": datetime.now(timezone.utc).isoformat(), "quantity": 2, "price": 50,
        })
        result = ReportingQueries(None).read("execution_fills")
        self.assertEqual("ok", result.status)
        self.assertEqual(2, result.rows[0]["quantity"])
        self.assertEqual(50, result.rows[0]["price"])

    def test_current_model_stage_derives_from_approved_promotions(self) -> None:
        with runtime_connection() as connection:
            connection.execute(
                "INSERT INTO model_versions(artifact_id,algorithm,feature_version,artifact_uri,sha256) "
                "VALUES(?,?,?,?,?)",
                ("artifact-1", "ridge", "v1", "s3://bucket/artifact-1", "a" * 64),
            )
            connection.execute(
                "INSERT INTO model_promotions(artifact_id,from_stage,to_stage,status,evidence,approved_by,approved_at,confirmation_text) "
                "VALUES(?,?,?,?,?,?,?,?)",
                ("artifact-1", "shadow", "backtest", "approved", "{}", "operator-1",
                 "2026-09-01T00:00:00+00:00", "PROMOTE artifact-1 shadow->backtest"),
            )
        result = ReportingQueries(None).read("current_model_stage")
        self.assertEqual("ok", result.status)
        self.assertEqual("backtest", result.rows[0]["stage"])

    def test_security_decisions_resolves_ticker_through_the_canonical_db(self) -> None:
        with runtime_connection() as connection:
            connection.execute(
                "INSERT INTO policies(policy_key,policy_version,stage,model_provider,model_name,prompt_version,config) "
                "VALUES(?,?,?,?,?,?,?)",
                ("policy", 1, "shadow", "openai", "gpt", "v1", "{}"),
            )
            connection.execute(
                "INSERT INTO security_decisions(case_key,security_id,as_of_at,horizon_days,policy_key,"
                "policy_version,model_provider,model_name,source_kind,status,context_hash,final_decision) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                ("AAPL__2026-09-01__20d__v1", 7, "2026-09-01T00:00:00+00:00", 20, "policy", 1,
                 "openai", "gpt", "live_shadow", "completed", "a" * 64, json.dumps({"decision": "buy"})),
            )
        canonical = FakeDatabase({("universe", "securities"): [{"security_id": 7, "ticker": "AAPL"}]})
        result = ReportingQueries(canonical).read("security_decisions", equals={"ticker": "AAPL"})
        self.assertEqual("ok", result.status)
        self.assertEqual("AAPL", result.rows[0]["ticker"])

    def test_portfolio_decisions_joins_proposal_and_risk_state(self) -> None:
        with runtime_connection() as connection:
            connection.execute(
                "INSERT INTO policies(policy_key,policy_version,stage,model_provider,model_name,prompt_version,config) "
                "VALUES(?,?,?,?,?,?,?)",
                ("policy", 1, "shadow", "openai", "gpt", "v1", "{}"),
            )
            connection.execute(
                "INSERT INTO decision_runs(run_id,as_of_at,stage,status,candidate_tickers,finished_at) "
                "VALUES(?,?,?,?,?,?)",
                ("run-1", "2026-09-01T00:00:00+00:00", "shadow", "completed", json.dumps(["AAPL"]),
                 "2026-09-01T00:00:00+00:00"),
            )
            connection.execute(
                "INSERT INTO portfolio_proposals(proposal_id,run_id,source_type,source_version,stage,as_of_at,"
                "weights,confidence,reasoning) VALUES(?,?,?,?,?,?,?,?,?)",
                ("proposal-1", "run-1", "rule", "v1", "shadow", "2026-09-01T00:00:00+00:00",
                 json.dumps({"AAPL": 1.0}), 0.9, json.dumps(["reason"])),
            )
            connection.execute(
                "INSERT INTO risk_decisions(risk_decision_id,proposal_id,policy_key,policy_version,policy_hash,"
                "input_hash,is_approved,approved_weights,violations,decided_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("risk-1", "proposal-1", "policy", 1, "a" * 64, "b" * 64, False, None,
                 json.dumps(["limit"]), "2026-09-01T00:00:00+00:00"),
            )
            connection.execute(
                "INSERT INTO portfolio_decisions(decision_id,run_id,proposal_id,risk_decision_id,champion_policy,status) "
                "VALUES(?,?,?,?,?,?)",
                ("decision-1", "run-1", "proposal-1", "risk-1", json.dumps({}), "rejected"),
            )
        result = ReportingQueries(None).read("portfolio_decisions", equals={"run_id": "run-1"})
        self.assertEqual("ok", result.status)
        self.assertEqual(False, result.rows[0]["risk_approved"])
        self.assertEqual(["limit"], result.rows[0]["violations"])

    def test_notification_failures_joins_outbox_and_delivery_state(self) -> None:
        with runtime_connection() as connection:
            connection.execute(
                "INSERT INTO notification_outbox(producer,notification_key,kind,payload_json,status,attempt_count,claimed_at) "
                "VALUES(?,?,?,?,?,?,?)",
                ("macro", "key-1", "report", "{}", "failed", 1, "2026-09-01T00:00:00+00:00"),
            )
            connection.execute(
                "INSERT INTO notification_deliveries(producer,notification_key,status,failure_reason,attempted_at) "
                "VALUES(?,?,?,?,?)",
                ("macro", "key-1", "failed", "rate limited", "2026-09-01T00:00:00+00:00"),
            )
        result = ReportingQueries(None).read("notification_failures", equals={"producer": "macro"})
        self.assertEqual("ok", result.status)
        self.assertEqual("discord", result.rows[0]["channel"])
        self.assertEqual("rate limited", result.rows[0]["failure_reason"])

    def test_job_health_reports_seconds_since_success(self) -> None:
        now = datetime.now(timezone.utc)
        with runtime_connection() as connection:
            connection.execute(
                "INSERT INTO local_job_state(job_name,last_started_at,last_finished_at,last_status,detail) "
                "VALUES(?,?,?,?,?)",
                ("macro_refresh", now.isoformat(), now.isoformat(), "ok", "done"),
            )
        result = ReportingQueries(None).read("job_health")
        self.assertEqual("ok", result.status)
        self.assertEqual("macro_refresh", result.rows[0]["job_key"])
        self.assertGreaterEqual(result.rows[0]["seconds_since_success"], 0)
