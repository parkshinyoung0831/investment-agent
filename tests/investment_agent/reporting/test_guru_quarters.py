"""13F 화면은 분기마다 정정 공시를 결합한 한 장부를 본다(RP-07).

"최신/직전"이 같은 분기의 원본·정정이 되면 추가분 몇 줄이 그 분기 전체 장부로 읽히고,
나머지 수십 종목이 전부 "신규"로 뜬다.
"""
from __future__ import annotations

import unittest

from investment_agent.dashboard.calculations.gurus import guru_position_changes, guru_portfolio
from investment_agent.reporting.services.guru_quarters import effective_quarters

MANAGER = "0001067983"


def _filing(accession, period, filed, *, form="13F-HR", amendment=None):
    return {"accession_no": accession, "manager_cik": MANAGER, "period_end": period, "form_type": form,
            "filing_date": filed, "accepted_at": f"{filed}T10:00:00+00:00", "amendment_type": amendment}


def _position(accession, cusip, quantity):
    return {"accession_no": accession, "cusip": cusip, "quantity": quantity, "value_usd": quantity * 10.0,
            "position_kind": "SHARES", "quantity_type": "SH", "issuer_name": cusip}


FILINGS = [
    _filing("Q1", "2026-03-31", "2026-05-15"),
    _filing("Q2", "2026-06-30", "2026-08-14"),
    _filing("Q2-ADD", "2026-06-30", "2026-08-30", form="13F-HR/A", amendment="NEW HOLDINGS"),
]
POSITIONS = [
    _position("Q1", "AAA", 100), _position("Q1", "BBB", 100),
    _position("Q2", "AAA", 100), _position("Q2", "BBB", 100),
    _position("Q2-ADD", "CCC", 50),
]


class EffectiveQuartersTest(unittest.TestCase):
    def test_a_quarter_with_an_addition_is_one_filing_with_the_whole_book(self) -> None:
        filings, positions = effective_quarters(FILINGS, POSITIONS)
        by_period = {row["period_end"]: row for row in filings}
        self.assertEqual({"2026-03-31", "2026-06-30"}, set(by_period))
        self.assertEqual("Q2-ADD", by_period["2026-06-30"]["accession_no"])
        q2 = [row for row in positions if row["accession_no"] == "Q2-ADD"]
        self.assertEqual({"AAA", "BBB", "CCC"}, {row["cusip"] for row in q2})

    def test_changes_compare_whole_quarters_not_the_addition_alone(self) -> None:
        filings, positions = effective_quarters(FILINGS, POSITIONS)
        latest, previous = sorted(filings, key=lambda row: row["period_end"], reverse=True)
        book = {}
        for row in positions:
            book.setdefault(row["accession_no"], []).append(row)
        changes = guru_position_changes(book[latest["accession_no"]], book[previous["accession_no"]], {})
        self.assertEqual({"CCC": "new"}, {row["cusip"]: row["change"] for row in changes})
        self.assertEqual(3, guru_portfolio(book[latest["accession_no"]], {})["position_count"])

    def test_without_the_combination_the_addition_would_look_like_the_previous_book(self) -> None:
        """결합하지 않은 옛 방식: 같은 분기의 정정이 '직전'이 된다 — 이 테스트가 그 함정을 문서로 남긴다."""
        ordered = sorted(FILINGS, key=lambda row: (row["period_end"], row["filing_date"]), reverse=True)
        self.assertEqual(("Q2-ADD", "Q2"), (ordered[0]["accession_no"], ordered[1]["accession_no"]))

    def test_a_restatement_replaces_earlier_rows_and_a_later_addition_is_kept(self) -> None:
        filings = [
            _filing("R0", "2026-06-30", "2026-08-14"),
            _filing("R1", "2026-06-30", "2026-08-20", form="13F-HR/A", amendment="RESTATEMENT"),
            _filing("R2", "2026-06-30", "2026-08-28", form="13F-HR/A", amendment="NEW HOLDINGS"),
        ]
        positions = [_position("R0", "OLD", 1), _position("R1", "AAA", 1), _position("R2", "CCC", 1)]
        events, combined = effective_quarters(filings, positions)
        self.assertEqual(["R2"], [row["accession_no"] for row in events])
        self.assertEqual({"AAA", "CCC"}, {row["cusip"] for row in combined}, "재작성본에 없는 원본 행은 버린다")

    def test_a_notice_only_quarter_is_kept_as_it_is(self) -> None:
        notice = _filing("NT", "2026-06-30", "2026-08-14", form="13F-NT")
        events, combined = effective_quarters([notice], [])
        self.assertEqual(["NT"], [row["accession_no"] for row in events])
        self.assertEqual([], combined)


if __name__ == "__main__":
    unittest.main()
