"""발행주식수 수집은 저장 계약이 받는 서식만 보낸다.

CompanyFacts의 fact에는 `10-KT`(회계연도 변경 전환기 보고서)처럼 우리 저장 계약이
받지 않는 서식도 섞여 온다. 제출 목록 조회는 서식을 정확히 일치시키지만 그 경로는
필터를 거치지 않아 그대로 흘러갔고, DB가 `23514 filings_form_type_check`로 거절해
**그 CIK의 발행주식수가 통째로 갱신되지 않았다**(2026-09-08 실측, CIK 0000202058).
"""
from __future__ import annotations

import unittest

from investment_agent.data.fundamentals.domain.filing import SUPPORTED_FORMS
from investment_agent.data.fundamentals.infrastructure.sec.common_shares import (
    storable_share_rows,
)


def _row(form: str, accession: str = "0000202058-20-000011") -> dict:
    return {"form_type": form, "accession_no": accession, "cik": "0000202058"}


class StorableShareRowsTest(unittest.TestCase):
    def test_supported_forms_pass_through(self) -> None:
        rows = [_row(form) for form in SUPPORTED_FORMS]
        keep, dropped = storable_share_rows(rows)
        self.assertEqual(len(SUPPORTED_FORMS), len(keep))
        self.assertEqual([], dropped)

    def test_a_transition_report_is_dropped_and_named(self) -> None:
        keep, dropped = storable_share_rows([_row("10-K"), _row("10-KT")])
        self.assertEqual(["10-K"], [row["form_type"] for row in keep])
        self.assertEqual(["10-KT"], dropped)

    def test_dropping_never_empties_a_healthy_cik(self) -> None:
        """한 건 때문에 그 기업 전체를 잃지 않는다 — 그것이 전에 일어난 일이다."""
        rows = [_row("10-Q"), _row("10-KT"), _row("10-Q/A")]
        keep, _dropped = storable_share_rows(rows)
        self.assertEqual(2, len(keep))

    def test_a_missing_form_is_not_silently_kept(self) -> None:
        keep, dropped = storable_share_rows([{"accession_no": "x", "cik": "y"}])
        self.assertEqual([], keep)
        self.assertEqual(["None"], dropped)


if __name__ == "__main__":
    unittest.main()
