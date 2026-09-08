"""본문 ticker 추출. 오탐을 막지 못하면 언급 표가 쓰레기가 된다."""
from __future__ import annotations

import unittest

from investment_agent.intelligence.domain import extract

TRACKED = frozenset({"AAPL", "NVDA", "ALL", "IT", "ON", "NOW", "A", "HAS", "TSLA"})


def _tickers(text: str) -> set[str]:
    return {match.ticker for match in extract.find_tickers(text, tracked=TRACKED)}


class FindTickersTest(unittest.TestCase):
    def test_cashtag_is_always_accepted(self) -> None:
        self.assertEqual({"AAPL"}, _tickers("buying $AAPL today"))

    def test_plain_symbol_is_accepted_when_unambiguous(self) -> None:
        self.assertEqual({"NVDA"}, _tickers("NVDA earnings tomorrow"))

    def test_common_english_words_are_not_tickers_without_a_cashtag(self) -> None:
        """S&P 500에는 ALL·IT·ON·NOW 같은 평범한 단어가 티커로 있다."""
        self.assertEqual(set(), _tickers("IT IS ON ALL NOW"))

    def test_ambiguous_ticker_is_accepted_with_a_cashtag(self) -> None:
        self.assertEqual({"ALL"}, _tickers("long $ALL here"))

    def test_short_symbols_always_need_a_cashtag(self) -> None:
        self.assertEqual(set(), _tickers("grade A work"))
        self.assertEqual({"A"}, _tickers("grade $A work"))

    def test_untracked_symbols_are_ignored(self) -> None:
        """universe에 없는 심볼은 언급이 아니다 — fail-closed."""
        self.assertEqual(set(), _tickers("ZZZZ to the moon"))
        self.assertEqual(set(), _tickers("$ZZZZ to the moon"))

    def test_lowercase_is_not_a_symbol(self) -> None:
        self.assertEqual(set(), _tickers("it has all now"))

    def test_confidence_grades_the_extraction_method(self) -> None:
        cashtag = extract.find_tickers("$NVDA", tracked=TRACKED)[0]
        symbol = extract.find_tickers("NVDA", tracked=TRACKED)[0]
        self.assertEqual("cashtag", cashtag.match_kind)
        self.assertEqual("symbol", symbol.match_kind)
        self.assertGreater(cashtag.confidence, symbol.confidence)

    def test_the_same_ticker_is_reported_once_per_match_kind(self) -> None:
        matches = extract.find_tickers("$NVDA and NVDA again", tracked=TRACKED)
        self.assertEqual(
            {("NVDA", "cashtag"), ("NVDA", "symbol")},
            {(m.ticker, m.match_kind) for m in matches},
        )


if __name__ == "__main__":
    unittest.main()
