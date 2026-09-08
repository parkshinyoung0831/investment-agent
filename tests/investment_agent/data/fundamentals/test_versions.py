"""as-of 조회가 그때 손에 없던 정정을 보지 않아야 한다."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from investment_agent.data.fundamentals.domain.filings import (
    FilingError,
    base_form,
    is_amendment,
    is_periodic,
    normalize_accession,
)
from investment_agent.data.fundamentals.domain.versions import (
    VersionKey,
    latest,
    latest_known_at,
    restatement_count,
)


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


ORIGINAL = VersionKey("0000320193-25-000001", date(2025, 2, 1), _utc(2025, 2, 2))
RESTATED = VersionKey("0000320193-25-000009", date(2025, 6, 1), _utc(2025, 6, 3))


class LatestTest(unittest.TestCase):
    def test_the_newest_filing_wins(self) -> None:
        self.assertEqual(RESTATED, latest([ORIGINAL, RESTATED]))

    def test_input_order_does_not_matter(self) -> None:
        self.assertEqual(latest([ORIGINAL, RESTATED]), latest([RESTATED, ORIGINAL]))

    def test_same_day_amendments_break_the_tie_by_when_we_got_them(self) -> None:
        """같은 날 두 번 내는 회사가 실제로 있다."""
        first = VersionKey("0000320193-25-000010", date(2025, 6, 1), _utc(2025, 6, 1))
        second = VersionKey("0000320193-25-000011", date(2025, 6, 1), _utc(2025, 6, 2))
        self.assertEqual(second, latest([second, first]))

    def test_no_versions_is_none(self) -> None:
        self.assertIsNone(latest([]))


class LatestKnownAtTest(unittest.TestCase):
    def test_a_restatement_we_did_not_have_yet_is_invisible(self) -> None:
        """v1이 정정 이력을 남기는 이유 그 자체다."""
        self.assertEqual(ORIGINAL, latest_known_at([ORIGINAL, RESTATED], _utc(2025, 3, 1)))

    def test_after_we_received_it_the_restatement_wins(self) -> None:
        self.assertEqual(RESTATED, latest_known_at([ORIGINAL, RESTATED], _utc(2025, 7, 1)))

    def test_before_anything_arrived_there_is_nothing(self) -> None:
        self.assertIsNone(latest_known_at([ORIGINAL, RESTATED], _utc(2025, 1, 1)))

    def test_filing_date_alone_does_not_make_it_known(self) -> None:
        """제출 당일 즉시 알았다고 가정하면 수집이 늦은 만큼 미래를 본다."""
        late = VersionKey("0000320193-25-000012", date(2025, 3, 1), _utc(2025, 3, 20))
        self.assertIsNone(latest_known_at([late], _utc(2025, 3, 5)))

    def test_a_version_without_available_at_is_never_known(self) -> None:
        unknown = VersionKey("0000320193-25-000013", date(2025, 3, 1), None)
        self.assertIsNone(latest_known_at([unknown], _utc(2026, 1, 1)))


class RestatementCountTest(unittest.TestCase):
    def test_one_version_is_no_restatement(self) -> None:
        self.assertEqual(0, restatement_count([ORIGINAL]))

    def test_two_versions_is_one_restatement(self) -> None:
        self.assertEqual(1, restatement_count([ORIGINAL, RESTATED]))

    def test_nothing_is_zero(self) -> None:
        self.assertEqual(0, restatement_count([]))


class AccessionTest(unittest.TestCase):
    def test_hyphenless_form_is_normalised(self) -> None:
        """같은 공시가 두 키로 남으면 재처리가 영영 끝나지 않는다."""
        self.assertEqual("0000320193-25-000073", normalize_accession("000032019325000073"))

    def test_standard_form_passes_through(self) -> None:
        self.assertEqual("0000320193-25-000073", normalize_accession(" 0000320193-25-000073 "))

    def test_unreadable_values_are_none(self) -> None:
        for value in (None, "", "0000320193-25", "not-an-accession", "00003201932500007"):
            self.assertIsNone(normalize_accession(value), value)


class FormTypeTest(unittest.TestCase):
    def test_amendments_are_recognised(self) -> None:
        self.assertTrue(is_amendment("10-K/A"))
        self.assertFalse(is_amendment("10-K"))

    def test_base_form_groups_amendments_with_originals(self) -> None:
        self.assertEqual("10-K", base_form("10-K/A"))
        self.assertEqual("8-K", base_form("8-K"))

    def test_only_periodic_reports_carry_full_financials(self) -> None:
        self.assertTrue(is_periodic("10-Q/A"))
        self.assertFalse(is_periodic("8-K"))


class FilingRowTest(unittest.TestCase):
    def test_an_unsupported_form_is_refused(self) -> None:
        from investment_agent.data.fundamentals.domain.filings import Filing

        with self.assertRaises(FilingError):
            Filing.from_row({
                "accession_no": "0000320193-25-000073", "cik": "320193",
                "form_type": "S-1", "filing_date": "2026-01-01",
            })

    def test_cik_is_padded_from_the_short_form(self) -> None:
        from investment_agent.data.fundamentals.domain.filings import Filing

        filing = Filing.from_row({
            "accession_no": "0000320193-25-000073", "cik": "320193",
            "form_type": "10-K", "filing_date": "2026-01-01",
        })
        self.assertEqual("0000320193", filing.cik)

    def test_available_at_is_never_written_back(self) -> None:
        """코드가 PIT 경계를 정할 수 있으면 그 경계는 경계가 아니다."""
        from investment_agent.data.fundamentals.domain.filings import Filing

        row = Filing(
            accession_no="0000320193-25-000073", cik="0000320193",
            form_type="10-K", filing_date=date(2026, 1, 1),
        ).as_row()
        self.assertNotIn("available_at", row)


if __name__ == "__main__":
    unittest.main()
