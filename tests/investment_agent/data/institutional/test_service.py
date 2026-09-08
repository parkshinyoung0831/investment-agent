"""v1 13F writer는 SEC 원문 행과 provenance를 함께 남긴다."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import unittest

from investment_agent.data.institutional.repository import SCHEMA
from investment_agent.data.institutional.application.service import refresh_institutional
from tests.investment_agent.fakes import FakeDatabase

CIK = "0001067983"
ACCESSION = "0001067983-26-000001"


def _record(*, parsed_line_count: int = 1) -> SimpleNamespace:
    position = SimpleNamespace(
        source_row_no=1, issuer_name="APPLE INC", cusip="037833100", identifier_type="CUSIP",
        title_of_class="COM", value_usd=1000, quantity=10, quantity_type="SH",
        position_kind="SHARES", investment_discretion="SOLE", other_manager=None,
        voting_sole=10, voting_shared=0, voting_none=0,
    )
    return SimpleNamespace(
        accession_no=ACCESSION, manager_cik=CIK, period_end=date(2026, 3, 31),
        form_type="13F-HR", report_type="13F HOLDINGS REPORT", filing_date=date(2026, 5, 15),
        accepted_at="2026-05-15T20:00:00+00:00", amendment_type=None, amendment_no=None,
        reported_value_usd=1000, reported_line_count=1, confidential_omitted=False,
        source_url="https://www.sec.gov/Archives/example", content_sha256="a" * 64,
        positions=(position,), parsed_line_count=parsed_line_count,
    )


class InstitutionalWriterTest(unittest.TestCase):
    def _db(self) -> FakeDatabase:
        return FakeDatabase()

    def test_writes_filing_before_its_raw_positions(self) -> None:
        # active_managers()는 이제 코드 설정의 실제 7인을 그대로 돌려준다. 이
        # filing_source는 CIK(Warren Buffett) 요청에만 응답하고 나머지 6명은
        # 빈 결과로 건너뛴다 — 그래야 그들이 실패로 잡히지 않는다.
        db = self._db()
        result = refresh_institutional(
            db, since=date(2016, 1, 1),
            filing_source=lambda cik, _since: [_record()] if cik == CIK else [],
        )

        self.assertEqual((1, 1), (result.filings, result.positions))
        self.assertEqual((), result.failures)
        self.assertEqual((SCHEMA, "filings"), db.upserts[0][0])
        self.assertEqual((SCHEMA, "positions"), db.upserts[1][0])
        self.assertEqual("accession_no", db.upserts[0][2])
        self.assertEqual("accession_no,source_row_no", db.upserts[1][2])
        self.assertEqual("037833100", db.upserts[1][1][0]["identifier"])

    def test_line_count_mismatch_never_persists_a_partial_filing(self) -> None:
        db = self._db()
        result = refresh_institutional(
            db, since=date(2016, 1, 1),
            filing_source=lambda cik, _since: [_record(parsed_line_count=2)] if cik == CIK else [],
        )

        self.assertEqual(1, len(result.failures))
        self.assertEqual([], db.upserts)


if __name__ == "__main__":
    unittest.main()
