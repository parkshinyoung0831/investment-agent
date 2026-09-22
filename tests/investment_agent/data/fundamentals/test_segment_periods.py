"""세그먼트 기간말 잔액이 다른 기준일에서 섞이지 않는지 검증한다."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd

from investment_agent.data.fundamentals.application.process_filing import (
    current_segment_facts,
)
from investment_agent.data.fundamentals.domain.services.normalize_segment_facts import (
    bulk_frames_to_filings_and_facts,
)


class CurrentSegmentPeriodTest(unittest.TestCase):
    def test_daily_path_requires_exact_report_date_for_instant_facts(self) -> None:
        facts = [
            {"id": "stale-instant", "period_end": "2026-05-31", "period_kind": "instant"},
            {"id": "current-instant", "period_end": "2026-06-30", "period_kind": "instant"},
            {"id": "nearby-flow", "period_end": "2026-06-01", "period_kind": "quarter"},
        ]

        selected = current_segment_facts(
            facts,
            filing={"report_date": "2026-06-30"},
            period_kind="quarter",
            fiscal_year=2026,
            fiscal_period="Q2",
        )

        self.assertEqual(
            [row["id"] for row in selected],
            ["current-instant", "nearby-flow"],
        )

    def test_bulk_path_applies_the_same_instant_date_contract(self) -> None:
        accession = "0000000001-26-000001"
        frames = SimpleNamespace(
            sub_df=pd.DataFrame([{
                "adsh": accession,
                "cik": 1,
                "form_type": "10-K",
                "fy": 2026,
                "fp": "FY",
                "period": 20260630,
                "filed": 20260801,
            }]),
            num_df=pd.DataFrame([
                {
                    "adsh": accession,
                    "tag": "Assets",
                    "ddate": 20260531,
                    "qtrs": 0,
                    "uom": "USD",
                    "segments": (
                        "us-gaap:StatementBusinessSegmentsAxis="
                        "acme:CloudMember;"
                    ),
                    "coreg": "",
                    "value": 90,
                },
                {
                    "adsh": accession,
                    "tag": "Assets",
                    "ddate": 20260630,
                    "qtrs": 0,
                    "uom": "USD",
                    "segments": (
                        "us-gaap:StatementBusinessSegmentsAxis="
                        "acme:CloudMember;"
                    ),
                    "coreg": "",
                    "value": 100,
                },
                {
                    "adsh": accession,
                    "tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
                    "ddate": 20260601,
                    "qtrs": 4,
                    "uom": "USD",
                    "segments": (
                        "us-gaap:StatementBusinessSegmentsAxis="
                        "acme:CloudMember;"
                    ),
                    "coreg": "",
                    "value": 200,
                },
            ]),
        )

        filing_rows, facts_by_accession, _ = bulk_frames_to_filings_and_facts(
            frames,
            ciks={1},
            period_kind="annual",
        )

        self.assertEqual(filing_rows[0]["facts_count"], 2)
        # sub_df는 load_batch에서 form -> form_type으로 바뀐 뒤에 도착한다. 원본 이름으로
        # 읽으면 조용히 빈 값이 되고, filing_runs_form_check가 그 분기 배치를 통째로
        # 되돌려 세그먼트 백필이 31개 분기 전부 실패한다.
        self.assertEqual(filing_rows[0]["form_type"], "10-K")
        self.assertEqual(
            sorted(row["period_end"] for row in facts_by_accession[accession]),
            ["2026-06-01", "2026-06-30"],
        )


class UnreadableQuarterCountTest(unittest.TestCase):
    """`qtrs`를 읽지 못한 행은 시점값으로 접지 않고 버린다."""

    ACCESSION = "0000000002-26-000001"

    def _frames(self, qtrs):
        return SimpleNamespace(
            sub_df=pd.DataFrame([{
                "adsh": self.ACCESSION, "cik": 2, "form_type": "10-Q",
                "fy": 2026, "fp": "Q2", "period": 20260630, "filed": 20260801,
            }]),
            num_df=pd.DataFrame([{
                "adsh": self.ACCESSION,
                "tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
                "ddate": 20260630, "qtrs": qtrs, "uom": "USD",
                "segments": ("us-gaap:StatementBusinessSegmentsAxis="
                             "acme:CloudMember;"),
                "coreg": "", "value": 200,
            }]),
        )

    def _facts(self, qtrs):
        _, facts_by_accession, _ = bulk_frames_to_filings_and_facts(
            self._frames(qtrs), ciks={2}, period_kind="quarter",
        )
        return facts_by_accession.get(self.ACCESSION, [])

    def test_a_readable_quarter_count_still_produces_a_flow_fact(self):
        facts = self._facts(1)
        self.assertEqual(len(facts), 1)
        self.assertFalse(facts[0]["is_instant"])
        self.assertEqual(facts[0]["period_start"], "2026-03-30")

    def test_an_unreadable_quarter_count_is_dropped_not_called_instant(self):
        """0으로 접으면 3개월 흐름인 매출이 시점 잔액으로 저장된다."""
        for unreadable in (None, "", "N/A", float("nan")):
            with self.subTest(qtrs=unreadable):
                self.assertEqual(self._facts(unreadable), [])


class UnreadableFiscalYearTest(unittest.TestCase):
    """`fy`를 읽지 못한 행은 `period_end.year`로 접지 않고 버린다(감사 FD3-02).

    실측(70개 분기, 433,717개 sub.txt 행): 2.84%(12,303행)가 fy 결측/파싱 불가다 —
    무시할 수 없는 비율이라 FD3-01과 같은 규약(못 읽으면 행을 버린다)으로 맞췄다.
    """

    ACCESSION = "0000000003-26-000001"

    def _frames(self, fy):
        return SimpleNamespace(
            sub_df=pd.DataFrame([{
                "adsh": self.ACCESSION, "cik": 3, "form_type": "10-Q",
                "fy": fy, "fp": "Q2", "period": 20260630, "filed": 20260801,
            }]),
            num_df=pd.DataFrame([{
                "adsh": self.ACCESSION,
                "tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
                "ddate": 20260630, "qtrs": 1, "uom": "USD",
                "segments": ("us-gaap:StatementBusinessSegmentsAxis="
                             "acme:CloudMember;"),
                "coreg": "", "value": 200,
            }]),
        )

    def _facts(self, fy):
        _, facts_by_accession, _ = bulk_frames_to_filings_and_facts(
            self._frames(fy), ciks={3}, period_kind="quarter",
        )
        return facts_by_accession.get(self.ACCESSION, [])

    def test_a_readable_fiscal_year_still_produces_a_fact(self):
        facts = self._facts(2026)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["fiscal_year"], 2026)

    def test_an_unreadable_fiscal_year_is_dropped_not_filled_from_period_end(self):
        for unreadable in (None, "", "N/A", float("nan")):
            with self.subTest(fy=unreadable):
                self.assertEqual(self._facts(unreadable), [])

if __name__ == "__main__":
    unittest.main()
