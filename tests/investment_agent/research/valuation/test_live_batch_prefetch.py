"""live 밸류에이션 적재도 재무·주식수·분할을 한 번에 읽는다 — 값은 종목별 조회와 같다(PB-1)."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from investment_agent.research.commands.build_valuations import build_valuations
from investment_agent.research.evidence import reader as reader_module
from investment_agent.research.evidence.reader import PitReader

AS_OF = datetime(2026, 8, 21, 2, 0, tzinfo=timezone.utc)
FUND = {"AAA": [{"ticker": "AAA", "fiscal_year": 2026, "fiscal_period": "Q1"}],
        "BBB": [{"ticker": "BBB", "fiscal_year": 2026, "fiscal_period": "Q1"}]}
SHARES = {"AAA": [{"shares_outstanding": 10}], "BBB": [{"shares_outstanding": 20}]}
SPLITS = {"AAA": [{"ticker": "AAA", "split_ratio": 2.0}], "BBB": []}


class _Mirror:
    def split_histories(self, tickers):
        return {ticker: list(SPLITS[ticker]) for ticker in tickers}


def _reader() -> PitReader:
    reader = PitReader()
    reader._mirror = lambda as_of_at=None: _Mirror()
    return reader


def _patches():
    fundamentals = reader_module.fundamentals_expectations
    shares = reader_module.fundamentals_shares
    return (
        mock.patch.object(fundamentals, "securities_fundamentals_filed_before",
                          side_effect=lambda tickers, as_of, limit: [r for t in tickers for r in FUND[t]]),
        mock.patch.object(shares, "share_class_snapshots_for_tickers_filed_before",
                          side_effect=lambda tickers, as_of, limit: {t: SHARES[t] for t in tickers}),
        mock.patch.object(fundamentals, "security_fundamentals_filed_before",
                          side_effect=lambda ticker, as_of, limit: list(FUND[ticker])),
        mock.patch.object(shares, "share_class_snapshots_filed_before",
                          side_effect=lambda ticker, as_of, limit: list(SHARES[ticker])),
    )


class BatchEqualsSingleTest(unittest.TestCase):
    def test_batched_reads_equal_per_ticker_reads_and_skip_the_single_calls(self) -> None:
        batch_f, batch_s, single_f, single_s = _patches()
        with batch_f as bf, batch_s as bs, single_f as sf, single_s as ss:
            reader = _reader()
            reader.prepare_valuation_inputs(["AAA", "BBB"], AS_OF)
            got = {t: (reader.fundamentals_pit(t, AS_OF, 12), reader.share_class_snapshots_pit(t, AS_OF),
                       reader.split_history(t)) for t in ("AAA", "BBB")}
            bf.assert_called_once()
            bs.assert_called_once()
            sf.assert_not_called()
            ss.assert_not_called()
        for ticker in ("AAA", "BBB"):
            self.assertEqual(got[ticker], (FUND[ticker], SHARES[ticker], SPLITS[ticker]))

    def test_a_ticker_the_batch_did_not_return_is_left_to_the_single_read(self) -> None:
        """배치는 상장 중인 종목만 읽는다. 빈 값을 seed하면 단건이 줬을(상장 폐지 종목 등) 값을 지운다."""
        batch_f, batch_s, single_f, single_s = _patches()
        with batch_f as bf, batch_s as bs, single_f as sf, single_s as ss:
            bf.side_effect = lambda tickers, as_of, limit: []
            bs.side_effect = lambda tickers, as_of, limit: {}
            reader = _reader()
            reader.prepare_valuation_inputs(["AAA"], AS_OF)
            self.assertEqual(reader.fundamentals_pit("AAA", AS_OF, 12), FUND["AAA"])
            self.assertEqual(reader.share_class_snapshots_pit("AAA", AS_OF), SHARES["AAA"])
            sf.assert_called_once()
            ss.assert_called_once()


class _Repository:
    def __init__(self, *, prepare_error: Exception | None = None) -> None:
        self.prepare_error = prepare_error
        self.prepared: list[tuple] = []

    def prepare_valuation_inputs(self, tickers, as_of_at):
        self.prepared.append((tuple(tickers), as_of_at))
        if self.prepare_error:
            raise self.prepare_error

    def market_prices(self, ticker, as_of_at, limit=260):
        return []

    def fundamentals_pit(self, ticker, as_of_at, limit=12):
        return []

    def share_class_snapshots_pit(self, ticker, as_of_at, limit=24):
        return []


class _Store:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    def save_valuation_observations(self, rows):
        self.saved.extend(rows)


class LivePathUsesBatchTest(unittest.TestCase):
    def test_live_run_prepares_all_tickers_once(self) -> None:
        repository, store = _Repository(), _Store()
        build_valuations(as_of_at=AS_OF, tickers=["AAA", "BBB"], repository=repository, store=store)
        self.assertEqual(repository.prepared, [(("AAA", "BBB"), AS_OF)])
        self.assertEqual(len(store.saved), 2)

    def test_batch_failure_falls_back_to_per_ticker_reads_instead_of_failing_the_run(self) -> None:
        repository, store = _Repository(prepare_error=TimeoutError("8s")), _Store()
        payload = build_valuations(as_of_at=AS_OF, tickers=["AAA"], repository=repository, store=store)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(len(store.saved), 1)


if __name__ == "__main__":
    unittest.main()
