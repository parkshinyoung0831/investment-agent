"""예상치·일정·커버리지를 바뀔 때만 버전으로 남기는 규칙과, 그 버전을 읽는 비교 뷰의 계약."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from investment_agent.data.fundamentals.domain.services.state_versions import plan_versions

ROOT = Path(__file__).resolve().parents[4]
REPORTING = (ROOT / "db" / "postgres" / "v1" / "90_reporting.sql").read_text(encoding="utf-8")
KEY = ("security_id", "target_fiscal_year", "target_fiscal_period", "source", "snapshot_kind")
VALUES = ("eps_avg", "revenue_avg")
NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)


def _row(day: str, eps: float, **extra) -> dict:
    return {"security_id": 1000001, "target_fiscal_year": 2026, "target_fiscal_period": "Q3",
            "source": "yfinance", "snapshot_kind": "captured_live", "snapshot_date": day,
            "eps_avg": eps, "revenue_avg": 100.0, **extra}


def _stored(day: str, eps: float) -> dict:
    return _row(day, eps, collected_at=f"{day}T21:00:00+00:00", last_seen_at=f"{day}T21:00:00+00:00")


class PlanVersionsTest(unittest.TestCase):
    def plan(self, candidates, stored=()):
        return plan_versions(candidates, stored, key_fields=KEY, value_fields=VALUES, now=NOW)

    def test_same_state_only_moves_last_seen(self) -> None:
        plan = self.plan([_row("2026-09-14", 1.5)], [_stored("2026-09-10", 1.5)])
        self.assertEqual([], plan.new_rows)
        self.assertEqual(["2026-09-10"], [row["snapshot_date"] for row in plan.confirmations])
        self.assertEqual(NOW.isoformat(), plan.confirmations[0]["last_seen_at"])

    def test_a_changed_state_is_a_new_version(self) -> None:
        plan = self.plan([_row("2026-09-14", 1.6)], [_stored("2026-09-10", 1.5)])
        self.assertEqual(["2026-09-14"], [row["snapshot_date"] for row in plan.new_rows])
        self.assertEqual([], plan.confirmations)

    def test_a_value_that_returns_is_kept_as_a_third_version(self) -> None:
        """A→B→A. 전체 DISTINCT로 줄이면 되돌아온 사건이 사라진다."""
        stored = [_stored("2026-09-01", 1.5), _stored("2026-09-05", 1.6)]
        plan = self.plan([_row("2026-09-14", 1.5)], stored)
        self.assertEqual(["2026-09-14"], [row["snapshot_date"] for row in plan.new_rows])

    def test_numeric_text_from_the_api_is_the_same_state(self) -> None:
        stored = [{**_stored("2026-09-10", 1.5), "eps_avg": "1.50"}]
        self.assertEqual([], self.plan([_row("2026-09-14", 1.5)], stored).new_rows)

    def test_late_historical_rows_are_not_compressed_against_newer_state(self) -> None:
        plan = self.plan([_row("2026-08-01", 1.5)], [_stored("2026-09-10", 1.5)])
        self.assertEqual(["2026-08-01"], [row["snapshot_date"] for row in plan.new_rows])

    def test_other_keys_are_independent(self) -> None:
        other = {**_row("2026-09-14", 1.5), "snapshot_kind": "reconstructed"}
        plan = self.plan([other], [_stored("2026-09-10", 1.5)])
        self.assertEqual(1, len(plan.new_rows))

    def test_a_batch_compares_each_candidate_with_the_one_before(self) -> None:
        plan = self.plan([_row("2026-09-12", 1.6), _row("2026-09-13", 1.6), _row("2026-09-14", 1.5)])
        self.assertEqual(["2026-09-12", "2026-09-14"], [row["snapshot_date"] for row in plan.new_rows])


class SurpriseViewContractTest(unittest.TestCase):
    """비교 뷰가 발표 뒤에 만든 값이나 다른 단위를 서프라이즈에 쓰지 않는다."""

    def _view(self, name: str) -> str:
        start = REPORTING.index(f"CREATE OR REPLACE VIEW reporting.{name} ")
        return REPORTING[start:REPORTING.index("COMMENT ON VIEW", start)]

    def test_earnings_surprise_uses_only_pre_release_live_or_vendor_pit_estimates(self) -> None:
        body = self._view("earnings_surprise")
        self.assertIn("est.snapshot_kind IN ('captured_live', 'vendor_pit')", body)
        self.assertIn("est.snapshot_date < f.filing_date", body)
        self.assertIn("est.collected_at < f.available_at", body)
        self.assertIn("eps_basis_match", body)

    def test_macro_surprise_compares_first_release_in_measure_units(self) -> None:
        body = REPORTING[REPORTING.index("CREATE OR REPLACE VIEW reporting.macro_release_summary"):]
        body = body[:body.index("COMMENT ON VIEW")]
        self.assertIn("macro.measure_value(b.measure_id, b.ref_period, b.first_vintage_at)", body)
        self.assertIn("fv.effective_at <= v.first_vintage_at", body)
        self.assertIn("x.first_value - x.closing_survey_value AS market_surprise", body)
        self.assertNotIn("latest_actual.value - closing_survey.value", body)

    def test_no_snapshot_pruning_function_is_declared(self) -> None:
        """발표 전 예상 이력은 다시 받을 수 없다. 버전 저장이라 지울 반복도 없다."""
        for name in ("30_fundamentals.sql", "40_macro.sql"):
            sql = (ROOT / "db" / "postgres" / "v1" / name).read_text(encoding="utf-8")
            with self.subTest(file=name):
                self.assertNotIn("prune_", sql)


if __name__ == "__main__":
    unittest.main()
