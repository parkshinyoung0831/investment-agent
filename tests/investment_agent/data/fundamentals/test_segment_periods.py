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


if __name__ == "__main__":
    unittest.main()
