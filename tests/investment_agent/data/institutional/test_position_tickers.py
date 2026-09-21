"""13F 보유 행에 ticker가 붙어 guru 신호가 결측이 되지 않는다(RS-1).

소비자(evidence reader)는 `row["ticker"]`와 `mapping_status in {mapped, historical}`를 요구한다.
원천 표에는 그 열이 없어, 저장소가 채우지 않으면 guru feature가 100% 결측이다.
"""
from __future__ import annotations

import unittest

from investment_agent.data.institutional.persistence import attach_tickers

CACHE = {
    ("037833100", "CUSIP"): {"security_id": 7, "mapping_status": "verified"},
    ("000000000", "CUSIP"): {"security_id": None, "mapping_status": "unresolved"},
    ("111111111", "CUSIP"): {"security_id": 8, "mapping_status": "conflict"},
}


class AttachTickersTest(unittest.TestCase):
    def _rows(self, *identifiers: str):
        return [{"identifier": i, "identifier_type": "CUSIP", "value_usd": 1.0} for i in identifiers]

    def test_verified_identifier_gets_a_ticker_and_the_mapped_status(self) -> None:
        (row,) = attach_tickers(self._rows("037833100"), CACHE, {7: "AAPL"})
        self.assertEqual((row["ticker"], row["mapping_status"]), ("AAPL", "mapped"))

    def test_unverified_or_unknown_identifiers_carry_no_ticker(self) -> None:
        rows = attach_tickers(self._rows("000000000", "111111111", "999999999"), CACHE, {8: "ZZZ"})
        self.assertEqual([r["ticker"] for r in rows], [None, None, None])
        self.assertEqual([r["mapping_status"] for r in rows], ["unresolved", "conflict", "unmapped"])

    def test_original_columns_are_preserved(self) -> None:
        (row,) = attach_tickers(self._rows("037833100"), CACHE, {7: "AAPL"})
        self.assertEqual(row["value_usd"], 1.0)

    def test_output_satisfies_the_reader_contract(self) -> None:
        """reader가 거르는 조건(`mapping_status in {mapped, historical}`, ticker 존재)을 통과한다."""
        (row,) = attach_tickers(self._rows("037833100"), CACHE, {7: "AAPL"})
        self.assertTrue(row["ticker"] and row["mapping_status"] in {"mapped", "historical"})


if __name__ == "__main__":
    unittest.main()


class EffectivePortfolioStateGroupingTest(unittest.TestCase):
    """원본과 NEW HOLDINGS가 함께 유효한 분기는 두 신고의 행이 한 포트폴리오로 묶여야 한다(DI-2).

    행마다 자기 accession을 키로 붙이면 소비자가 추가분 몇 줄만 그 분기 포트폴리오로 읽는다.
    """

    MANAGER = "0001067983"

    def _filing(self, accession, period, filed, *, form="13F-HR", amendment=None):
        return {
            "accession_no": accession, "manager_cik": self.MANAGER, "period_end": period,
            "form_type": form, "report_type": "13F HOLDINGS REPORT", "filing_date": filed,
            "accepted_at": f"{filed}T10:00:00+00:00", "amendment_type": amendment, "amendment_no": None,
            "source_url": None, "confidential_omitted": False,
        }

    def _state(self):
        from datetime import datetime, timezone
        from unittest import mock

        from investment_agent.data.institutional import persistence

        filings = [
            self._filing("A-BASE-Q1", "2026-03-31", "2026-05-15"),
            self._filing("A-BASE-Q2", "2026-06-30", "2026-08-14"),
            self._filing("A-ADD-Q2", "2026-06-30", "2026-08-30", form="13F-HR/A", amendment="NEW HOLDINGS"),
        ]
        positions = [
            {"accession_no": "A-BASE-Q1", "source_row_no": 1, "identifier": "037833100", "value_usd": 9.0},
            {"accession_no": "A-BASE-Q2", "source_row_no": 1, "identifier": "037833100", "value_usd": 5.0},
            {"accession_no": "A-BASE-Q2", "source_row_no": 2, "identifier": "594918104", "value_usd": 4.0},
            {"accession_no": "A-ADD-Q2", "source_row_no": 1, "identifier": "88160R101", "value_usd": 1.0},
        ]

        class Db:
            def table(self, *_a):
                return self

            def select(self, *_a):
                return self

            def lte(self, *_a):
                return self

            def select_paged(self, _factory, **_k):
                return filings

            def select_in_chunks(self, **kwargs):
                wanted = set(kwargs["values"])
                return [row for row in positions if row["accession_no"] in wanted]

        class Universe:
            def __init__(self, _db):
                pass

            def tickers_by_security_id(self, _ids):
                return {}

        with mock.patch.object(persistence, "_db", return_value=Db()), \
                mock.patch.object(persistence, "UniverseRepository", Universe), \
                mock.patch.object(persistence, "get_identifier_cache", return_value={}), \
                mock.patch.dict(persistence.manager_config.MANAGER_CATALOG, {self.MANAGER: {"is_active": True}}, clear=True):
            return persistence.effective_portfolio_state(datetime(2026, 9, 21, tzinfo=timezone.utc))

    def test_base_and_addition_rows_share_the_events_accession(self) -> None:
        current, previous, rows = self._state()
        event_accession = current[self.MANAGER]["effective_accession_no"]
        self.assertEqual("A-ADD-Q2", event_accession, "그 분기의 최신 유효 신고가 사건이다")
        by_accession = {row["accession_no"]: row["effective_accession_no"] for row in rows}
        self.assertEqual(event_accession, by_accession["A-BASE-Q2"])
        self.assertEqual(event_accession, by_accession["A-ADD-Q2"])
        self.assertEqual("A-BASE-Q1", previous[self.MANAGER]["effective_accession_no"])
        self.assertEqual("A-BASE-Q1", by_accession["A-BASE-Q1"])

    def test_the_whole_quarter_is_readable_under_the_event_key(self) -> None:
        current, _previous, rows = self._state()
        key = current[self.MANAGER]["effective_accession_no"]
        self.assertEqual(3, len([row for row in rows if row["effective_accession_no"] == key]))
