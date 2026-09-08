"""portfolio_shadow의 모델 풀 재시도 배선 — 실제 TradingAgents/네트워크는 주입으로 뗀다."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from investment_agent.trading.decision.portfolio_shadow import _select_and_run
from investment_agent.trading.decision.model_pool import CALLS_PER_TICKER_ESTIMATE, ModelCandidate, ModelPoolError

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


if __name__ == "__main__":
    unittest.main()
