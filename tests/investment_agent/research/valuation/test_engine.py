from __future__ import annotations

import unittest
from decimal import Decimal

from investment_agent.trading.contracts import ContractError
from investment_agent.research.valuation.engine import PITScalar, PITValuationInputs, build_pit_valuation


AS_OF = "2024-11-01T21:00:00+00:00"


def _scalar(value: int | float | str | None, *, evidence_id: str, available_at: str = "2024-10-31T21:00:00+00:00", missing_reason: str | None = None) -> PITScalar:
    if value is None:
        return PITScalar(value=None, observed_at=None, available_at=None, missing_reason=missing_reason or "source_missing")
    return PITScalar(
        value=value,
        observed_at="2024-10-31T20:00:00+00:00",
        available_at=available_at,
        evidence_ids=(evidence_id,),
    )


def _inputs(**overrides: PITScalar | str) -> PITValuationInputs:
    values: dict[str, PITScalar | str] = {
        "ticker": "AAPL",
        "as_of_at": AS_OF,
        "source_kind": "historical_replay",
        "source_version": "pit-valuation-v1",
        "price": _scalar("200", evidence_id="EV-PRICE-1"),
        "shares_outstanding": _scalar("100", evidence_id="EV-SHARES-1"),
        "earnings_ttm": _scalar("1000", evidence_id="EV-EARNINGS-1"),
        "book_value": _scalar("4000", evidence_id="EV-BOOK-1"),
        "revenue_ttm": _scalar("5000", evidence_id="EV-REVENUE-1"),
        "free_cash_flow_ttm": _scalar("800", evidence_id="EV-FCF-1"),
    }
    values.update(overrides)
    return PITValuationInputs(**values)  # type: ignore[arg-type]


class PITValuationTest(unittest.TestCase):
    def test_calculates_per_pbr_psr_and_fcf_yield_from_pit_inputs(self) -> None:
        observation = build_pit_valuation(_inputs())

        self.assertEqual(observation.market_cap, Decimal("20000"))
        self.assertEqual(observation.pe_ttm, Decimal("20"))
        self.assertEqual(observation.pb, Decimal("5"))
        self.assertEqual(observation.ps_ttm, Decimal("4"))
        self.assertEqual(observation.fcf_yield, Decimal("0.04"))
        self.assertEqual(observation.available_at, "2024-10-31T21:00:00+00:00")
        self.assertEqual(observation.input_evidence_ids, (
            "EV-BOOK-1", "EV-EARNINGS-1", "EV-FCF-1", "EV-PRICE-1", "EV-REVENUE-1", "EV-SHARES-1",
        ))

    def test_rejects_every_future_input_before_calculation(self) -> None:
        with self.assertRaisesRegex(ContractError, "future valuation input rejected: earnings_ttm"):
            _inputs(earnings_ttm=_scalar(
                "1000", evidence_id="EV-EARNINGS-FUTURE", available_at="2024-11-01T21:00:01+00:00",
            ))

    def test_negative_or_zero_denominators_are_not_silently_zeroed(self) -> None:
        observation = build_pit_valuation(_inputs(
            earnings_ttm=_scalar("-1", evidence_id="EV-EARNINGS-LOSS"),
            book_value=_scalar("0", evidence_id="EV-BOOK-ZERO"),
            revenue_ttm=_scalar("-1", evidence_id="EV-REVENUE-NEGATIVE"),
            free_cash_flow_ttm=_scalar("-1", evidence_id="EV-FCF-NEGATIVE"),
        ))

        self.assertIsNone(observation.pe_ttm)
        self.assertIsNone(observation.pb)
        self.assertIsNone(observation.ps_ttm)
        self.assertIsNone(observation.fcf_yield)
        self.assertFalse(observation.is_meaningful_pe_ttm)
        self.assertEqual(observation.missing_reasons["pe_ttm"], "earnings_ttm_nonpositive")
        self.assertEqual(observation.missing_reasons["fcf_yield"], "free_cash_flow_ttm_nonpositive")

    def test_missing_input_is_preserved_with_its_reason(self) -> None:
        observation = build_pit_valuation(_inputs(
            free_cash_flow_ttm=_scalar(None, evidence_id="EV-UNUSED", missing_reason="ttm_not_complete"),
        ))

        self.assertIsNone(observation.fcf_yield)
        self.assertEqual(observation.missing_reasons["free_cash_flow_ttm"], "ttm_not_complete")
        self.assertEqual(observation.missing_reasons["fcf_yield"], "ttm_not_complete")

    def test_same_inputs_have_a_stable_hash(self) -> None:
        self.assertEqual(_inputs().input_hash, _inputs().input_hash)
        self.assertNotEqual(
            _inputs(price=_scalar("201", evidence_id="EV-PRICE-1")).input_hash,
            _inputs().input_hash,
        )

    def test_known_scalar_requires_evidence_and_chronological_timing(self) -> None:
        with self.assertRaisesRegex(ContractError, "requires evidence_ids"):
            PITScalar(
                value=1, observed_at="2024-10-31T20:00:00+00:00",
                available_at="2024-10-31T21:00:00+00:00",
            )
        with self.assertRaisesRegex(ContractError, "cannot precede observed_at"):
            PITScalar(
                value=1, observed_at="2024-10-31T21:00:00+00:00",
                available_at="2024-10-31T20:00:00+00:00", evidence_ids=("EV-1",),
            )


if __name__ == "__main__":
    unittest.main()
