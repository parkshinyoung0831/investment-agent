"""로그는 한 줄 JSON이고, 비밀값은 나가지 않는다."""
from __future__ import annotations

import json
import logging
import unittest

from investment_agent.platform.logging import JsonFormatter, log_fields, redact


def _render(msg: str, **extra: object) -> dict:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, msg, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return json.loads(JsonFormatter().format(record))


class RedactTest(unittest.TestCase):
    def test_api_key_in_query_string_is_hidden(self) -> None:
        cleaned = redact("GET https://api.example.test/v1?series=X&api_key=abcd1234efgh")
        self.assertNotIn("abcd1234efgh", cleaned)
        self.assertIn("api_key=<redacted>", cleaned)

    def test_bearer_token_is_hidden(self) -> None:
        cleaned = redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload")
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", cleaned)

    def test_ordinary_text_is_untouched(self) -> None:
        self.assertEqual("upserted 12 rows", redact("upserted 12 rows"))


class JsonFormatterTest(unittest.TestCase):
    def test_emits_one_json_object_with_the_basics(self) -> None:
        payload = _render("hello")
        self.assertEqual({"ts", "level", "logger", "msg"}, set(payload))
        self.assertEqual("INFO", payload["level"])

    def test_extra_fields_become_top_level_keys(self) -> None:
        payload = _render("done", rows_upserted=12, workflow="market_daily")
        self.assertEqual(12, payload["rows_upserted"])
        self.assertEqual("market_daily", payload["workflow"])

    def test_message_is_redacted(self) -> None:
        payload = _render("fetch https://x.test?token=supersecretvalue")
        self.assertNotIn("supersecretvalue", payload["msg"])

    def test_unserializable_value_does_not_break_logging(self) -> None:
        """로그는 관측이다. 직렬화 때문에 프로그램이 죽으면 안 된다."""
        payload = _render("obj", thing=object())
        self.assertIsInstance(payload["thing"], str)


class LogFieldsTest(unittest.TestCase):
    def test_reserved_names_are_rejected_early(self) -> None:
        """logging이 나중에 KeyError를 던지는 것보다 여기서 막는 편이 낫다."""
        with self.assertRaises(ValueError):
            log_fields(message="x")

    def test_ordinary_names_pass_through(self) -> None:
        self.assertEqual({"rows": 3}, dict(log_fields(rows=3)))


if __name__ == "__main__":
    unittest.main()
