"""구조화 호출 payload가 모델이 받는 모양인지 검증한다.

실측 2026-09-03 (Azure gpt-5-mini):
  temperature=0.1 -> 400 "Unsupported value: 'temperature' does not support 0.1
                          with this model. Only the default (1) value is supported."
  temperature 미전송 / =1 -> 200
TradingAgents 호출 17건이 전부 성공한 뒤 이 마지막 단계에서만 죽었다.
"""
from __future__ import annotations

import unittest

from investment_agent.trading.decision.llm.client import OpenAICompatibleClient, supports_custom_temperature


class TemperatureSupportTest(unittest.TestCase):
    def test_reasoning_families_only_accept_the_default(self):
        for model in ("gpt-5-mini", "gpt-5", "gpt-5.4-nano", "o1-mini", "o3", "o4-mini"):
            self.assertFalse(supports_custom_temperature(model), model)

    def test_other_models_still_accept_a_custom_temperature(self):
        for model in ("gpt-4o-mini", "gpt-4.1", "gemini-2.5-flash", "DeepSeek-V3"):
            self.assertTrue(supports_custom_temperature(model), model)

    def test_case_and_padding_do_not_change_the_answer(self):
        self.assertFalse(supports_custom_temperature("  GPT-5-Mini "))


class PayloadTest(unittest.TestCase):
    def _client(self, model: str) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(
            base_url="https://example.test/openai/v1", model=model, api_key="k",
        )

    def test_temperature_is_omitted_for_models_that_reject_it(self):
        payload = self._client("gpt-5-mini").build_payload(system="s", user="u", schema_text="{}")

        self.assertNotIn("temperature", payload)
        self.assertEqual(payload["response_format"], {"type": "json_object"})

    def test_temperature_is_kept_for_models_that_accept_it(self):
        payload = self._client("gpt-4o-mini").build_payload(system="s", user="u", schema_text="{}")

        self.assertEqual(payload["temperature"], 0.1)

    def test_the_schema_is_shown_to_the_model(self):
        payload = self._client("gpt-5-mini").build_payload(
            system="s", user="u", schema_text='{"type":"object"}',
        )

        self.assertIn('{"type":"object"}', payload["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()


class ErrorDetailTest(unittest.TestCase):
    """400의 이유가 provider 응답 본문에만 있는데 그걸 버리면 원인을 알 수 없다."""

    def _client(self):
        return OpenAICompatibleClient(
            base_url="https://example.test/openai/v1", model="gpt-5-mini", api_key="k",
        )

    def test_provider_reason_is_carried_into_the_raised_error(self):
        import httpx
        from unittest import mock

        body = {"error": {"message": "Unsupported value: 'temperature' does not support 0.1"}}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json=body)

        transport = httpx.MockTransport(handler)
        original = httpx.Client

        def patched(*args, **kwargs):
            kwargs["transport"] = transport
            return original(*args, **kwargs)

        with mock.patch.object(httpx, "Client", patched):
            with self.assertRaises(Exception) as caught:
                self._client().complete_json(
                    system="s", user="u", output_schema={}, task_name="t",
                )

        self.assertIn("temperature", str(caught.exception))
