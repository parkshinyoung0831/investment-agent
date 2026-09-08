from __future__ import annotations

import unittest

from investment_agent.reporting.services.economic_releases import parse_event_key


class EconEventKeyTest(unittest.TestCase):
    """화면은 자연키가 유효한지만 알면 된다 — domain의 예외 표현에 묶이지 않는다."""

    def test_valid_key_splits_into_series_and_period(self) -> None:
        self.assertEqual(("CPI", "2026-08-01"), parse_event_key("CPI:2026-08-01"))
        self.assertEqual(("CPI", "2026-08-01"), parse_event_key("  CPI:2026-08-01  "))

    def test_malformed_keys_return_none_instead_of_raising(self) -> None:
        for value in (None, "", "CPI", "CPI:2026-13-01", "CPI:2026-08-01:extra", "cpi:2026-08-01"):
            with self.subTest(value=value):
                self.assertIsNone(parse_event_key(value))
