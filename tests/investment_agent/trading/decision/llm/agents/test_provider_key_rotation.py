"""후보를 갈아탈 때 앞 후보의 API 키가 남으면 다음 후보가 그 키로 호출된다.

실측 2026-09-03: Azure 시도가 OPENAI_API_KEY를 채운 뒤 Gemini 후보로 넘어가자
Gemini가 Azure 키를 받아 400 "Please pass a valid API key"를 냈다.

`_config()`를 직접 부르지 않는다 — 그건 선택 의존성 `tradingagents`를 import하므로
CI(오프라인 단위 테스트)에서는 설치돼 있지 않다. 검증 대상은 키 결정과 재시도
예산이고, 둘 다 그 의존성 없이 판정할 수 있다.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from investment_agent.trading.decision.llm.agents.tradingagents_adapter import (
    _llm_max_retries,
    apply_downstream_api_key,
)


class ProviderKeyRotationTest(unittest.TestCase):
    def test_second_candidate_key_replaces_the_first(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)

            apply_downstream_api_key("openai", "azure-key")
            first = os.environ.get("OPENAI_API_KEY")
            apply_downstream_api_key("openai", "gemini-key")
            second = os.environ.get("OPENAI_API_KEY")

        self.assertEqual(first, "azure-key")
        self.assertEqual(second, "gemini-key")

    def test_each_provider_writes_its_own_variable(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            self.assertEqual(apply_downstream_api_key("openai", "k"), "OPENAI_API_KEY")
            self.assertEqual(apply_downstream_api_key("google", "k"), "GEMINI_API_KEY")
            self.assertEqual(apply_downstream_api_key("anthropic", "k"), "ANTHROPIC_API_KEY")

    def test_an_unknown_provider_writes_nothing(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            self.assertIsNone(apply_downstream_api_key("openai_compatible", "k"))

    def test_a_blank_key_does_not_clobber_an_existing_one(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "kept"}, clear=False):
            self.assertIsNone(apply_downstream_api_key("openai", "   "))
            self.assertEqual(os.environ["OPENAI_API_KEY"], "kept")


class RetryBudgetTest(unittest.TestCase):
    """Azure 배포는 429에 Retry-After 10~15초를 준다. SDK 기본 2회로는 못 견딘다."""

    def test_default_covers_a_full_rate_limit_window(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_INVESTOR_LLM_MAX_RETRIES", None)
            self.assertGreaterEqual(_llm_max_retries(), 5)

    def test_it_is_configurable(self):
        with mock.patch.dict(os.environ, {"AI_INVESTOR_LLM_MAX_RETRIES": "3"}, clear=False):
            self.assertEqual(_llm_max_retries(), 3)

    def test_an_out_of_range_value_is_rejected(self):
        with mock.patch.dict(os.environ, {"AI_INVESTOR_LLM_MAX_RETRIES": "99"}, clear=False):
            with self.assertRaises(RuntimeError):
                _llm_max_retries()


if __name__ == "__main__":
    unittest.main()
