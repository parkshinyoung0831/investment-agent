"""LLM 계측 — 없으면 provider 비교의 근거가 통째로 없다.

`INVESTMENT_DECISION_ENGINE_DESIGN.md` §50이 요구하는 값들이고, 계측 전에는
비용·지연 수치를 문서에 적지 않는다는 규칙(§49)의 전제다.
"""
from __future__ import annotations

import unittest

from investment_agent.trading.decision.llm.usage import CallUsage, UsageLedger


class CallUsageTest(unittest.TestCase):
    def test_tokens_come_from_the_provider_usage_block(self):
        call = CallUsage.from_response(
            task_name="analyst",
            latency_ms=120.0,
            body={"usage": {"prompt_tokens": 1500, "completion_tokens": 300}},
        )
        self.assertEqual(1500, call.input_tokens)
        self.assertEqual(300, call.output_tokens)
        self.assertTrue(call.has_token_counts)

    def test_a_missing_usage_block_leaves_tokens_unknown_not_zero(self):
        """0으로 적으면 '안 썼다'와 '모르겠다'가 같은 값이 되어 비용을 과소 추정한다."""
        call = CallUsage.from_response(task_name="analyst", latency_ms=1.0, body={"choices": []})
        self.assertIsNone(call.input_tokens)
        self.assertIsNone(call.output_tokens)
        self.assertFalse(call.has_token_counts)

    def test_a_nonsense_token_count_is_unknown(self):
        for value in ("many", -5, None, True):
            with self.subTest(value=value):
                call = CallUsage.from_response(
                    task_name="analyst", latency_ms=1.0,
                    body={"usage": {"prompt_tokens": value, "completion_tokens": 10}},
                )
                self.assertIsNone(call.input_tokens)

    def test_latency_must_be_finite_and_non_negative(self):
        for bad in (-1.0, float("nan"), float("inf")):
            with self.subTest(latency=bad):
                with self.assertRaises(ValueError):
                    CallUsage(task_name="analyst", latency_ms=bad)


class UsageLedgerTest(unittest.TestCase):
    @staticmethod
    def _ledger(*calls: CallUsage) -> UsageLedger:
        ledger = UsageLedger()
        for call in calls:
            ledger.record(call)
        return ledger

    def test_it_sums_requests_and_tokens_across_calls(self):
        ledger = self._ledger(
            CallUsage("market_analyst", 100.0, 1000, 200),
            CallUsage("news_analyst", 200.0, 1200, 250),
        )
        self.assertEqual(2, ledger.requests)
        self.assertEqual(2200, ledger.input_tokens)
        self.assertEqual(450, ledger.output_tokens)
        self.assertTrue(ledger.is_complete)

    def test_an_incomplete_ledger_says_so(self):
        """합계가 하한이라는 사실을 지우면 나중에 비용을 조용히 과소 추정한다."""
        ledger = self._ledger(
            CallUsage("market_analyst", 100.0, 1000, 200),
            CallUsage("news_analyst", 200.0),
        )
        self.assertFalse(ledger.is_complete)
        self.assertEqual(1, ledger.requests_without_usage)
        self.assertEqual(1000, ledger.input_tokens)
        self.assertFalse(ledger.to_metadata()["tokens_are_complete"])

    def test_percentiles_return_an_observed_value(self):
        ledger = self._ledger(*(CallUsage(f"t{i}", float(i)) for i in (10, 20, 30, 40)))
        self.assertEqual(20.0, ledger.latency_ms_percentile(0.50))
        self.assertEqual(40.0, ledger.latency_ms_percentile(0.95))
        self.assertEqual(40.0, ledger.latency_ms_percentile(1.0))

    def test_an_empty_ledger_is_not_complete(self):
        """호출이 없었던 것을 '토큰을 다 안다'로 적으면 안 된다."""
        self.assertFalse(UsageLedger().is_complete)
        self.assertEqual(0, UsageLedger().requests)

    def test_metadata_counts_calls_per_task(self):
        ledger = self._ledger(
            CallUsage("bull", 10.0, 1, 1),
            CallUsage("bear", 10.0, 1, 1),
            CallUsage("bull", 10.0, 1, 1),
        )
        self.assertEqual({"bear": 1, "bull": 2}, ledger.to_metadata()["by_task"])


class ClientRecordsUsageTest(unittest.TestCase):
    """client가 실제로 계측을 남기는가. 남기지 않으면 §50이 통째로 빈다."""

    def test_a_successful_call_records_one_measurement(self):
        import httpx
        from unittest import mock
        from investment_agent.trading.decision.llm.client import OpenAICompatibleClient

        client = OpenAICompatibleClient(base_url="https://example.com/v1", model="m")
        body = {
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 800, "completion_tokens": 40},
        }
        response = mock.Mock(spec=httpx.Response)
        response.raise_for_status.return_value = None
        response.json.return_value = body
        with mock.patch.object(httpx.Client, "post", return_value=response):
            self.assertEqual({"ok": True}, client.complete_json(
                system="s", user="u", output_schema={}, task_name="probe",
            ))
        self.assertEqual(1, client.usage.requests)
        self.assertEqual(800, client.usage.input_tokens)
        self.assertEqual(40, client.usage.output_tokens)
        self.assertEqual({"probe": 1}, client.usage.to_metadata()["by_task"])


class RunTotalTest(unittest.TestCase):
    def test_an_incomplete_ticker_makes_the_run_total_incomplete(self):
        from investment_agent.trading.decision.analysis import run_usage_total

        total = run_usage_total([
            {"requests": 14, "input_tokens": 100, "output_tokens": 10,
             "tokens_are_complete": True, "latency_ms_total": 1000.0},
            {"requests": 14, "input_tokens": 90, "output_tokens": 9,
             "tokens_are_complete": False, "latency_ms_total": 900.0},
        ])
        self.assertEqual(2, total["tickers"])
        self.assertEqual(28, total["requests"])
        self.assertEqual(14.0, total["requests_per_ticker"])
        self.assertEqual(190, total["input_tokens"])
        self.assertFalse(total["tokens_are_complete"])

    def test_no_tickers_is_not_a_zero_cost_claim(self):
        from investment_agent.trading.decision.analysis import run_usage_total

        self.assertEqual({"tickers": 0}, run_usage_total([]))


if __name__ == "__main__":
    unittest.main()
