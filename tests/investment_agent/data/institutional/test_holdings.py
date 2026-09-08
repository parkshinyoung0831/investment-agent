"""13F 정정을 잘못 다루면 보유가 두 배가 되거나 절반이 사라진다."""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.data.institutional.domain.holdings import (
    AMENDMENT_NEW_HOLDINGS,
    AMENDMENT_RESTATEMENT,
    Filing13F,
    HoldingsError,
    Position,
    effective_filings,
    portfolio_weights,
    share_positions,
)

PERIOD = date(2026, 6, 30)


def _filing(
    accession: str, *, form: str = "13F-HR", amendment: str | None = None, filed: int = 15
) -> Filing13F:
    return Filing13F(
        accession_no=accession,
        manager_cik="0001067983",
        period_end=PERIOD,
        form_type=form,
        filing_date=date(2026, 8, filed),
        amendment_type=amendment,
        amendment_no=1 if amendment else None,
    )


def _position(row: int, identifier: str, value: float, kind: str = "SHARES") -> Position:
    return Position(
        accession_no="0001067983-26-000001",
        source_row_no=row,
        issuer_name="EXAMPLE",
        identifier=identifier,
        value_usd=value,
        quantity=100,
        position_kind=kind,
    )


class EffectiveFilingsTest(unittest.TestCase):
    def test_a_plain_original_is_effective(self) -> None:
        original = _filing("0001067983-26-000001")
        self.assertEqual([original], effective_filings([original]))

    def test_a_restatement_replaces_the_original(self) -> None:
        """전체를 다시 낸 것이다. 원본까지 세면 보유가 두 배가 된다."""
        original = _filing("0001067983-26-000001")
        restated = _filing("0001067983-26-000009", form="13F-HR/A",
                           amendment=AMENDMENT_RESTATEMENT, filed=25)
        self.assertEqual([restated], effective_filings([original, restated]))

    def test_new_holdings_adds_to_the_original(self) -> None:
        """빠뜨린 것을 덧붙인 것이다. 원본을 버리면 보유가 절반이 된다."""
        original = _filing("0001067983-26-000001")
        added = _filing("0001067983-26-000010", form="13F-HR/A",
                        amendment=AMENDMENT_NEW_HOLDINGS, filed=25)
        self.assertEqual([original, added], effective_filings([original, added]))

    def test_the_last_restatement_wins(self) -> None:
        first = _filing("0001067983-26-000009", form="13F-HR/A",
                        amendment=AMENDMENT_RESTATEMENT, filed=20)
        second = _filing("0001067983-26-000011", form="13F-HR/A",
                         amendment=AMENDMENT_RESTATEMENT, filed=28)
        self.assertEqual([second], effective_filings([first, second]))

    def test_quarters_are_handled_independently(self) -> None:
        q2 = _filing("0001067983-26-000001")
        q1 = Filing13F(
            accession_no="0001067983-26-000000", manager_cik="0001067983",
            period_end=date(2026, 3, 31), form_type="13F-HR", filing_date=date(2026, 5, 15),
        )
        self.assertEqual(2, len(effective_filings([q2, q1])))

    def test_nothing_in_nothing_out(self) -> None:
        self.assertEqual([], effective_filings([]))


class FilingRowTest(unittest.TestCase):
    def test_a_period_after_the_filing_is_refused(self) -> None:
        """13F는 분기말 뒤에 낸다. 뒤집혀 있으면 그 행은 미래를 보고한 것이다."""
        with self.assertRaises(HoldingsError):
            Filing13F.from_row({
                "accession_no": "0001067983-26-000001", "manager_cik": "0001067983",
                "period_end": "2026-09-30", "filing_date": "2026-08-15",
                "form_type": "13F-HR", "reported_value_usd": 100.0,
            })

    def test_amendment_flag_follows_the_form_type(self) -> None:
        filing = Filing13F.from_row({
            "accession_no": "0001067983-26-000009", "manager_cik": "0001067983",
            "period_end": "2026-06-30", "filing_date": "2026-08-25",
            "form_type": "13F-HR/A", "amendment_type": AMENDMENT_RESTATEMENT,
            "amendment_no": 1, "reported_value_usd": 100.0,
        })
        self.assertTrue(filing.is_amendment)
        self.assertTrue(filing.replaces_original)


class PositionTest(unittest.TestCase):
    def test_options_are_not_share_positions(self) -> None:
        """풋을 보유로 세면 하락 베팅이 매수로 둔갑한다."""
        positions = [
            _position(1, "037833100", 100.0),
            _position(2, "037833100", 50.0, kind="PUT"),
        ]
        self.assertEqual(1, len(share_positions(positions)))

    def test_an_unknown_kind_is_refused(self) -> None:
        with self.assertRaises(HoldingsError):
            Position.from_row({
                "accession_no": "x", "source_row_no": 1, "issuer_name": "E",
                "identifier": "037833100", "value_usd": 1.0, "quantity": 1,
                "position_kind": "SWAP",
            })

    def test_a_negative_value_is_refused(self) -> None:
        with self.assertRaises(HoldingsError):
            Position.from_row({
                "accession_no": "x", "source_row_no": 1, "issuer_name": "E",
                "identifier": "037833100", "value_usd": -1.0, "quantity": 1,
                "position_kind": "SHARES",
            })


class PortfolioWeightsTest(unittest.TestCase):
    def test_weights_sum_to_one(self) -> None:
        weights = portfolio_weights([
            _position(1, "037833100", 75.0),
            _position(2, "594918104", 25.0),
        ])
        self.assertAlmostEqual(1.0, sum(weights.values()))
        self.assertAlmostEqual(0.75, weights["037833100"])

    def test_options_do_not_dilute_the_weights(self) -> None:
        weights = portfolio_weights([
            _position(1, "037833100", 100.0),
            _position(2, "594918104", 100.0, kind="CALL"),
        ])
        self.assertEqual({"037833100": 1.0}, weights)

    def test_the_same_cusip_on_two_lines_is_combined(self) -> None:
        """운용 재량별로 나눠 보고하는 매니저가 있다."""
        weights = portfolio_weights([
            _position(1, "037833100", 50.0),
            _position(2, "037833100", 50.0),
        ])
        self.assertEqual({"037833100": 1.0}, weights)

    def test_an_empty_portfolio_does_not_divide_by_zero(self) -> None:
        self.assertEqual({}, portfolio_weights([]))
        self.assertEqual({}, portfolio_weights([_position(1, "037833100", 0.0)]))


if __name__ == "__main__":
    unittest.main()
