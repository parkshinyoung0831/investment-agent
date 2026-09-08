"""SEC submissions JSON -> 내부 공시 dict 매핑 계약.

여기서 어긋나면 예외가 아니라 **0건**으로 끝난다. 세그먼트 동기화가 매일 초록으로
돌면서 아무것도 적재하지 않았고, 그 사실이 한참 뒤 대시보드의 빈 화면으로만 드러났다.
"""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.data.fundamentals.infrastructure.sec import filing_documents


def _submissions_document() -> dict:
    """SEC submissions 응답의 모양을 그대로 흉내 낸다(키 이름이 계약의 전부다)."""
    return {
        "filings": {
            "recent": {
                # SEC는 서식 배열만 `form`이고 나머지는 camelCase다. 이 비대칭이 함정이다.
                "form": ["10-Q", "8-K", "10-Q"],
                "accessionNumber": [
                    "0000006281-26-000073",
                    "0000006281-26-000060",
                    "0000006281-26-000040",
                ],
                "reportDate": ["2026-08-01", "2026-07-15", "2026-05-02"],
                "filingDate": ["2026-08-19", "2026-07-16", "2026-05-21"],
                "acceptanceDateTime": [
                    "2026-08-19T16:31:00.000Z",
                    "2026-07-16T08:02:00.000Z",
                    "2026-05-21T16:12:00.000Z",
                ],
                "primaryDocument": ["adi-20260801.htm", "adi-8k.htm", "adi-20260502.htm"],
                "isXBRL": [1, 1, 1],
            }
        }
    }


class SubmissionsMappingTest(unittest.TestCase):
    def test_form_array_is_read_from_the_form_key(self) -> None:
        rows = filing_documents._filings_from_document(
            _submissions_document(), forms={"10-Q"}
        )

        self.assertEqual(len(rows), 2, "`form` 키를 못 읽으면 조용히 0건이 된다")
        self.assertEqual(
            [row["accession_no"] for row in rows],
            ["0000006281-26-000073", "0000006281-26-000040"],
        )

    def test_report_date_is_the_period_end_and_filing_date_is_when_it_was_filed(self) -> None:
        """두 날짜가 뒤바뀌면 조회 창이 영원히 빗나가고 보존 삭제가 엉뚱한 행을 지운다."""
        rows = filing_documents._filings_from_document(
            _submissions_document(), forms={"10-Q"}
        )

        first = rows[0]
        self.assertEqual(first["report_date"], "2026-08-01")
        self.assertEqual(first["filing_date"], "2026-08-19")
        for row in rows:
            with self.subTest(accession=row["accession_no"]):
                # 보고기간이 끝나기 전에 제출할 수는 없다.
                self.assertLessEqual(row["report_date"], row["filing_date"])

    def test_non_xbrl_filings_are_skipped(self) -> None:
        document = _submissions_document()
        document["filings"]["recent"]["isXBRL"] = [0, 1, 1]

        rows = filing_documents._filings_from_document(document, forms={"10-Q"})

        self.assertEqual([row["accession_no"] for row in rows], ["0000006281-26-000040"])

    def test_filings_filed_since_filters_on_the_filing_date(self) -> None:
        """보고기간이 아니라 제출일로 잘라야 '최근 N일에 들어온 공시'가 된다."""
        original = filing_documents.submissions
        filing_documents.submissions = lambda cik: _submissions_document()
        try:
            rows = filing_documents.filings_filed_since(
                6281, forms=("10-Q",), cutoff=date(2026, 7, 27)
            )
        finally:
            filing_documents.submissions = original

        self.assertEqual([row["accession_no"] for row in rows], ["0000006281-26-000073"])


if __name__ == "__main__":
    unittest.main()
