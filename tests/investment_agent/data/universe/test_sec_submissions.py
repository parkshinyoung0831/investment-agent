"""공용 SEC submissions 파서의 키 매핑 계약.

`src/investment_agent/data/universe/sec.py`는 gurus 13F와 fundamentals 기업 공시가 **함께** 쓰는 헬퍼다.
여기서 키가 어긋나면 예외가 아니라 **0건**으로 끝나서, 두 파이프라인이 매일 초록으로
돌면서 아무것도 적재하지 않는다.
"""
from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from investment_agent.data.universe.infrastructure.sources import sec


def _document() -> dict:
    """SEC submissions 응답의 모양(키 이름이 계약의 전부다)."""
    return {
        "filings": {
            "recent": {
                # 서식 배열만 `form`이고 나머지는 camelCase다. 이 비대칭이 함정이다.
                "form": ["13F-HR", "4", "13F-HR/A"],
                "accessionNumber": [
                    "0000950123-24-002518",
                    "0000950123-24-000111",
                    "0000950123-24-005622",
                ],
                "reportDate": ["2023-12-31", "2024-01-05", "2024-03-31"],
                "filingDate": ["2024-02-14", "2024-01-08", "2024-05-15"],
                "acceptanceDateTime": [
                    "2024-02-14T16:01:00.000Z",
                    "2024-01-08T18:22:00.000Z",
                    "2024-05-15T16:04:00.000Z",
                ],
                "primaryDocument": ["brk.xml", "form4.xml", "brk-a.xml"],
                "items": ["", "", ""],
            },
            "files": [],
        }
    }


class SubmissionFilingsTest(unittest.TestCase):
    def test_form_array_is_read_from_the_form_key(self) -> None:
        rows = sec.submission_filings(_document(), forms={"13F-HR", "13F-HR/A"})

        self.assertEqual(len(rows), 2, "`form` 키를 못 읽으면 조용히 0건이 된다")
        self.assertEqual(
            [row.accession_no for row in rows],
            ["0000950123-24-002518", "0000950123-24-005622"],
        )

    def test_unwanted_forms_are_filtered_out(self) -> None:
        rows = sec.submission_filings(_document(), forms={"13F-HR"})

        self.assertEqual([row.form_type for row in rows], ["13F-HR"])

    def test_report_date_is_the_period_end_and_filing_date_is_when_it_was_filed(self) -> None:
        """두 날짜가 뒤바뀌면 조회 창이 빗나가고 보존 삭제가 엉뚱한 행을 지운다."""
        rows = sec.submission_filings(_document(), forms={"13F-HR", "13F-HR/A"})

        self.assertEqual(rows[0].report_date, "2023-12-31")
        self.assertEqual(rows[0].filing_date, "2024-02-14")
        for row in rows:
            with self.subTest(accession=row.accession_no):
                self.assertLessEqual(row.report_date, row.filing_date)

    def test_filings_filed_since_cuts_on_the_filing_date(self) -> None:
        with mock.patch.object(sec, "submissions", return_value=_document()):
            rows = sec.filings_filed_since(
                1067983, forms=("13F-HR", "13F-HR/A"), cutoff=date(2024, 3, 1)
            )

        self.assertEqual([row.accession_no for row in rows], ["0000950123-24-005622"])

    def test_older_submission_pages_are_followed(self) -> None:
        """13F 운용사는 10년치가 페이지로 나뉜다 — 최근 페이지만 보면 이력이 통째로 빈다."""
        document = _document()
        document["filings"]["files"] = [
            {"name": "CIK0001067983-submissions-001.json",
             "filingFrom": "2016-01-01", "filingTo": "2020-12-31"}
        ]
        older = {
            "form": ["13F-HR"],
            "accessionNumber": ["0000950123-20-000999"],
            "reportDate": ["2020-09-30"],
            "filingDate": ["2020-11-16"],
            "acceptanceDateTime": ["2020-11-16T16:00:00.000Z"],
            "primaryDocument": ["old.xml"],
            "items": [""],
        }
        with mock.patch.object(sec, "submissions", return_value=document), \
             mock.patch.object(sec, "get_json", return_value=older):
            rows = sec.filings_filed_since(
                1067983, forms=("13F-HR", "13F-HR/A"), cutoff=date(2016, 1, 1)
            )

        self.assertIn("0000950123-20-000999", [row.accession_no for row in rows])


class CompanyFactsKeyContractTest(unittest.TestCase):
    """fundamentals 일별 경로가 읽는 SEC 키 계약.

    `src/investment_agent/data/universe/sec.py`와 별개로 CompanyFacts 어댑터도 SEC 원본
    JSON을 직접 읽는다. 여기서 키를 내부 용어(`form_type`)로 읽으면 예외 없이 0건이
    되어, fundamentals_daily가 매일 성공하면서 공시를 하나도 못 찾는다. 실제로
    그랬다.
    """

    def _submissions(self) -> dict:
        return {
            "filings": {
                "recent": {
                    "form": ["10-Q", "8-K", "10-K"],
                    "accessionNumber": ["ACC-1", "ACC-2", "ACC-3"],
                    "filingDate": ["2026-05-01", "2026-05-02", "2026-02-01"],
                    "reportDate": ["2026-03-31", "2026-05-01", "2025-12-31"],
                    "isXBRL": [1, 1, 1],
                }
            }
        }

    def test_financial_filings_reads_the_form_key(self) -> None:
        from investment_agent.data.fundamentals.infrastructure.sec import companyfacts

        rows = companyfacts.financial_filings(self._submissions())

        self.assertEqual(
            [row.form_type for row in rows],
            ["10-Q", "10-K"],
            "`form` 키를 못 읽으면 일별 동기화가 조용히 0건이 된다",
        )
        self.assertEqual([row.accession_no for row in rows], ["ACC-1", "ACC-3"])

    def test_unit_entries_are_filtered_on_the_form_key(self) -> None:
        """Company Facts unit entry도 원본 이름 `form`을 쓴다."""
        entry = {
            "accn": "ACC-1", "fy": 2026, "fp": "Q1", "form": "10-Q",
            "filed": "2026-05-01", "start": "2026-01-01", "end": "2026-03-31",
            "val": 100,
        }
        self.assertIn("form", entry)
        self.assertNotIn("form_type", entry)
        source = Path("src/investment_agent/data/fundamentals/infrastructure/sec/companyfacts.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(
            'entry.get("form_type")',
            source,
            "unit entry를 form_type으로 읽으면 모든 fact가 걸러진다",
        )


if __name__ == "__main__":
    unittest.main()
