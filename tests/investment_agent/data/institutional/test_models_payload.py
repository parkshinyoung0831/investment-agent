"""FilingRecord payload 계약 단위 테스트. 외부 의존성 없음."""
from __future__ import annotations

import unittest

from tests.investment_agent.data.institutional._factories import make_filing_record, make_position

# ingest_13f_filing RPC가 읽는 p_filing 키. 이 집합이 깨지면 적재가 조용히 빈다.
_EXPECTED_FILING_KEYS = {
    "accession_no",
    "manager_cik",
    "period_end",
    "form_type",
    "report_type",
    "filing_date",
    "accepted_at",
    "amendment_type",
    "amendment_no",
    "reported_value_usd",
    "reported_line_count",
    "confidential_omitted",
    "source_url",
    "content_sha256",
}


class FilingPayloadTest(unittest.TestCase):
    def test_filing_payload_key_contract_is_stable(self):
        payload = make_filing_record().filing_payload()

        self.assertEqual(set(payload), _EXPECTED_FILING_KEYS)

    def test_filing_payload_dates_are_iso_strings(self):
        payload = make_filing_record().filing_payload()

        self.assertEqual(payload["period_end"], "2024-03-31")
        self.assertEqual(payload["filing_date"], "2024-05-15")


class PositionsPayloadTest(unittest.TestCase):
    def test_positions_payload_contract_is_stable(self):
        record = make_filing_record(
            positions=(
                make_position(),
                make_position(
                    cusip="594918104",
                    issuer_name="Microsoft Corp",
                    position_kind="CALL",
                ),
            )
        )

        rows = record.positions_payload()

        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertTrue(first["cusip"])
        self.assertTrue(first["issuer_name"])
        self.assertGreater(first["source_row_no"], 0)
        self.assertIn(first["identifier_type"], {"CUSIP", "CINS"})
        self.assertGreaterEqual(first["value_usd"], 0)
        self.assertIn(first["quantity_type"], {"SH", "PRN"})
        self.assertIn(first["position_kind"], {"SHARES", "CALL", "PUT"})

    def test_positions_payload_empty_for_zero_holdings(self):
        record = make_filing_record(positions=())

        self.assertEqual(record.positions_payload(), [])


if __name__ == "__main__":
    unittest.main()
