"""13F 원시 행 보존과 CINS 분류를 검증한다."""
from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from investment_agent.data.institutional.domain.parser import identifier_type, normalize_positions, parse_information_table


_FIXTURE = Path(__file__).parent / "fixtures" / "infotable_basic.xml"


class PositionParserTest(unittest.TestCase):
    def test_preserves_sec_source_fields_and_row_numbers(self):
        rows = parse_information_table(_FIXTURE.read_text(encoding="utf-8"))

        self.assertEqual([row.source_row_no for row in rows], [1, 2, 3])
        self.assertEqual(rows[0].title_of_class, "COM")
        self.assertEqual(rows[0].investment_discretion, "SOLE")
        self.assertEqual(rows[0].voting_sole, 1000)
        self.assertEqual(rows[0].voting_shared, 0)
        self.assertEqual(rows[2].voting_none, 9999)
        self.assertEqual(rows[1].position_kind, "PUT")

    def test_does_not_aggregate_combination_style_duplicate_rows(self):
        rows = parse_information_table(_FIXTURE.read_text(encoding="utf-8"))
        duplicated = [rows[0], rows[0]]
        _scale, positions = normalize_positions(
            duplicated, schema_version="INFOTABLE", period_end=date(2024, 3, 31)
        )

        self.assertEqual(len(positions), 2)
        self.assertEqual([position.source_row_no for position in positions], [1, 1])

    def test_identifier_type_distinguishes_cusip_and_cins(self):
        self.assertEqual(identifier_type("037833100"), "CUSIP")
        self.assertEqual(identifier_type("G5960L103"), "CINS")
        with self.assertRaises(ValueError):
            identifier_type("BAD")


if __name__ == "__main__":
    unittest.main()
