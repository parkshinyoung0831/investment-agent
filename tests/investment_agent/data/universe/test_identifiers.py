"""이름 정규화가 같은 종목을 갈라놓거나 다른 종목을 합치지 않아야 한다."""
from __future__ import annotations

import unittest

from investment_agent.data.universe.domain.identifiers import (
    cusip_check_digit,
    is_valid_identifier,
    normalize_cik,
    normalize_cusip,
    normalize_ticker,
)


class NormalizeTickerTest(unittest.TestCase):
    def test_sec_and_yahoo_forms_land_on_the_same_ticker(self) -> None:
        """`BRK.B`와 `brk-b`가 다른 종목이 되면 같은 회사가 둘로 갈린다."""
        self.assertEqual("BRK-B", normalize_ticker("BRK.B"))
        self.assertEqual("BRK-B", normalize_ticker(" brk-b "))

    def test_shapes_the_store_rejects_are_none(self) -> None:
        for value in (None, "", "   ", "TOOLONGTICKER1", "AA PL", "AA_PL", "티커"):
            self.assertIsNone(normalize_ticker(value), value)

    def test_plain_ticker_is_unchanged(self) -> None:
        self.assertEqual("AAPL", normalize_ticker("AAPL"))


class NormalizeCikTest(unittest.TestCase):
    def test_every_form_sec_sends_becomes_ten_digits(self) -> None:
        for value in ("320193", "0000320193", "CIK0000320193", " cik320193 "):
            self.assertEqual("0000320193", normalize_cik(value), value)

    def test_unreadable_values_are_none(self) -> None:
        for value in (None, "", "abc", "12345678901", "12.3"):
            self.assertIsNone(normalize_cik(value), value)


class CusipTest(unittest.TestCase):
    def test_real_cusips_validate(self) -> None:
        # AAPL, MSFT, AMZN.
        for value in ("037833100", "594918104", "023135106"):
            self.assertEqual(value, normalize_cusip(value), value)

    def test_a_wrong_check_digit_is_refused(self) -> None:
        """자리가 밀린 CUSIP은 아무 종목에도 안 붙는데 에러는 안 난다 — 여기서 잡는다."""
        self.assertIsNone(normalize_cusip("037833101"))

    def test_shape_errors_are_refused(self) -> None:
        for value in (None, "", "03783310", "0378331000", "03783310!"):
            self.assertIsNone(normalize_cusip(value), value)

    def test_check_digit_needs_eight_characters(self) -> None:
        self.assertIsNone(cusip_check_digit("0378331"))
        self.assertEqual("0", cusip_check_digit("03783310"))


class IsValidIdentifierTest(unittest.TestCase):
    def test_each_type_has_its_own_shape(self) -> None:
        self.assertTrue(is_valid_identifier("037833100", "CUSIP"))
        self.assertTrue(is_valid_identifier("BBG000B9XRY4", "FIGI"))
        self.assertTrue(is_valid_identifier("BRK-B", "TICKER"))

    def test_wrong_shape_for_the_type_is_refused(self) -> None:
        self.assertFalse(is_valid_identifier("BBG000B9XRY4", "CUSIP"))
        self.assertFalse(is_valid_identifier("037833100", "FIGI"))

    def test_unknown_type_is_refused(self) -> None:
        self.assertFalse(is_valid_identifier("037833100", "ISIN"))


if __name__ == "__main__":
    unittest.main()
