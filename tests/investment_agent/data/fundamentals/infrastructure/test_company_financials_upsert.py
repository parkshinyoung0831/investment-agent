"""기업 전체 재무가 canonical financials에 적재되는지 검증한다."""
from __future__ import annotations

import unittest
from unittest import mock

from investment_agent.data.fundamentals.infrastructure.supabase import company_financials


class CompanyFinancialsUpsertTest(unittest.TestCase):
    def test_atomic_replace_strips_memory_only_provenance(self):
        rows = [{
            "cik": "0000320193",
            "period_end": "2026-06-30",
            "accession_no": "0000320193-26-000001",
            "fiscal_year": 2026,
            "fiscal_period": "Q2",
            "mapping_version": "v1",
            "revenue": 100,
            "source_manifest": {"revenue": {"concept": "Revenue"}},
        }]
        schema = mock.MagicMock()
        schema.table.return_value.upsert.return_value.execute.return_value.data = [{}]
        client = mock.MagicMock()
        client.schema.return_value = schema
        with mock.patch.object(company_financials, "sb", client):
            stored = company_financials.upsert_core_wide(rows)

        self.assertEqual(stored, 1)
        schema.table.assert_called_with(company_financials.T_FINANCIALS)
        payload = schema.table.return_value.upsert.call_args.args[0]
        self.assertNotIn("source_manifest", payload[0])
        self.assertEqual(payload[0]["revenue"], 100)
        self.assertEqual(payload[0]["source_accession_no"], "0000320193-26-000001")

    def test_period_and_fiscal_conflicts_use_canonical_primary_key(self):
        schema = mock.MagicMock()
        schema.table.return_value.upsert.return_value.execute.return_value.data = [{}]
        client = mock.MagicMock()
        client.schema.return_value = schema
        row = {
            "cik": "0001037646",
            "period_end": "2026-06-30",
            "accession_no": "0001037646-26-000001",
            "fiscal_year": 2026,
            "fiscal_period": "Q2",
            "revenue": 100,
            "mapping_version": "v1",
        }

        with mock.patch.object(company_financials, "sb", client):
            company_financials.upsert_core_wide([row])

        self.assertEqual(
            schema.table.return_value.upsert.call_args.kwargs["on_conflict"],
            "cik,period_end,fiscal_period",
        )


if __name__ == "__main__":
    unittest.main()
