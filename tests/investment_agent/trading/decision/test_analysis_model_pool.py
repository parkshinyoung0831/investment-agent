"""analysis의 모델 풀 재시도 배선 — 실제 TradingAgents/네트워크는 주입으로 뗀다."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from investment_agent.trading.decision.analysis import _select_and_run, failure_model
from investment_agent.trading.decision.model_pool import (
    CALLS_PER_TICKER_ESTIMATE, UNSTARTED_MODEL, UNSTARTED_PROVIDER,
    ModelCandidate, ModelPoolError, never_reached_a_model,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _candidate(name: str, *, api_key_env: str, daily_request_limit: int = 1000) -> ModelCandidate:
    return ModelCandidate(
        name=name, base_url="https://example.com/v1", model=name,
        provider="openai_compatible", tradingagents_provider="openai",
        api_key_env=api_key_env, daily_request_limit=daily_request_limit,
    )


class SelectAndRunTest(unittest.TestCase):
    def _ledger(self, temp: str) -> Path:
        return Path(temp) / "llm-model-usage.sqlite3"

    def test_first_candidate_success_is_returned_as_is(self):
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.dict(os.environ, {"KEY_A": "a"}, clear=False):
            pool = (_candidate("a", api_key_env="KEY_A"),)
            result, candidate = _select_and_run(
                object(), memory_text="", pool=pool, ledger_path=self._ledger(temp), runner=object(),
                attempt=lambda bundle, memory_text, runner: "ok",
            )
            self.assertEqual(result, "ok")
            self.assertEqual(candidate.name, "a")

    def test_a_failing_first_candidate_falls_over_to_the_second(self):
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.dict(os.environ, {"KEY_A": "a", "KEY_B": "b"}, clear=False):
            pool = (_candidate("a", api_key_env="KEY_A"), _candidate("b", api_key_env="KEY_B"))
            calls = []

            def attempt(bundle, memory_text, runner):
                calls.append(os.environ["AI_INVESTOR_MODEL"])
                if os.environ["AI_INVESTOR_MODEL"] == "a":
                    raise RuntimeError("boom")
                return "ok-b"

            result, candidate = _select_and_run(
                object(), memory_text="", pool=pool, ledger_path=self._ledger(temp), runner=object(),
                attempt=attempt,
            )
            self.assertEqual(result, "ok-b")
            self.assertEqual(candidate.name, "b")
            self.assertEqual(calls, ["a", "b"])

    def test_every_candidate_failing_raises_the_last_exception(self):
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.dict(os.environ, {"KEY_A": "a"}, clear=False):
            pool = (_candidate("a", api_key_env="KEY_A"),)

            def attempt(bundle, memory_text, runner):
                raise RuntimeError("always fails")

            with self.assertRaisesRegex(RuntimeError, "always fails"):
                _select_and_run(
                    object(), memory_text="", pool=pool, ledger_path=self._ledger(temp),
                    runner=object(), attempt=attempt,
                )

    def test_no_configured_candidate_raises_model_pool_error(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("KEY_A", None)
                pool = (_candidate("a", api_key_env="KEY_A"),)
                with self.assertRaises(ModelPoolError):
                    _select_and_run(
                        object(), memory_text="", pool=pool, ledger_path=self._ledger(temp),
                        runner=object(), attempt=lambda *a: "unreachable",
                    )

    def test_env_is_restored_after_a_successful_attempt(self):
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.dict(os.environ, {"KEY_A": "a", "AI_INVESTOR_MODEL": "outer"}, clear=False):
            pool = (_candidate("a", api_key_env="KEY_A"),)
            _select_and_run(
                object(), memory_text="", pool=pool, ledger_path=self._ledger(temp), runner=object(),
                attempt=lambda bundle, memory_text, runner: "ok",
            )
            self.assertEqual(os.environ["AI_INVESTOR_MODEL"], "outer")

    def test_a_model_that_only_has_room_for_one_ticker_is_not_retried_within_the_same_call(self):
        """예약은 시도 즉시 소진되므로 실패한 후보를 같은 종목 안에서 두 번 고르지 않는다."""
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.dict(os.environ, {"KEY_A": "a", "KEY_B": "b"}, clear=False):
            small = _candidate("small", api_key_env="KEY_A", daily_request_limit=CALLS_PER_TICKER_ESTIMATE)
            backup = _candidate("backup", api_key_env="KEY_B")
            seen = []

            def attempt(bundle, memory_text, runner):
                seen.append(os.environ["AI_INVESTOR_MODEL"])
                if os.environ["AI_INVESTOR_MODEL"] == "small":
                    raise RuntimeError("small failed")
                return "ok"

            _select_and_run(
                object(), memory_text="", pool=(small, backup), ledger_path=self._ledger(temp),
                runner=object(), attempt=attempt,
            )
            self.assertEqual(seen, ["small", "backup"])



class RuntimePreflightTest(unittest.TestCase):
    """환경 장애는 종목 실패로 쌓지 않고 회차 시작 전에 멈춘다."""

    def test_first_configured_candidate_that_passes_is_returned(self):
        import os
        from unittest import mock
        from investment_agent.trading.decision.analysis import verify_runtime

        pool = (_candidate("no-key", api_key_env="PREFLIGHT_MISSING"), _candidate("ok", api_key_env="PREFLIGHT_KEY"))
        calls = []
        with mock.patch.dict(os.environ, {"PREFLIGHT_KEY": "k"}):
            self.assertEqual(verify_runtime(pool, verify=lambda: calls.append(os.environ["AI_INVESTOR_API_KEY"])), "ok")
        self.assertEqual(calls, ["k"])

    def test_every_candidate_failing_raises_one_runtime_error(self):
        import os
        from unittest import mock
        from investment_agent.trading.decision.llm.runtime import TradingAgentsRuntimeError
        from investment_agent.trading.decision.analysis import verify_runtime

        def broken():
            raise TradingAgentsRuntimeError("connection failed")

        with mock.patch.dict(os.environ, {"PREFLIGHT_KEY": "k"}):
            with self.assertRaisesRegex(TradingAgentsRuntimeError, "connection failed"):
                verify_runtime((_candidate("ok", api_key_env="PREFLIGHT_KEY"),), verify=broken)

    def test_connection_failure_is_reported_as_a_runtime_error(self):
        import os
        from unittest import mock
        import httpx
        from investment_agent.trading.decision.llm import runtime as adapter

        with mock.patch.dict(os.environ, {"AI_INVESTOR_BASE_URL": "https://example.invalid", "AI_INVESTOR_API_KEY": "k"}), \
                mock.patch.object(httpx.Client, "get", side_effect=httpx.ConnectError("boom")):
            with self.assertRaises(adapter.TradingAgentsRuntimeError):
                adapter.verify_tradingagents_runtime()

    def test_rejected_credentials_stop_the_run(self):
        import os
        from unittest import mock
        import httpx
        from investment_agent.trading.decision.llm import runtime as adapter

        response = httpx.Response(401, request=httpx.Request("GET", "https://example.invalid/models"))
        with mock.patch.dict(os.environ, {"AI_INVESTOR_BASE_URL": "https://example.invalid", "AI_INVESTOR_API_KEY": "k"}), \
                mock.patch.object(httpx.Client, "get", return_value=response):
            with self.assertRaisesRegex(adapter.TradingAgentsRuntimeError, "401"):
                adapter.verify_tradingagents_runtime()

    def test_main_checks_the_runtime_before_analysing_any_ticker(self):
        # main()은 Supabase를 읽어 단위 테스트로 돌리기 어렵다. 확인 호출이 종목 루프보다 앞에 있는지 구조로 본다.
        import ast
        import inspect
        from investment_agent.trading.decision import analysis

        tree = ast.parse(inspect.getsource(analysis.main))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        lines = {node.func.id: node.lineno for node in sorted(calls, key=lambda node: node.lineno)
                 if node.func.id in {"verify_runtime", "_select_and_run"}}
        self.assertIn("verify_runtime", lines)
        self.assertLess(lines["verify_runtime"], lines["_select_and_run"])



class AnalysisBudgetTest(unittest.TestCase):
    """고르는 종목 수를 남은 모델 예산과 시간에 맞춰, 판단 없이 회차를 붙잡는 종목을 만들지 않는다."""

    def test_limit_is_the_smaller_of_request_and_remaining_budget(self):
        from investment_agent.trading.decision.analysis import analysis_limit

        self.assertEqual(analysis_limit(250, remaining_budget=20), 20)
        self.assertEqual(analysis_limit(5, remaining_budget=20), 5)
        self.assertEqual(analysis_limit(250, remaining_budget=0), 0)

    def test_next_ticker_starts_only_if_the_longest_case_still_fits(self):
        from investment_agent.trading.decision.analysis import should_start_next

        self.assertTrue(should_start_next(elapsed_seconds=0, longest_case_seconds=0, max_runtime_seconds=100))
        self.assertTrue(should_start_next(elapsed_seconds=60, longest_case_seconds=40, max_runtime_seconds=100))
        self.assertFalse(should_start_next(elapsed_seconds=61, longest_case_seconds=40, max_runtime_seconds=100))
        self.assertTrue(should_start_next(elapsed_seconds=10_000, longest_case_seconds=500, max_runtime_seconds=None))

    def test_remaining_budget_reads_usage_without_reserving(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock
        from investment_agent.platform.external_usage import reserve_provider_call
        from investment_agent.trading.decision.model_pool import remaining_ticker_budget

        pool = (_candidate("m1", api_key_env="BUDGET_KEY", daily_request_limit=150),
                _candidate("m2", api_key_env="BUDGET_MISSING", daily_request_limit=150))
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"BUDGET_KEY": "k"}):
            ledger = Path(directory) / "usage.sqlite3"
            self.assertEqual(remaining_ticker_budget(pool, ledger_path=ledger), 10)
            for _ in range(3):
                reserve_provider_call(ledger, provider="m1", cap=10)
            self.assertEqual(remaining_ticker_budget(pool, ledger_path=ledger), 7)
            self.assertEqual(remaining_ticker_budget(pool, ledger_path=ledger), 7)

    def test_harness_passes_a_runtime_budget_below_its_timeout(self):
        from datetime import datetime, timezone
        from threading import Event
        from investment_agent.operations.harness.commands import CommandResult
        from investment_agent.operations.harness.contracts import StageContext
        from investment_agent.operations.harness_adapters import ProductionInvestmentAdapters

        commands = []

        class Runner:
            def run(self, command, *, stop_event):
                commands.append(command)
                return CommandResult(command.module, 0, 0.0)

        class Repo:
            def signal_batch_id_for_as_of(self, *, as_of_at):
                return "signal_batch_" + "a" * 24

        adapters = ProductionInvestmentAdapters(
            command_runner=Runner(), decision_repository=Repo(), approval_repository=None,
            system_store=None, follow_target=lambda **k: None, create_execution_intent=lambda **k: None,
            timeouts={"analysis": 1000},
        )
        now = datetime(2026, 9, 14, tzinfo=timezone.utc)
        adapters.analysis(StageContext(job_id="j", run_id="r", stage_id="analysis", attempt=1, idempotency_key="k",
                                       now=now, stop_event=Event(), prior_metadata={}, completed_metadata={}))
        arguments = commands[0].arguments
        runtime = float(arguments[arguments.index("--max-runtime-seconds") + 1])
        self.assertLess(runtime, commands[0].timeout_seconds)

    def test_main_wires_budget_time_limit_and_attempted_symbols(self):
        import ast
        import inspect
        from investment_agent.trading.decision import analysis

        tree = ast.parse(inspect.getsource(analysis.main))
        called = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertTrue({"analysis_limit", "remaining_ticker_budget", "should_start_next"} <= called)
        batch = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name) and node.func.id == "SignalBatch")
        requested = next(keyword.value for keyword in batch.keywords if keyword.arg == "requested_symbols")
        self.assertEqual(ast.unparse(requested), "tuple(attempted)")


class NothingDueTest(unittest.TestCase):
    def test_no_candidates_due_ends_the_run_without_a_batch(self):
        import ast
        import inspect
        from investment_agent.trading.decision import analysis

        tree = ast.parse(inspect.getsource(analysis.main))
        handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)
                    and isinstance(node.type, ast.Name) and node.type.id == "NoCandidatesDue"]
        self.assertEqual(len(handlers), 1)
        self.assertEqual(ast.unparse(handlers[0].body[-1]), "return 0")


class BudgetExhaustionTest(unittest.TestCase):
    def test_budget_exhaustion_leaves_the_ticker_unattempted_not_failed(self):
        import ast
        import inspect
        from investment_agent.trading.decision import analysis

        tree = ast.parse(inspect.getsource(analysis.main))
        handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)
                    and isinstance(node.type, ast.Name) and node.type.id == "ModelPoolError"]
        self.assertEqual(len(handlers), 1)
        body = ast.unparse(handlers[0])
        self.assertIn("attempted.pop()", body)
        self.assertNotIn("save_case", body)

    def test_harness_marks_a_run_without_a_batch_as_skipped(self):
        from datetime import datetime, timezone
        from threading import Event
        from investment_agent.operations.harness.commands import CommandResult
        from investment_agent.operations.harness.contracts import StageContext
        from investment_agent.operations.harness_adapters import ProductionInvestmentAdapters

        class Runner:
            def run(self, command, *, stop_event):
                return CommandResult(command.module, 0, 0.0)

        class Repo:
            def signal_batch_id_for_as_of(self, *, as_of_at):
                raise LookupError("no batch")

        adapters = ProductionInvestmentAdapters(
            command_runner=Runner(), decision_repository=Repo(), approval_repository=None,
            system_store=None, follow_target=lambda **k: None, create_execution_intent=lambda **k: None,
        )
        now = datetime(2026, 9, 14, tzinfo=timezone.utc)
        outcome = adapters.analysis(StageContext(job_id="j", run_id="r", stage_id="analysis", attempt=1,
                                                 idempotency_key="k", now=now, stop_event=Event(),
                                                 prior_metadata={}, completed_metadata={}))
        self.assertEqual(outcome.status, "skipped")
        self.assertEqual(outcome.metadata["reason"], "no_signal_batch")


class FailureModelTest(unittest.TestCase):
    def test_a_failure_after_the_model_answered_names_that_model(self):
        from investment_agent.trading.decision.analysis import failure_model

        self.assertEqual(("openai_compatible", "m1"), failure_model(_candidate("m1", api_key_env="K")))

    def test_no_candidate_means_the_pool_was_exhausted(self):
        from investment_agent.trading.decision.analysis import failure_model

        self.assertEqual(("model_pool", "exhausted"), failure_model(None))

    def test_main_records_failures_through_failure_model(self):
        """main이 (provider, model)을 직접 짓지 않고 failure_model을 거치는가."""
        import inspect
        from investment_agent.trading.decision import analysis

        source = inspect.getsource(analysis.main)
        self.assertIn("failure_model(", source)
        self.assertNotIn('"exhausted"', source)

    def test_main_falls_back_to_the_candidate_the_exception_carries(self):
        """`_select_and_run`이 도중에 실패하면 지역 candidate는 None이다.

        그 경우까지 `failure_model(None)`로 보내면 모델이 답한 실패도 '시작 못 함'으로
        기록되고, 후보 선정이 그 행을 보고 잘못된 억제 판정을 한다.
        """
        import inspect
        from investment_agent.trading.decision import analysis

        source = inspect.getsource(analysis.main)
        self.assertIn('getattr(exc, "model_candidate", None)', source)



class FailureAttributionTest(unittest.TestCase):
    """실패를 원장에 적을 때 어떤 모델이 관여했는지가 정확해야 한다.

    `failure_model`이 모두 `exhausted`로 적으면 후보 선정이 "판단을 받은 적 없는 종목"과
    "모델이 답한 뒤 실패한 종목"을 구분하지 못한다. 실측(2026-09-22)에서 모델이 제안까지
    만든 ContractError 실패도 `exhausted`로 기록돼 있었다.
    """

    def test_a_failure_after_a_model_answered_names_that_model(self):
        with tempfile.TemporaryDirectory() as temp,              mock.patch.dict(os.environ, {"KEY_A": "a"}, clear=False):
            pool = (_candidate("a", api_key_env="KEY_A"),)

            def boom(bundle, memory_text, runner):
                raise RuntimeError("proposal cites unknown evidence")

            with self.assertRaises(RuntimeError) as caught:
                _select_and_run(
                    object(), memory_text="", pool=pool,
                    ledger_path=Path(temp) / "ledger.sqlite3", runner=object(), attempt=boom,
                )
            self.assertEqual("a", caught.exception.model_candidate.name)
            self.assertEqual(
                ("openai_compatible", "a"), failure_model(caught.exception.model_candidate)
            )

    def test_never_getting_a_candidate_is_recorded_as_unstarted(self):
        """키가 없어 후보를 못 얻으면 모델에 닿지 못한 것이다 — 그 종목을 억제하면 안 된다."""
        with tempfile.TemporaryDirectory() as temp,              mock.patch.dict(os.environ, {}, clear=True):
            pool = (_candidate("a", api_key_env="MISSING_KEY"),)
            with self.assertRaises(ModelPoolError):
                _select_and_run(
                    object(), memory_text="", pool=pool,
                    ledger_path=Path(temp) / "ledger.sqlite3", runner=object(),
                    attempt=lambda bundle, memory_text, runner: "ok",
                )
        self.assertEqual((UNSTARTED_PROVIDER, UNSTARTED_MODEL), failure_model(None))
        self.assertTrue(never_reached_a_model(UNSTARTED_PROVIDER, UNSTARTED_MODEL))
        self.assertFalse(never_reached_a_model("openai_compatible", "azure-gpt-5-mini"))

if __name__ == "__main__":
    unittest.main()
