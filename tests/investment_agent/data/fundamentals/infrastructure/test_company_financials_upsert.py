"""기업 전체 재무가 회계기간마다 한 행(financials)으로 적재되는지 검증한다."""
from __future__ import annotations

import unittest
from unittest import mock

from investment_agent.data.fundamentals.infrastructure.supabase import company_financials

ROW = {
    "cik": "0000320193",
    "period_end": "2026-06-30",
    "accession_no": "0000320193-26-000001",
    "fiscal_year": 2026,
    "fiscal_period": "Q2",
    "revenue": 100,
    "source_manifest": {"revenue": {"concept": "Revenue"}},
}


def _client(existing: list[dict] | None = None) -> tuple[mock.MagicMock, mock.MagicMock]:
    schema = mock.MagicMock()
    schema.table.return_value.upsert.return_value.execute.return_value.data = [{}]
    client = mock.MagicMock()
    client.schema.return_value = schema
    return client, schema


class CompanyFinancialsUpsertTest(unittest.TestCase):
    def _upsert(self, rows: list[dict], existing: list[dict] | None = None):
        client, schema = _client()
        with mock.patch.object(company_financials, "sb", client), mock.patch.object(
            company_financials, "select_paged_in_chunks", return_value=existing or []
        ):
            stored = company_financials.upsert_core_wide(rows)
        return stored, schema

    def test_memory_only_provenance_is_stripped(self):
        stored, schema = self._upsert([ROW])

        self.assertEqual(stored, 1)
        schema.table.assert_called_with(company_financials.T_FINANCIALS)
        payload = schema.table.return_value.upsert.call_args.args[0]
        self.assertNotIn("source_manifest", payload[0])
        self.assertEqual(payload[0]["revenue"], 100)
        self.assertEqual(payload[0]["accession_no"], "0000320193-26-000001")

    def test_one_row_per_period_is_overwritten_and_restamped(self):
        """정정·재처리는 같은 기간 행을 덮고, 쓴 시각을 옮겨 재처리 정리가 그 행을 남긴다."""
        _stored, schema = self._upsert([ROW])

        call = schema.table.return_value.upsert.call_args
        self.assertEqual("cik,period_end", call.kwargs["on_conflict"])
        self.assertIn("ingested_at", call.args[0][0])

    def test_a_label_that_moved_to_another_period_end_is_removed_first(self):
        """라벨이 다른 기간말로 옮겨 가면 옛 행이 UNIQUE(cik, 연도, 분기)로 새 행을 막는다."""
        existing = [
            {"cik": ROW["cik"], "period_end": "2026-03-31", "fiscal_year": 2026, "fiscal_period": "Q2"},
            {"cik": ROW["cik"], "period_end": "2026-06-30", "fiscal_year": 2026, "fiscal_period": "Q2"},
        ]
        _stored, schema = self._upsert([ROW], existing)

        delete = schema.table.return_value.delete.return_value
        delete.eq.assert_called_once_with("cik", ROW["cik"])
        delete.eq.return_value.eq.assert_called_once_with("period_end", "2026-03-31")


if __name__ == "__main__":
    unittest.main()
