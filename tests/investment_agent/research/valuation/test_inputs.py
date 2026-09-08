"""PIT 밸류에이션 입력 조립과 적재 진입점의 시점 계약을 고정한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from investment_agent.research.commands.build_valuations import build_valuations
from investment_agent.research.valuation.engine import build_pit_valuation
from investment_agent.research.valuation.inputs import (
    build_valuation_inputs,
    filing_available_at,
    select_ttm_quarters,
    shares_scalar,
    ttm_scalars,
)

_AS_OF = datetime(2026, 8, 20, 22, tzinfo=timezone.utc)


def _quarter(year, period, *, period_end, filed_at, revenue=100.0, net_income=10.0,
             equity=500.0, ocf=20.0, capex=5.0, accession="0000000001-26-000001"):
    return {
        "ticker": "AAA", "fiscal_year": year, "fiscal_period": period,
        "period_end": period_end, "filed_at": filed_at, "accession_no": accession,
        "revenue": revenue, "net_income": net_income, "common_equity": equity,
        "net_cash_from_operating_activities": ocf, "capital_expenses": capex,
    }


def _four_quarters(**overrides):
    base = [
        _quarter(2026, "Q2", period_end="2026-06-30", filed_at="2026-07-25", accession="0000000001-26-000004"),
        _quarter(2026, "Q1", period_end="2026-03-31", filed_at="2026-04-25", accession="0000000001-26-000003"),
        _quarter(2025, "Q4", period_end="2025-12-31", filed_at="2026-01-25", accession="0000000001-26-000002"),
        _quarter(2025, "Q3", period_end="2025-09-30", filed_at="2025-10-25", accession="0000000001-25-000001"),
    ]
    for row in base:
        row.update(overrides)
    return base


class FilingAvailabilityTest(unittest.TestCase):
    def test_date_only_filing_is_treated_as_next_day(self):
        """일자만 아는 공시를 그날 0시로 잡으면 실제보다 이르게 안다고 주장하게 된다."""
        self.assertEqual(
            filing_available_at("2026-07-25"),
            datetime(2026, 7, 26, tzinfo=timezone.utc),
        )

    def test_same_day_filing_is_not_usable_yet(self):
        rows = _four_quarters()
        rows[0]["filed_at"] = _AS_OF.date().isoformat()
        self.assertEqual(len(select_ttm_quarters(rows, as_of_at=_AS_OF)), 3)


class TTMReconstructionTest(unittest.TestCase):
    def test_ttm_sums_four_quarters_and_keeps_equity_as_a_balance(self):
        values = ttm_scalars(_four_quarters(), as_of_at=_AS_OF)
        self.assertEqual(values["revenue_ttm"].value, Decimal("400"))
        self.assertEqual(values["earnings_ttm"].value, Decimal("40"))
        # FCF = 영업현금흐름 - capex, 4분기 합
        self.assertEqual(values["free_cash_flow_ttm"].value, Decimal("60"))
        # 자기자본은 잔액이라 합산하지 않고 최근 분기 값을 쓴다
        self.assertEqual(values["book_value"].value, Decimal("500"))

    def test_available_at_is_the_latest_quarter_filing(self):
        values = ttm_scalars(_four_quarters(), as_of_at=_AS_OF)
        self.assertEqual(values["revenue_ttm"].available_at, "2026-07-26T00:00:00+00:00")

    def test_every_quarter_contributes_an_evidence_id(self):
        values = ttm_scalars(_four_quarters(), as_of_at=_AS_OF)
        self.assertEqual(len(values["revenue_ttm"].evidence_ids), 4)

    def test_three_quarters_is_missing_not_annualized(self):
        values = ttm_scalars(_four_quarters()[:3], as_of_at=_AS_OF)
        for name in ("revenue_ttm", "earnings_ttm", "free_cash_flow_ttm", "book_value"):
            self.assertIsNone(values[name].value, name)
            self.assertIn("ttm_incomplete", values[name].missing_reason)

    def test_one_missing_field_makes_only_that_metric_missing(self):
        rows = _four_quarters()
        rows[1]["revenue"] = None
        values = ttm_scalars(rows, as_of_at=_AS_OF)
        self.assertIsNone(values["revenue_ttm"].value)
        self.assertEqual(values["revenue_ttm"].missing_reason, "revenue_missing_in_ttm_window")
        self.assertIsNotNone(values["earnings_ttm"].value)

    def test_restatement_uses_the_first_published_row(self):
        """나중 정정본을 쓰면 그 시점에 알 수 없던 값이 섞인다."""
        rows = _four_quarters()
        restated = dict(rows[0])
        restated["filed_at"] = "2026-08-10"
        restated["revenue"] = 999.0
        selected = select_ttm_quarters([restated, *rows], as_of_at=_AS_OF)
        newest = [row for row in selected if row["period_end"] == "2026-06-30"]
        self.assertEqual(len(newest), 1)
        self.assertEqual(newest[0]["revenue"], 100.0)


class SharesOutstandingTest(unittest.TestCase):
    def test_accepted_at_is_preferred_over_the_filing_date(self):
        scalar = shares_scalar([{
            "shares_outstanding": 1000, "accession_no": "0000000001-26-000004",
            "share_class_key": "common", "filed_at": "2026-07-25",
            "accepted_at": "2026-07-25T18:03:00+00:00",
        }], as_of_at=_AS_OF)
        self.assertEqual(scalar.value, Decimal("1000"))
        self.assertEqual(scalar.available_at, "2026-07-25T18:03:00+00:00")

    def test_future_snapshot_is_rejected(self):
        scalar = shares_scalar([{
            "shares_outstanding": 1000, "accession_no": "0000000001-26-000009",
            "share_class_key": "common", "filed_at": "2026-09-01",
            "accepted_at": "2026-09-01T18:03:00+00:00",
        }], as_of_at=_AS_OF)
        self.assertIsNone(scalar.value)
        self.assertEqual(scalar.missing_reason, "no_shares_outstanding_available_at_cutoff")

    def test_missing_coverage_is_reported_not_zero_filled(self):
        scalar = shares_scalar([], as_of_at=_AS_OF)
        self.assertIsNone(scalar.value)
        self.assertIsNotNone(scalar.missing_reason)


class ValuationInputsTest(unittest.TestCase):
    def _inputs(self, **overrides):
        payload = {
            "ticker": "AAA", "as_of_at": _AS_OF, "source_version": "test-v1",
            "price_rows": [{"ticker": "AAA", "trade_date": "2026-08-20", "close": 50.0,
                            "ingested_at": "2026-08-20T21:30:00+00:00"}],
            "fundamental_rows": _four_quarters(),
            "share_rows": [{"shares_outstanding": 1000, "accession_no": "0000000001-26-000004",
                            "share_class_key": "common", "filed_at": "2026-07-25",
                            "accepted_at": "2026-07-25T18:03:00+00:00"}],
        }
        payload.update(overrides)
        return build_valuation_inputs(**payload)

    def test_ratios_match_a_hand_calculation(self):
        observation = build_pit_valuation(self._inputs())
        # 시가총액 = 50 x 1000 = 50,000
        self.assertEqual(observation.market_cap, Decimal("50000"))
        self.assertEqual(observation.pe_ttm, Decimal("1250"))     # 50000 / 40
        self.assertEqual(observation.pb, Decimal("100"))          # 50000 / 500
        self.assertEqual(observation.ps_ttm, Decimal("125"))      # 50000 / 400
        self.assertEqual(observation.fcf_yield, Decimal("0.0012"))  # 60 / 50000

    def test_price_ingested_after_the_cutoff_is_refused(self):
        observation = build_pit_valuation(self._inputs(price_rows=[{
            "ticker": "AAA", "trade_date": "2026-08-20", "close": 50.0,
            "ingested_at": "2026-08-21T02:00:00+00:00",
        }]))
        self.assertIsNone(observation.price)
        self.assertIsNone(observation.market_cap)
        self.assertEqual(observation.missing_reasons["price"], "no_price_available_at_cutoff")

    def test_negative_earnings_leave_pe_not_meaningful(self):
        rows = _four_quarters()
        for row in rows:
            row["net_income"] = -5.0
        observation = build_pit_valuation(self._inputs(fundamental_rows=rows))
        self.assertIsNone(observation.pe_ttm)
        self.assertFalse(observation.is_meaningful_pe_ttm)
        self.assertEqual(observation.missing_reasons["pe_ttm"], "earnings_ttm_nonpositive")
        # 적자라고 다른 비율까지 버리지 않는다.
        self.assertIsNotNone(observation.pb)

    def test_same_inputs_produce_the_same_hash(self):
        self.assertEqual(
            build_pit_valuation(self._inputs()).input_hash,
            build_pit_valuation(self._inputs()).input_hash,
        )


class _Repository:
    def __init__(self, *, price_rows=None, fundamental_rows=None, share_rows=None):
        self.price_rows = price_rows if price_rows is not None else [
            {"ticker": "AAA", "trade_date": "2026-08-20", "close": 50.0,
             "ingested_at": "2026-08-20T21:30:00+00:00"}]
        self.fundamental_rows = _four_quarters() if fundamental_rows is None else fundamental_rows
        self.share_rows = share_rows if share_rows is not None else [
            {"shares_outstanding": 1000, "accession_no": "0000000001-26-000004",
             "share_class_key": "common", "filed_at": "2026-07-25",
             "accepted_at": "2026-07-25T18:03:00+00:00"}]
        self.saved: list[dict] = []

    def current_tracked_tickers(self):
        return ["AAA"]

    def market_prices(self, ticker, as_of_at, limit=260):
        return list(self.price_rows)

    def fundamentals_pit(self, ticker, as_of_at, limit=12):
        return list(self.fundamental_rows)

    def share_class_snapshots_pit(self, ticker, as_of_at, limit=24):
        return list(self.share_rows)

    def save_valuation_observations(self, rows):
        self.saved.extend(rows)


class BuildValuationsEntryTest(unittest.TestCase):
    def test_observation_is_stored_with_evidence_and_hash(self):
        repository = _Repository()
        payload = build_valuations(as_of_at=_AS_OF, tickers=["AAA"], repository=repository)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(len(repository.saved), 1)
        row = repository.saved[0]
        self.assertEqual(row["source_kind"], "live_shadow")
        self.assertEqual(row["market_cap"], 50000.0)
        self.assertTrue(row["input_evidence_ids"])
        self.assertEqual(len(row["input_hash"]), 64)

    def test_incomplete_source_is_still_stored_with_reasons(self):
        """근거가 모자란 날도 기록한다 — 왜 못 만들었는지가 나중에 필요하다."""
        repository = _Repository(share_rows=[])
        build_valuations(as_of_at=_AS_OF, tickers=["AAA"], repository=repository)
        row = repository.saved[0]
        self.assertIsNone(row["market_cap"])
        self.assertFalse(row["is_meaningful_pe_ttm"])
        self.assertIn("shares_outstanding", row["missing_reasons"])

    def test_meaningful_flags_always_agree_with_the_stored_value(self):
        """DB CHECK 제약과 같은 불변식을 코드 쪽에서도 지킨다."""
        for repository in (_Repository(), _Repository(share_rows=[]), _Repository(fundamental_rows=[])):
            build_valuations(as_of_at=_AS_OF, tickers=["AAA"], repository=repository)
            row = repository.saved[0]
            for metric in ("pe_ttm", "pb", "ps_ttm", "fcf_yield"):
                self.assertEqual(
                    row[metric] is not None, row[f"is_meaningful_{metric}"], metric,
                )

    def test_dry_run_writes_nothing(self):
        repository = _Repository()
        payload = build_valuations(
            as_of_at=_AS_OF, tickers=["AAA"], dry_run=True, repository=repository,
        )
        self.assertEqual(repository.saved, [])
        self.assertEqual(payload["rows_upserted"], 0)


if __name__ == "__main__":
    unittest.main()
