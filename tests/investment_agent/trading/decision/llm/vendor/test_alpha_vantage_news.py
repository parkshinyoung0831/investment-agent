"""Alpha Vantage NEWS_SENTIMENT fetcher가 날짜 포맷·요금제 오류 분류를 지키는지 검증한다(네트워크 없음)."""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from investment_agent.trading.decision.llm.vendor.alpha_vantage_news import (
    AlphaVantageNotConfiguredError,
    AlphaVantageRateLimitError,
    format_datetime_for_api,
    get_news,
)


class FormatDatetimeForApiTest(unittest.TestCase):
    def test_plain_date_gets_midnight_time(self):
        self.assertEqual(format_datetime_for_api("2026-09-16"), "20260916T0000")

    def test_already_formatted_value_passes_through(self):
        self.assertEqual(format_datetime_for_api("20260916T0000"), "20260916T0000")


class GetNewsTest(unittest.TestCase):
    def test_returns_raw_response_text_on_success(self):
        payload = json.dumps({"feed": [{"title": "Apple beats"}]})
        with mock.patch.dict(os.environ, {"ALPHA_VANTAGE_API_KEY": "k"}):
            result = get_news(
                "AAPL", "2026-09-01", "2026-09-16",
                http_get=lambda params, timeout: payload,
            )
        self.assertEqual(result, payload)

    def test_sends_ticker_and_formatted_dates(self):
        seen = {}

        def _capture(params, timeout):
            seen.update(params)
            return "{}"

        with mock.patch.dict(os.environ, {"ALPHA_VANTAGE_API_KEY": "k"}):
            get_news("AAPL", "2026-09-01", "2026-09-16", http_get=_capture)
        self.assertEqual(seen["tickers"], "AAPL")
        self.assertEqual(seen["time_from"], "20260901T0000")
        self.assertEqual(seen["time_to"], "20260916T0000")
        self.assertEqual(seen["apikey"], "k")

    def test_missing_api_key_raises_not_configured(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AlphaVantageNotConfiguredError):
                get_news("AAPL", "2026-09-01", "2026-09-16", http_get=lambda p, t: "{}")

    def test_rate_limit_notice_raises_rate_limit_error(self):
        payload = json.dumps({"Information": "You have hit the rate limit, 25 requests per day"})
        with mock.patch.dict(os.environ, {"ALPHA_VANTAGE_API_KEY": "k"}):
            with self.assertRaises(AlphaVantageRateLimitError):
                get_news("AAPL", "2026-09-01", "2026-09-16", http_get=lambda p, t: payload)

    def test_bad_api_key_notice_raises_not_configured(self):
        payload = json.dumps({"Information": "the apikey you supplied is invalid"})
        with mock.patch.dict(os.environ, {"ALPHA_VANTAGE_API_KEY": "k"}):
            with self.assertRaises(AlphaVantageNotConfiguredError):
                get_news("AAPL", "2026-09-01", "2026-09-16", http_get=lambda p, t: payload)


if __name__ == "__main__":
    unittest.main()
