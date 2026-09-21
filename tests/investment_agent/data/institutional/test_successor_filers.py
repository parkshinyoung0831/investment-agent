"""제출자를 바꾼 사람의 공시는 본인 CIK로 귀속해 적재한다(DI-1). Pershing Square가 실제 사례다."""
from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date
from unittest import mock

from investment_agent.data.institutional.application import etl
from investment_agent.data.institutional.domain.managers import MANAGER_CATALOG, filing_sources
from tests.investment_agent.data.institutional._factories import make_filing_record

OLD, NEW = "0001336528", "0002026053"


def _record(cik: str, period: date, accession: str):
    return replace(make_filing_record(), manager_cik=cik, period_end=period, accession_no=accession)


class FilingSourcesTest(unittest.TestCase):
    def test_pershing_successor_is_declared_with_its_first_period(self) -> None:
        self.assertEqual(filing_sources(OLD), ((OLD, None), (NEW, "2026-06-30")))

    def test_a_manager_without_successors_has_only_itself(self) -> None:
        self.assertEqual(filing_sources("0001067983"), (("0001067983", None),))

    def test_every_successor_is_a_real_ten_digit_cik_not_already_tracked(self) -> None:
        for cik, row in MANAGER_CATALOG.items():
            for successor in (row.get("successors") or {}):
                self.assertEqual(len(successor), 10)
                self.assertNotIn(successor, MANAGER_CATALOG, "후속 CIK를 별개 거장으로 또 추적하면 스레드가 갈라진다")


class SuccessorAttributionTest(unittest.TestCase):
    def _run(self, by_cik: dict) -> list:
        def fake_iter(cik, since, **_options):
            yield from by_cik.get(cik, [])

        with mock.patch.object(etl.edgar, "iter_filings", side_effect=fake_iter):
            return list(etl.iter_manager_filings(OLD, date(2020, 1, 1)))

    def test_successor_filings_from_the_first_period_are_attributed_to_the_person(self) -> None:
        records = self._run({
            OLD: [_record(OLD, date(2026, 3, 31), "old-q1")],
            NEW: [_record(NEW, date(2026, 6, 30), "new-q2")],
        })
        self.assertEqual([(r.accession_no, r.manager_cik) for r in records], [("old-q1", OLD), ("new-q2", OLD)])

    def test_successor_filings_before_the_first_period_are_ignored_to_avoid_double_counting(self) -> None:
        records = self._run({
            OLD: [_record(OLD, date(2026, 3, 31), "old-q1")],
            NEW: [_record(NEW, date(2026, 3, 31), "new-q1-duplicate"), _record(NEW, date(2025, 12, 31), "new-q4")],
        })
        self.assertEqual([r.accession_no for r in records], ["old-q1"])


if __name__ == "__main__":
    unittest.main()
