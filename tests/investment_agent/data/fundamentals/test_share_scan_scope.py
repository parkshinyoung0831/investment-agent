"""CompanyFacts가 덮는 공시는 문서를 받지 않는다.

CompanyFacts는 XBRL **차원을 버린다.** 그래서 어떤 공시가 CompanyFacts에 있다는 것은
그 공시의 발행주식수 사실에 클래스 차원이 없었다는 뜻이고, 없다는 것은 클래스별로
나뉘어 있었다는 뜻이다. 그 대비가 곧 "문서를 받아야 하는 공시"의 정의다.

전에는 모든 공시의 primary document(1~3MB inline XBRL)를 받아 파싱했다 —
500 CIK × 40건 = 2만 건, 약 33GB, 시간의 71%가 파싱이었다. 실측으로 92%의 CIK는
CompanyFacts가 이미 같은 값을 갖고 있어 결과가 바뀌지 않았다.
"""
from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

from investment_agent.data.fundamentals.infrastructure.sec import common_shares

CIK = "0000320193"
_COVERED = "0000320193-24-000006"
_UNCOVERED = "0000320193-26-000050"


def _filing(accession: str, filing_date: str):
    return SimpleNamespace(
        accession_no=accession, primary_document="doc.htm", form_type="10-Q",
        filing_date=filing_date, accepted_at=f"{filing_date}T21:00:00Z",
    )


def _companyfacts_row(accession: str, filed: str) -> dict:
    return {
        "cik": CIK, "share_class_key": "common", "share_class_axis": None,
        "share_class_member": None, "share_class_title": "Common Stock",
        "mapped_ticker": "AAPL", "as_of_date": filed, "shares_outstanding": 15_000_000_000.0,
        "accession_no": accession, "form_type": "10-Q", "filed_at": filed,
        "accepted_at": None, "source_concept": "dei:EntityCommonStockSharesOutstanding",
        "ticker_mapping_status": "single_class_default",
    }


class ScanScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fetched: list[str] = []

    def _run(self, *, filings, cf_rows, parsed=()):
        def get_bytes_optional(url):
            self.fetched.append(url)
            return b"<html/>"

        with (
            mock.patch.object(common_shares.sec, "get_json", return_value={"cik": CIK}),
            mock.patch.object(common_shares, "parse_common_shares_from_companyfacts",
                              return_value=list(cf_rows)),
            mock.patch.object(common_shares.sec, "filings_filed_since", return_value=filings),
            mock.patch.object(common_shares.sec, "filing_document_url",
                              side_effect=lambda c, a, d: f"https://sec/{a}"),
            mock.patch.object(common_shares.sec, "get_bytes_optional", get_bytes_optional),
            mock.patch.object(common_shares, "parse_common_shares_from_xbrl_document",
                              return_value=list(parsed)),
        ):
            return common_shares.fetch_cik_common_shares(
                CIK, cutoff=date(2016, 1, 1), active_tickers=["AAPL"])

    def test_a_covered_filing_is_never_downloaded(self) -> None:
        rows = self._run(
            filings=[_filing(_COVERED, "2024-02-01")],
            cf_rows=[_companyfacts_row(_COVERED, "2024-02-01")],
        )
        self.assertEqual([], self.fetched, "CompanyFacts가 덮는 공시를 또 받았다")
        self.assertEqual(1, len(rows))

    def test_an_uncovered_filing_is_downloaded(self) -> None:
        """CompanyFacts에 없다 = 차원이 있었다 = 문서를 봐야 클래스를 안다."""
        self._run(
            filings=[_filing(_COVERED, "2024-02-01"), _filing(_UNCOVERED, "2026-05-01")],
            cf_rows=[_companyfacts_row(_COVERED, "2024-02-01")],
        )
        self.assertEqual(["https://sec/" + _UNCOVERED], self.fetched)

    def test_companyfacts_rows_survive_alongside_class_rows(self) -> None:
        """클래스를 나중에 만든 기업의 과거 기간이 사라지면 안 된다.

        전에는 클래스가 하나라도 보이면 CompanyFacts를 통째로 버렸고, 게다가
        "문서로만 읽은 공시가 있다"며 CIK 전체를 실패시켰다.
        """
        class_row = {
            **_companyfacts_row(_UNCOVERED, "2026-05-01"),
            "share_class_key": "class_a", "share_class_member": "ClassAMember",
            "share_class_axis": "us-gaap:StatementClassOfStockAxis",
        }
        rows = self._run(
            filings=[_filing(_COVERED, "2024-02-01"), _filing(_UNCOVERED, "2026-05-01")],
            cf_rows=[_companyfacts_row(_COVERED, "2024-02-01")],
            parsed=[class_row],
        )
        keys = sorted(row["share_class_key"] for row in rows)
        self.assertEqual(["class_a", "common"], keys)


if __name__ == "__main__":
    unittest.main()
