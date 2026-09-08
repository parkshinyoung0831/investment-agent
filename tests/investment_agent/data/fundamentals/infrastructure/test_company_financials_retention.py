"""Fundamentals 품질 이슈 기록의 실패 전파 계약."""
from __future__ import annotations

import unittest
from unittest import mock

from investment_agent.data.fundamentals.infrastructure.supabase import company_financials


class OperationalRetentionTest(unittest.TestCase):
    def test_collector_repository_does_not_delete_alert_history(self):
        self.assertFalse(hasattr(company_financials, "prune_operational_rows"))

    def test_anomalies_are_logged_without_a_database_write(self):
        anomalies = [
            {"cik": "0000000001", "fiscal_year": 2026, "fiscal_period": "Q1",
             "reason": "mapping_conflict", "detail": {"column_key": "revenue"}},
            {"cik": "0000000002", "fiscal_year": 2026, "fiscal_period": "Q2",
             "reason": "mapping_conflict", "detail": {"column_key": "net_income"}},
        ]

        with mock.patch.object(company_financials, "log") as log:
            reported = company_financials.report_anomalies(anomalies)

        self.assertEqual(reported, 2)
        self.assertEqual(log.warning.call_count, 3)

    def test_core_upsert_carries_source_provenance_without_memory_manifest(self):
        """canonical 정책은 우리가 처리한 시각(ingested_at)이 아니라 공시 자체의
        provenance(source_accession_no/source_filing_date)를 PIT 경계로 쓴다."""
        row = {
            "cik": "0000000001",
            "period_end": "2026-03-31",
            "accession_no": "0000000001-26-000001",
            "filing_date": "2026-05-01",
            "fiscal_year": 2026,
            "fiscal_period": "Q1",
            "mapping_version": "v1",
            "revenue": 100,
            "source_manifest": {"revenue": {"raw_tag": "Revenues"}},
        }
        schema = mock.MagicMock()
        schema.table.return_value.upsert.return_value.execute.return_value = mock.Mock(data=[{}])
        client = mock.MagicMock()
        client.schema.return_value = schema

        with mock.patch.object(company_financials, "sb", client):
            self.assertEqual(company_financials.upsert_core_wide([row]), 1)

        payload = schema.table.return_value.upsert.call_args.args[0]
        self.assertEqual(
            payload,
            [{
                "cik": "0000000001",
                "period_end": "2026-03-31",
                "fiscal_year": 2026,
                "fiscal_period": "Q1",
                "mapping_version": "v1",
                "revenue": 100,
                "source_accession_no": "0000000001-26-000001",
                "source_filing_date": "2026-05-01",
            }],
        )
        self.assertIn("source_manifest", row)


if __name__ == "__main__":
    unittest.main()
