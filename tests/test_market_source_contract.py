from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

from investment_agent.data.market.infrastructure.sources import yahoo as source


class PriceCollectionContractTests(unittest.TestCase):
    def test_market_group_installs_the_yfinance_repair_extra(self) -> None:
        """repair=True는 yfinance의 scipy/scikit-learn extra를 요구한다.

        extra 없이 설치하면 repair가 조용히 아무것도 고치지 않는다 — 값이 틀린 채로
        들어오고 그건 예외로 드러나지 않는다.
        """
        import tomllib

        groups = tomllib.loads(
            Path("pyproject.toml").read_text(encoding="utf-8")
        )["dependency-groups"]
        # market 수집은 data group으로 설치된다.
        declared = [item for item in groups["data"] if isinstance(item, str)]
        self.assertTrue(
            any(item.startswith("yfinance[repair]") for item in declared),
            declared,
        )

    def test_excludes_unfinished_current_session_bar(self) -> None:
        rows = [
            {"trade_date": "2026-08-27"},
            {"trade_date": "2026-08-28"},
        ]

        completed = source._exclude_unfinished_daily_bars(
            rows,
            date(2026, 8, 27),
        )

        self.assertEqual(completed, [{"trade_date": "2026-08-27"}])

    def test_rejects_invalid_corporate_actions(self) -> None:
        base = {
            "ticker": "AAPL",
            "trade_date": "2026-08-27",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "adj_close": 99.0,
            "volume": 100,
            "div_amount": None,
            "split_ratio": 1.0,
        }

        with self.assertRaisesRegex(RuntimeError, "invalid split_ratio"):
            source._validate_price_rows([base], ["AAPL"])

    def test_repairs_small_yahoo_ohlc_bound_error(self) -> None:
        row = {
            "ticker": "HUBB",
            "trade_date": "2021-05-05",
            "open": 195.98,
            "high": 198.64,
            "low": 196.21,
            "close": 198.13,
            "adj_close": 190.0,
            "volume": 127_234,
            "div_amount": None,
            "split_ratio": None,
            "source": "yfinance",
        }

        repaired = source._repair_small_ohlc_bound_errors([row])

        self.assertEqual(repaired[0]["low"], row["open"])
        self.assertEqual(repaired[0]["source"], "yfinance_repaired")
        source._validate_price_rows(repaired, ["HUBB"])

    def test_does_not_hide_large_ohlc_bound_error(self) -> None:
        row = {
            "ticker": "BAD",
            "trade_date": "2026-08-27",
            "open": 100.0,
            "high": 101.0,
            "low": 110.0,
            "close": 100.0,
            "adj_close": 99.0,
            "volume": 1,
            "div_amount": None,
            "split_ratio": None,
            "source": "yfinance",
        }

        repaired = source._repair_small_ohlc_bound_errors([row])

        with self.assertRaisesRegex(RuntimeError, "incoherent OHLC"):
            source._validate_price_rows(repaired, ["BAD"])

    def test_download_validates_split_continuity_before_returning(self) -> None:
        raw = pd.DataFrame(
            {
                ("TEST", "Open"): [100.0, 50.0],
                ("TEST", "High"): [101.0, 51.0],
                ("TEST", "Low"): [99.0, 49.0],
                ("TEST", "Close"): [100.0, 50.0],
                ("TEST", "Adj Close"): [100.0, 50.0],
                ("TEST", "Volume"): [100, 200],
                ("TEST", "Dividends"): [0.0, 0.0],
                ("TEST", "Stock Splits"): [0.0, 2.0],
            },
            index=pd.to_datetime(["2026-08-26", "2026-08-27"]),
        )
        raw.columns = pd.MultiIndex.from_tuples(raw.columns)

        with (
            mock.patch.object(source, "_yf_download", return_value=raw),
            mock.patch.object(
                source,
                "completed_bar_cutoff",
                return_value=date(2026, 8, 27),
            ),
            mock.patch.object(
                source,
                "normalize_split_adjusted_prices",
                side_effect=lambda rows: rows,
            ),
            self.assertRaisesRegex(RuntimeError, "split validation failed"),
        ):
            source.download_ohlcv(["TEST"], 7)

    def test_rows_preserve_provider_adjusted_close(self) -> None:
        raw = pd.DataFrame(
            {
                ("AAPL", "Open"): [125.0],
                ("AAPL", "High"): [126.0],
                ("AAPL", "Low"): [124.0],
                ("AAPL", "Close"): [125.01],
                ("AAPL", "Adj Close"): [121.15],
                ("AAPL", "Volume"): [100],
                ("AAPL", "Dividends"): [0.0],
                ("AAPL", "Stock Splits"): [0.0],
            },
            index=pd.to_datetime(["2020-08-27"]),
        )
        raw.columns = pd.MultiIndex.from_tuples(raw.columns)

        rows = source._rows_from_frame(raw, ["AAPL"])

        self.assertEqual(rows[0]["close"], 125.01)
        self.assertEqual(rows[0]["adj_close"], 121.15)
        self.assertNotEqual(rows[0]["adj_close"], rows[0]["close"])


if __name__ == "__main__":
    unittest.main()
