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

    def test_reasoning_and_cached_tokens_come_from_the_details_blocks(self):
        """output이 왜 비싼지(reasoning), 캐시가 걸렸는지(cached)는 details에만 있다."""
        call = CallUsage.from_response(
            task_name="analyst", latency_ms=1.0,
            body={"usage": {
                "prompt_tokens": 1500, "completion_tokens": 300,
                "prompt_tokens_details": {"cached_tokens": 1024},
                "completion_tokens_details": {"reasoning_tokens": 192},
            }},
        )
        self.assertEqual(192, call.reasoning_tokens)
        self.assertEqual(1024, call.cached_input_tokens)

    def test_missing_details_are_unknown_not_zero(self):
        """cached 0은 '캐시가 안 걸렸다'이고, details가 없는 것은 '모른다'다. 둘을 섞지 않는다."""
        call = CallUsage.from_response(
            task_name="analyst", latency_ms=1.0,
            body={"usage": {"prompt_tokens": 10, "completion_tokens": 1}},
        )
        self.assertIsNone(call.reasoning_tokens)
        self.assertIsNone(call.cached_input_tokens)
        zero = CallUsage.from_response(
            task_name="analyst", latency_ms=1.0,
            body={"usage": {"prompt_tokens": 10, "completion_tokens": 1,
                            "prompt_tokens_details": {"cached_tokens": 0}}},
        )
        self.assertEqual(0, zero.cached_input_tokens)

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


    def test_tokens_are_broken_down_by_task(self):
        """역할별 호출 수만으로는 어느 역할을 줄여야 하는지 모른다."""
        ledger = self._ledger(
            CallUsage("bull", 10.0, 100, 10, 5, 0),
            CallUsage("bull", 10.0, 200, 20, 7, 64),
            CallUsage("bear", 10.0, 50, 5),
        )
        by_task = ledger.to_metadata()["tokens_by_task"]
        self.assertEqual({"input_tokens": 300, "output_tokens": 30, "reasoning_tokens": 12,
                          "cached_input_tokens": 64}, by_task["bull"])
        self.assertEqual({"input_tokens": 50, "output_tokens": 5, "reasoning_tokens": None,
                          "cached_input_tokens": None}, by_task["bear"])

    def test_detail_totals_say_when_they_are_a_lower_bound(self):
        ledger = self._ledger(
            CallUsage("bull", 10.0, 100, 10, 5, 0),
            CallUsage("bear", 10.0, 50, 5),
        )
        metadata = ledger.to_metadata()
        self.assertEqual(5, metadata["reasoning_tokens"])
        self.assertEqual(1, metadata["requests_without_token_details"])
        self.assertIsNone(UsageLedger().to_metadata()["reasoning_tokens"])


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

    def test_the_run_total_carries_reasoning_and_cache_with_completeness(self):
        from investment_agent.trading.decision.analysis import run_usage_total

        total = run_usage_total([
            {"requests": 14, "reasoning_tokens": 700, "cached_input_tokens": 9000,
             "requests_without_token_details": 0, "tokens_are_complete": True},
            {"requests": 14, "reasoning_tokens": None, "cached_input_tokens": None,
             "requests_without_token_details": 14, "tokens_are_complete": True},
        ])
        self.assertEqual(700, total["reasoning_tokens"])
        self.assertEqual(9000, total["cached_input_tokens"])
        self.assertFalse(total["token_details_are_complete"])

    def test_no_tickers_is_not_a_zero_cost_claim(self):
        from investment_agent.trading.decision.analysis import run_usage_total

        self.assertEqual({"tickers": 0}, run_usage_total([]))


if __name__ == "__main__":
    unittest.main()
