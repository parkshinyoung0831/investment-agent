"""LLM 모델 풀 — 종목당 하루 예산을 원자적으로 예약하고, 소진되면 다음 모델로 넘어간다."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from investment_agent.trading.decision.model_pool import (
    CALLS_PER_TICKER_ESTIMATE,
    ModelCandidate,
    ModelPoolError,
    apply_candidate,
    select_model_for_ticker,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _candidate(name: str, *, daily_request_limit: int, api_key_env: str = "TEST_KEY") -> ModelCandidate:
    return ModelCandidate(
        name=name,
        base_url="https://example.com/v1",
        model=name,
        provider="openai_compatible",
        tradingagents_provider="openai",
        api_key_env=api_key_env,
        daily_request_limit=daily_request_limit,
    )


class SelectModelForTickerTest(unittest.TestCase):
    def _ledger(self, temp: str) -> Path:
        return Path(temp) / "llm-model-usage.sqlite3"

    def test_picks_the_first_candidate_with_room_today(self):
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.dict(os.environ, {"TEST_KEY": "k"}, clear=False):
            pool = (_candidate("a", daily_request_limit=1000), _candidate("b", daily_request_limit=1000))
            picked = select_model_for_ticker(pool, ledger_path=self._ledger(temp), now=NOW)
            self.assertEqual(picked.name, "a")

    def test_exhausted_daily_budget_moves_to_the_next_candidate(self):
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.dict(os.environ, {"TEST_KEY": "k"}, clear=False):
            ledger = self._ledger(temp)
            # 하루 요청 한도가 종목당 예상 호출수보다 작으면 그 모델의 오늘치 종목 배정은 0이다.
            tiny = _candidate("tiny", daily_request_limit=CALLS_PER_TICKER_ESTIMATE - 1)
            roomy = _candidate("roomy", daily_request_limit=1000)
            picked = select_model_for_ticker((tiny, roomy), ledger_path=ledger, now=NOW)
            self.assertEqual(picked.name, "roomy")

    def test_a_model_used_up_across_many_tickers_is_skipped_afterward(self):
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.dict(os.environ, {"TEST_KEY": "k"}, clear=False):
            ledger = self._ledger(temp)
            # 종목 1개만 태울 수 있는 예산.
            small = _candidate("small", daily_request_limit=CALLS_PER_TICKER_ESTIMATE)
            backup = _candidate("backup", daily_request_limit=1000)
            first = select_model_for_ticker((small, backup), ledger_path=ledger, now=NOW)
            second = select_model_for_ticker((small, backup), ledger_path=ledger, now=NOW)
            self.assertEqual(first.name, "small")
            self.assertEqual(second.name, "backup")

    def test_budget_resets_on_a_new_utc_day(self):
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.dict(os.environ, {"TEST_KEY": "k"}, clear=False):
            ledger = self._ledger(temp)
            small = _candidate("small", daily_request_limit=CALLS_PER_TICKER_ESTIMATE)
            select_model_for_ticker((small,), ledger_path=ledger, now=NOW)
            tomorrow = select_model_for_ticker((small,), ledger_path=ledger, now=NOW + timedelta(days=1))
            self.assertEqual(tomorrow.name, "small")

    def test_a_candidate_without_its_api_key_configured_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            # TEST_KEY를 일부러 비워 둔다 — 그 provider는 아직 준비되지 않은 상태다.
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("TEST_KEY", None)
                unset = _candidate("unset", daily_request_limit=1000)
                backup = _candidate("backup", daily_request_limit=1000, api_key_env="OTHER_KEY")
                os.environ["OTHER_KEY"] = "k"
                picked = select_model_for_ticker((unset, backup), ledger_path=self._ledger(temp), now=NOW)
                self.assertEqual(picked.name, "backup")

    def test_every_candidate_exhausted_or_unconfigured_returns_none(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("TEST_KEY", None)
                unset = _candidate("unset", daily_request_limit=1000)
                self.assertIsNone(
                    select_model_for_ticker((unset,), ledger_path=self._ledger(temp), now=NOW)
                )

    def test_excluded_candidates_are_skipped_even_with_budget_left(self):
        with tempfile.TemporaryDirectory() as temp,              mock.patch.dict(os.environ, {"TEST_KEY": "k"}, clear=False):
            pool = (_candidate("a", daily_request_limit=1000), _candidate("b", daily_request_limit=1000))
            picked = select_model_for_ticker(
                pool, ledger_path=self._ledger(temp), now=NOW, exclude=frozenset({"a"}),
            )
            self.assertEqual(picked.name, "b")

class ApplyCandidateTest(unittest.TestCase):
    def test_sets_and_restores_every_env_var_it_touches(self):
        candidate = _candidate("m", daily_request_limit=100, api_key_env="TEST_KEY")
        keys = (
            "AI_INVESTOR_PROVIDER", "AI_INVESTOR_BASE_URL", "AI_INVESTOR_MODEL",
            "AI_INVESTOR_QUICK_MODEL", "AI_INVESTOR_DEEP_MODEL", "AI_INVESTOR_API_KEY",
            "AI_INVESTOR_TRADINGAGENTS_PROVIDER",
        )
        with mock.patch.dict(os.environ, {"TEST_KEY": "secret", **{k: "before" for k in keys}}, clear=False):
            with apply_candidate(candidate):
                self.assertEqual(os.environ["AI_INVESTOR_MODEL"], "m")
                self.assertEqual(os.environ["AI_INVESTOR_QUICK_MODEL"], "m")
                self.assertEqual(os.environ["AI_INVESTOR_API_KEY"], "secret")
            self.assertEqual(os.environ["AI_INVESTOR_MODEL"], "before")
            self.assertEqual(os.environ["AI_INVESTOR_API_KEY"], "before")

    def test_restores_even_when_the_body_raises(self):
        candidate = _candidate("m", daily_request_limit=100, api_key_env="TEST_KEY")
        with mock.patch.dict(os.environ, {"TEST_KEY": "secret", "AI_INVESTOR_MODEL": "before"}, clear=False):
            with self.assertRaises(RuntimeError):
                with apply_candidate(candidate):
                    raise RuntimeError("boom")
            self.assertEqual(os.environ["AI_INVESTOR_MODEL"], "before")

    def test_missing_api_key_fails_closed_rather_than_sending_an_unauthenticated_request(self):
        candidate = _candidate("m", daily_request_limit=100, api_key_env="MISSING_KEY_XYZ")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MISSING_KEY_XYZ", None)
            with self.assertRaises(ModelPoolError):
                with apply_candidate(candidate):
                    pass


if __name__ == "__main__":
    unittest.main()
