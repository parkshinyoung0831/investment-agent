"""같은 내용은 항상 같은 문자열·같은 지문이어야 한다."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from investment_agent.platform.serialization import (
    ContractError,
    canonical_json,
    canonicalize_url,
    content_hash,
    finite_float,
    json_value,
    parse_datetime,
)


class CanonicalJsonTest(unittest.TestCase):
    def test_key_order_does_not_change_the_output(self) -> None:
        self.assertEqual(canonical_json({"b": 1, "a": 2}), canonical_json({"a": 2, "b": 1}))

    def test_decimal_keeps_every_digit(self) -> None:
        """float으로 왕복시키면 마지막 자리가 달라진다."""
        self.assertIn('"0.1234567890123456789"', canonical_json({"x": Decimal("0.1234567890123456789")}))

    def test_dates_become_iso_strings(self) -> None:
        payload = canonical_json({"d": date(2026, 9, 5), "t": datetime(2026, 9, 5, tzinfo=timezone.utc)})
        self.assertIn('"2026-09-05"', payload)
        self.assertIn('"2026-09-05T00:00:00+00:00"', payload)

    def test_set_order_is_stable(self) -> None:
        self.assertEqual(canonical_json({"s": {"b", "a"}}), canonical_json({"s": {"a", "b"}}))

    def test_nan_becomes_null_not_invalid_json(self) -> None:
        """NaN/Infinity는 표준 JSON이 아니라 받는 쪽 파서가 제각각 읽는다."""
        self.assertEqual('{"x":null}', canonical_json({"x": float("nan")}))
        self.assertEqual('{"x":null}', canonical_json({"x": float("inf")}))

    def test_tuple_and_list_are_the_same_value(self) -> None:
        self.assertEqual(json_value((1, 2)), json_value([1, 2]))


class ContentHashTest(unittest.TestCase):
    def test_same_content_same_digest_regardless_of_key_order(self) -> None:
        self.assertEqual(content_hash({"a": 1, "b": [1, 2]}), content_hash({"b": [1, 2], "a": 1}))

    def test_different_content_different_digest(self) -> None:
        self.assertNotEqual(content_hash({"a": 1}), content_hash({"a": 2}))

    def test_digest_is_sha256_hex(self) -> None:
        self.assertEqual(64, len(content_hash({"a": 1})))


class ParseDatetimeTest(unittest.TestCase):
    def test_z_suffix_is_utc(self) -> None:
        self.assertEqual(
            datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc),
            parse_datetime("2026-09-05T13:00:00Z"),
        )

    def test_naive_string_is_rejected(self) -> None:
        with self.assertRaises(ContractError):
            parse_datetime("2026-09-05T13:00:00")


class CanonicalizeUrlTest(unittest.TestCase):
    def test_tracking_parameters_are_dropped(self) -> None:
        self.assertEqual(
            "https://example.test/a?id=1",
            canonicalize_url("https://Example.test/a/?id=1&utm_source=x&fbclid=y#frag"),
        )

    def test_default_port_is_dropped_but_others_kept(self) -> None:
        self.assertEqual("https://example.test/a", canonicalize_url("https://example.test:443/a"))
        self.assertEqual("https://example.test:8443/a", canonicalize_url("https://example.test:8443/a"))

    def test_non_http_schemes_are_rejected(self) -> None:
        for value in ("javascript:alert(1)", "ftp://example.test/a", "", None, "not a url"):
            self.assertIsNone(canonicalize_url(value), value)


class FiniteFloatTest(unittest.TestCase):
    def test_bool_is_not_a_number(self) -> None:
        """float(True)는 1.0이라, 플래그가 지표 값으로 조용히 섞인다."""
        self.assertIsNone(finite_float(True))

    def test_non_finite_and_unreadable_use_the_default(self) -> None:
        for value in (float("nan"), float("inf"), None, "abc", object()):
            self.assertEqual(-1.0, finite_float(value, -1.0))

    def test_numeric_strings_are_read(self) -> None:
        self.assertEqual(1.5, finite_float("1.5"))


if __name__ == "__main__":
    unittest.main()
