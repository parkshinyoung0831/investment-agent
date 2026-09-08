"""기본 풀 구성 — 실제로 존재하는 모델 id만, 안전 우선순위로 나열한다."""
from __future__ import annotations

import unittest

from investment_agent.trading.decision.model_pool import (
    CALLS_PER_TICKER_ESTIMATE,
    DEFAULT_POOL,
    gemini_candidate,
)


class DefaultPoolTest(unittest.TestCase):
    def test_pool_is_not_empty(self):
        self.assertGreaterEqual(len(DEFAULT_POOL), 1)

    def test_names_are_unique(self):
        names = [candidate.name for candidate in DEFAULT_POOL]
        self.assertEqual(len(names), len(set(names)))

    def test_higher_daily_capacity_candidates_come_first(self):
        """예산이 큰 모델부터 시도해야 하루 처리량이 최대화된다."""
        budgets = [candidate.daily_ticker_budget for candidate in DEFAULT_POOL]
        self.assertEqual(budgets, sorted(budgets, reverse=True))

    def test_the_gemini_factory_still_points_at_the_openai_compatible_endpoint(self):
        """풀에서는 뺐지만 되살릴 때 엔드포인트를 다시 찾지 않아도 되게 남겨 둔다."""
        candidate = gemini_candidate("gemini-2.5-flash", daily_request_limit=20)

        self.assertEqual(
            candidate.base_url, "https://generativelanguage.googleapis.com/v1beta/openai",
        )
        self.assertEqual(candidate.tradingagents_provider, "openai")
        self.assertEqual(candidate.api_key_env, "AI_INVESTOR_GEMINI_API_KEY")

    def test_every_candidate_can_actually_finish_at_least_one_ticker(self):
        for candidate in DEFAULT_POOL:
            self.assertGreaterEqual(
                candidate.daily_request_limit, CALLS_PER_TICKER_ESTIMATE, candidate.name,
            )

    def test_retired_and_tool_calling_incompatible_models_are_not_in_the_pool(self):
        """실측(2026-09-03): gemini-2.5-flash-lite는 신규 계정에서 404,
        Gemini 3.x 계열은 벤더 클라이언트가 thought_signature를 못 채워 도구 호출
        두 번째 턴에서 400을 낸다. gemini-2.5-flash만 실제로 완주한다.
        """
        names = {c.name for c in DEFAULT_POOL} | {"gemini-2.5-flash"}
        for broken in (
            "gemini-2.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite",
            "gemini-3-flash-preview", "gemini-3.5-flash", "gemini-3.6-flash",
            "gemini-3.7-flash", "gemini-3.8-flash",
        ):
            self.assertNotIn(broken, names, broken)

if __name__ == "__main__":
    unittest.main()
