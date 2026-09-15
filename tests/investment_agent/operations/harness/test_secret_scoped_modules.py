"""LLM을 부르는 모듈은 실행 범위에 들어가지 않고, 진입 감시는 시세를 실행 범위에서 따로 받는다."""
from __future__ import annotations

import ast
import tempfile
import unittest
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from threading import Event

from investment_agent.operations.commands.capture_toss_quotes import capture, read_quotes
from investment_agent.operations.harness.commands import CommandResult
from investment_agent.operations.harness.contracts import StageContext
from investment_agent.operations.harness_adapters import EXECUTION_MODULES, _MODULES, ProductionInvestmentAdapters
from investment_agent.operations.harness.market_schedule import SessionWindow

ROOT = Path(__file__).resolve().parents[4] / "src"
NOW = datetime(2026, 9, 14, 15, 0, tzinfo=timezone.utc)
# 이 이름을 import하는 모듈은 LLM 판단을 부른다.
LLM_MARKERS = ("trading.decision.llm", "trading.decision.portfolio_shadow", "OpenAICompatibleClient")


class _Runner:
    def __init__(self):
        self.modules: list[tuple[str, tuple[str, ...]]] = []

    def run(self, command, *, stop_event):
        self.modules.append((command.module, command.arguments))
        return CommandResult(command.module, 0, 0.0)


class SecretScopedModulesTest(unittest.TestCase):
    def test_execution_modules_never_import_llm_decision_code(self):
        self.assertTrue(EXECUTION_MODULES <= _MODULES)
        for module in sorted(EXECUTION_MODULES):
            source = (ROOT / (module.replace(".", "/") + ".py")).read_text(encoding="utf-8")
            imports = " ".join(
                (getattr(node, "module", None) or "") + " " + " ".join(alias.name for alias in node.names)
                for node in ast.walk(ast.parse(source)) if isinstance(node, (ast.Import, ast.ImportFrom))
            )
            for marker in LLM_MARKERS:
                self.assertNotIn(marker, imports, module)

    def test_llm_modules_stay_in_the_analysis_scope(self):
        for module in ("investment_agent.operations.commands.watch_entries",
                       "investment_agent.trading.decision.portfolio_shadow",
                       "investment_agent.operations.commands.event_reanalysis"):
            self.assertIn(module, _MODULES)
            self.assertNotIn(module, EXECUTION_MODULES)

    def test_entry_watch_captures_quotes_in_execution_scope_before_the_llm_review(self):
        runner = _Runner()
        adapters = ProductionInvestmentAdapters(
            command_runner=runner, decision_repository=None, approval_repository=None,
            construct_portfolio=lambda **kwargs: None, create_execution_intent=lambda **kwargs: None,
            now=lambda: NOW, session_window=SessionWindow(start=time(0, 1), end=time(23, 59)),
        )
        context = StageContext(job_id="entry_watch", run_id="run", stage_id="watch", attempt=1,
                               idempotency_key="k", now=NOW, stop_event=Event(), prior_metadata={}, completed_metadata={})
        adapters.watch_entries(context)
        modules = [module for module, _ in runner.modules]
        self.assertEqual(modules, ["investment_agent.operations.commands.capture_toss_quotes",
                                   "investment_agent.operations.commands.watch_entries"])
        self.assertIn(modules[0], EXECUTION_MODULES)
        quote_path = runner.modules[0][1][1]
        self.assertEqual(runner.modules[1][1], ("--quotes", quote_path))


class QuoteFileTest(unittest.TestCase):
    def test_quotes_round_trip_with_their_broker_timestamps(self):
        stamp = (NOW - timedelta(seconds=5)).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "q.json"
            count = capture(path, symbols={"AAPL"}, now=NOW,
                            fetch=lambda symbols: ({"AAPL": 200.5}, {"AAPL": stamp}))
            self.assertEqual(count, 1)
            self.assertEqual(read_quotes(path), {"AAPL": (200.5, stamp)})

    def test_no_symbols_writes_an_empty_file_without_calling_the_broker(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "q.json"
            capture(path, symbols=set(), now=NOW, fetch=lambda symbols: self.fail("broker called"))
            self.assertEqual(read_quotes(path), {})


if __name__ == "__main__":
    unittest.main()
