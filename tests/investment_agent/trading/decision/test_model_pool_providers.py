"""풀에 있는 후보가 실제로 호출 가능하고, 실제 프롬프트 크기를 견디는지 못박는다.

실측 2026-09-03 (도구 호출 2턴 + 실제 evidence bundle 크기로 시험):

| provider | 모델                   | 도구 호출 | 실제 프롬프트 | 한도 |
|----------|------------------------|-----------|---------------|------|
| azure    | gpt-5-mini             | OK        | 31,894토큰 OK | 이 리소스의 유일한 배포 |
| gemini   | gemini-2.5-flash       | OK        | 429           | 무료 250k TPM |
| groq     | openai/gpt-oss-20b     | OK        | 413           | **무료 TPM 8,000** |
| groq     | groq/compound-mini     | 미지원    | -             | tool calling 불가 |
| azure    | 그 밖의 카탈로그 모델  | -         | -             | DeploymentNotFound(404) |

Azure `/models`는 배포 목록이 아니라 지역 카탈로그(407개)라 목록에 있다고 부를 수 있는 게 아니다.
"""
from __future__ import annotations

import unittest

from investment_agent.trading.decision.model_pool import (
    CALLS_PER_TICKER_ESTIMATE,
    DEFAULT_POOL,
    GROQ_FREE_TIER_TPM,
    groq_candidate,
)


class AzureCandidateTest(unittest.TestCase):
    def _azure(self):
        found = [c for c in DEFAULT_POOL if c.api_key_env == "AI_INVESTOR_AZURE_API_KEY"]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_azure_uses_the_only_model_actually_deployed(self):
        self.assertEqual(self._azure().model, "gpt-5-mini")

    def test_undeployed_catalog_models_are_not_in_the_pool(self):
        """카탈로그에만 있는 이름을 넣으면 매번 404를 맞고 후보 하나를 낭비한다."""
        names = {c.model for c in DEFAULT_POOL}
        for absent in ("DeepSeek-V4-Flash", "gpt-4.1-nano", "gpt-5-nano", "gpt-4o-mini"):
            self.assertNotIn(absent, names, absent)

    def test_azure_leads_the_pool_because_it_is_the_one_that_fits(self):
        self.assertEqual(DEFAULT_POOL[0].api_key_env, "AI_INVESTOR_AZURE_API_KEY")


class GroqCandidateTest(unittest.TestCase):
    def test_groq_is_available_but_not_in_the_default_pool(self):
        """무료 TPM 8,000은 종목 하나의 프롬프트도 못 받는다 — 넣으면 매번 413이다."""
        self.assertNotIn(
            "AI_INVESTOR_GROQ_API_KEY", {c.api_key_env for c in DEFAULT_POOL},
        )
        self.assertNotIn("GROQ_API_KEY", {c.api_key_env for c in DEFAULT_POOL})

    def test_the_groq_factory_is_kept_for_a_paid_tier(self):
        candidate = groq_candidate("openai/gpt-oss-20b", daily_request_limit=1000)

        self.assertEqual(candidate.base_url, "https://api.groq.com/openai/v1")
        self.assertEqual(candidate.api_key_env, "GROQ_API_KEY")
        self.assertEqual(candidate.tradingagents_provider, "openai")

    def test_the_measured_free_tier_limit_is_recorded(self):
        """왜 뺐는지 숫자로 남긴다 — 나중에 '한번 더 넣어보자'를 막는다."""
        self.assertEqual(GROQ_FREE_TIER_TPM, 8000)


class PoolCapacityTest(unittest.TestCase):
    def test_every_candidate_can_finish_at_least_one_ticker(self):
        for candidate in DEFAULT_POOL:
            self.assertGreaterEqual(
                candidate.daily_request_limit, CALLS_PER_TICKER_ESTIMATE, candidate.name,
            )

    def test_the_pool_is_azure_only(self):
        """단일화 결정(2026-09-03): 후보가 하나면 어느 키로 불렀는지가 항상 분명하다."""
        self.assertEqual({c.api_key_env for c in DEFAULT_POOL}, {"AI_INVESTOR_AZURE_API_KEY"})


if __name__ == "__main__":
    unittest.main()
