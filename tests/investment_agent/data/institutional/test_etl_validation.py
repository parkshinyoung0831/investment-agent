"""13F 적재 전 검증 계약.

SEC 요약(tableEntryTotal)이 세는 것은 informationTable의 **원시 행**이다.
13F COMBINATION REPORT는 같은 증권을 자회사 운용사마다 한 행씩 신고하므로,
(cusip, 종류, 단위)로 합산한 positions는 늘 원시 행보다 적다. 합산 결과와 요약을
비교하면 정상 공시가 통째로 버려진다 — 버크셔가 매 분기 그렇게 빠졌다.
"""
from __future__ import annotations

import unittest

from investment_agent.data.institutional.application.etl import _validate_filing
from tests.investment_agent.data.institutional._factories import make_filing_record, make_position


class ValidateFilingTest(unittest.TestCase):
    def test_plain_holdings_report_passes(self) -> None:
        record = make_filing_record(
            positions=(
                make_position(cusip="037833100", value_usd=1_000),
                make_position(cusip="594918104", value_usd=2_000),
            )
        )

        _validate_filing(record)  # 예외가 없으면 통과

    def test_combination_report_with_aggregated_positions_passes(self) -> None:
        """증권 2개가 자회사 5곳에 걸쳐 5행으로 신고된 경우."""
        record = make_filing_record(
            report_type="13F COMBINATION REPORT",
            positions=(
                make_position(cusip="037833100", value_usd=1_000),
                make_position(cusip="594918104", value_usd=2_000),
            ),
            reported_line_count=5,   # SEC 요약이 세는 원시 행
            parsed_line_count=5,     # 파서가 실제로 읽은 원시 행
        )

        _validate_filing(record)

    def test_lost_rows_still_fail_closed(self) -> None:
        """진짜 파싱 손실(원시 행이 요약보다 적음)은 그대로 막아야 한다."""
        record = make_filing_record(
            report_type="13F COMBINATION REPORT",
            positions=(make_position(value_usd=3_000),),
            reported_line_count=5,
            parsed_line_count=3,  # 2행을 놓쳤다
        )

        with self.assertRaisesRegex(ValueError, "holding row count mismatch"):
            _validate_filing(record)

    def test_missing_report_type_fails(self) -> None:
        record = make_filing_record()
        object.__setattr__(record, "report_type", None)

        with self.assertRaisesRegex(ValueError, "missing report type"):
            _validate_filing(record)

    def test_missing_pit_provenance_fails_closed(self) -> None:
        for field, message in (
            ("accepted_at", "missing accepted_at"),
            ("source_url", "missing source_url"),
            ("content_sha256", "invalid content hash"),
        ):
            record = make_filing_record()
            object.__setattr__(record, field, None if field != "content_sha256" else "bad")
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, message):
                    _validate_filing(record)


if __name__ == "__main__":
    unittest.main()
