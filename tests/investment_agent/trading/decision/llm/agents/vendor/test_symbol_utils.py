"""브로커 심볼을 Yahoo Finance 심볼로 정규화하는 규칙을 검증한다."""
from __future__ import annotations

import unittest

from investment_agent.trading.decision.llm.agents.vendor.symbol_utils import (
    crypto_base,
    normalize_symbol,
)


class NormalizeSymbolTest(unittest.TestCase):
    def test_plain_equity_passes_through_uppercased(self):
        self.assertEqual(normalize_symbol("aapl"), "AAPL")

    def test_gold_alias_resolves_to_comex_future(self):
        self.assertEqual(normalize_symbol("XAUUSD"), "GC=F")
        self.assertEqual(normalize_symbol("XAUUSD+"), "GC=F")

    def test_forex_pair_gets_yahoo_suffix(self):
        self.assertEqual(normalize_symbol("EURUSD"), "EURUSD=X")

    def test_crypto_pair_uses_dash_form(self):
        self.assertEqual(normalize_symbol("BTCUSD"), "BTC-USD")
        self.assertEqual(normalize_symbol("BTC-USDT"), "BTC-USD")


class CryptoBaseTest(unittest.TestCase):
    def test_known_base_detected_regardless_of_dash(self):
        self.assertEqual(crypto_base("BTCUSD"), "BTC")
        self.assertEqual(crypto_base("BTC-USD"), "BTC")

    def test_non_crypto_symbol_returns_none(self):
        self.assertIsNone(crypto_base("AAPL"))


if __name__ == "__main__":
    unittest.main()
