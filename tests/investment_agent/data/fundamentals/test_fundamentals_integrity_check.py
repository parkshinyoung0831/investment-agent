"""정합성 점검의 등급 판정.

수집 잡은 "이번 실행이 성공했나"만 본다. 조용히 썩는 실패 — 스키마 드리프트,
매핑이 깨져 떨어진 충전율, 멈춘 mv_company_ttm — 는 초록 불 아래에서 몇 주를 간다.
"""
from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from investment_agent.data.fundamentals.application.verify_integrity import (
    BALANCE_MISMATCH_ERROR,
    ERROR,
    OK,
    WARNING,
    evaluate,
    verify_integrity,
)

TODAY = date(2026, 8, 27)
HEALTHY = {
    "columns_missing_in_db": [],
    "columns_missing_in_code": [],
    "last_filed_at": date(2026, 8, 25),
    "latest_financial_period_end": date(2026, 8, 2),
    "row_count": 18998,
    "current_mapping_version": "test-current",
    "stale_mapping_rows": 0,
    "missing_financial_tickers": [],
    "balance_checkable_rows": 13218,
    "balance_mismatch_rows": 319,
    "fiscal_sequence": {
        "non_monotonic_rows": 0,
        "duplicate_period_end_rows": 0,
    },
    "fill_rates": {
        "revenue": 94.4,
        "liabilities": 99.79,
        "eps_diluted_gaap": 90.8,
    },
    "fill_floors": {
        "revenue": 85.0,
        "liabilities": 95.0,
        "eps_diluted_gaap": 70.0,
    },
    "derived_liability_rows": 5740,
    "unknown_equity_scope_rows": 0,
    "segment_integrity": {
        "metric_rows": 105554,
        "metric_tickers": 498,
        "filing_rows": 15171,
        "stale_mapping_filing_rows": 0,
        "tracked_without_filing_rows": 0,
        "valueless_metric_rows": 0,
        "unknown_classification_rows": 0,
        "orphan_metric_rows": 0,
        "nonparsed_metric_state_rows": 0,
        "report_period_mismatch_rows": 0,
        "future_metric_rows": 0,
        "invalid_period_kind_rows": 0,
        "invalid_derived_rows": 0,
        "invalid_coverage_rows": 0,
        "invalid_metric_metadata_rows": 0,
        "invalid_filing_date_rows": 0,
    },
    "schedule_rows": 50,
    "schedule_unknown_session": 1,
}


def _run(**overrides) -> dict[str, dict]:
    facts = {**HEALTHY, **overrides}
    checks = evaluate(facts, TODAY, stale_filing_days=14, stale_mv_days=100)
    return {check["name"]: check for check in checks}


class HealthyBaseline(unittest.TestCase):
    def test_current_production_state_is_all_clear(self):
        """2026-08-27 실측값이 전부 통과해야 한다. 안 그러면 매번 빨간불이라 아무도 안 본다."""
        for name, check in _run().items():
            self.assertEqual(check["severity"], OK, f"{name}: {check['message']}")


class SchemaDrift(unittest.TestCase):
    def test_column_missing_in_db_is_an_error(self):
        """코드가 쓰는 컬럼이 DB에 없으면 적재가 통째로 PGRST204로 실패한다."""
        check = _run(columns_missing_in_db=["goodwill"])["schema_drift"]
        self.assertEqual(check["severity"], ERROR)
        self.assertEqual(check["detail"]["missing"], ["goodwill"])

    def test_orphan_column_in_db_is_only_a_warning(self):
        """아무도 채우지 않는 컬럼은 낭비지 장애가 아니다."""
        self.assertEqual(
            _run(columns_missing_in_code=["legacy_col"])["schema_drift"]["severity"],
            WARNING,
        )


class MappingRegression(unittest.TestCase):
    def test_stale_policy_rows_are_an_error(self):
        check = _run(stale_mapping_rows=12)["mapping_policy_current"]
        self.assertEqual(check["severity"], ERROR)
        self.assertEqual(check["detail"]["stale_rows"], 12)

    def test_unknown_equity_scope_is_an_error(self):
        check = _run(unknown_equity_scope_rows=1)["equity_scope"]
        self.assertEqual(check["severity"], ERROR)

    def test_non_monotonic_fiscal_sequence_is_an_error(self):
        check = _run(fiscal_sequence={
            "non_monotonic_rows": 1,
            "duplicate_period_end_rows": 0,
        })["fiscal_sequence"]
        self.assertEqual(check["severity"], ERROR)

    def test_fill_rate_below_floor_warns(self):
        check = _run(fill_rates={"revenue": 94.4, "eps_diluted_gaap": 60.0})["fill_eps_diluted_gaap"]
        self.assertEqual(check["severity"], WARNING)

    def test_fill_rate_collapse_is_an_error(self):
        """실제로 EPS가 5%까지 떨어진 채 몇 달을 갔다. 절반 밑은 매핑이 깨진 것이다."""
        check = _run(fill_rates={"revenue": 94.4, "eps_diluted_gaap": 5.1})["fill_eps_diluted_gaap"]
        self.assertEqual(check["severity"], ERROR)


class TerminalProvenance(unittest.TestCase):
    def test_integrity_does_not_model_runtime_failure_as_a_db_state(self):
        self.assertNotIn("filing_state", _run())


class SegmentIntegrity(unittest.TestCase):
    def _with_segment_error(self, key: str, value: int = 1) -> dict:
        segment = {**HEALTHY["segment_integrity"], key: value}
        return _run(segment_integrity=segment)

    def test_missing_stats_is_an_error(self):
        self.assertEqual(
            _run(segment_integrity=None)["segment_integrity_available"]["severity"],
            ERROR,
        )

    def test_stale_segment_mapping_provenance_is_an_error(self):
        check = self._with_segment_error("stale_mapping_filing_rows")["segment_filing_state"]
        self.assertEqual(check["severity"], ERROR)

    def test_tracked_ticker_without_state_is_an_error(self):
        check = self._with_segment_error("tracked_without_filing_rows")[
            "segment_tracked_coverage"
        ]
        self.assertEqual(check["severity"], ERROR)

    def test_terminal_segment_states_without_metric_rows_are_covered(self):
        """빈 세그먼트도 terminal processing state가 있으면 수집 누락이 아니다."""
        segment = {
            **HEALTHY["segment_integrity"],
            "tracked_without_filing_rows": 0,
            "tracked_without_segment_state_tickers": [],
        }
        check = _run(segment_integrity=segment)["segment_tracked_coverage"]
        self.assertEqual(check["severity"], OK)
        self.assertEqual(check["detail"]["missing"], [])

    def test_orphan_segment_metric_is_an_error(self):
        check = self._with_segment_error("orphan_metric_rows")[
            "segment_data_contract"
        ]
        self.assertEqual(check["severity"], ERROR)
        self.assertEqual(check["detail"]["orphan_metric_rows"], 1)


class TrackedCoverage(unittest.TestCase):
    def test_missing_tracked_ticker_is_an_error(self):
        check = _run(missing_financial_tickers=["MISSING"])["tracked_coverage"]
        self.assertEqual(check["severity"], ERROR)
        self.assertEqual(check["detail"]["missing"], ["MISSING"])


class StalenessChecks(unittest.TestCase):
    def test_stalled_collection_warns(self):
        self.assertEqual(
            _run(last_filed_at=date(2026, 8, 1))["collection_stalled"]["severity"], WARNING)

    def test_empty_table_is_an_error(self):
        self.assertEqual(_run(last_filed_at=None)["collection_stalled"]["severity"], ERROR)

    def test_frozen_financial_versions_is_an_error(self):
        """원장 최신 기간이 멈추면 화면 파생값만으로는 알 수 없다."""
        self.assertEqual(
            _run(latest_financial_period_end=date(2026, 1, 31))["financial_versions_stale"]["severity"], ERROR)


class BalanceIdentityBaseline(unittest.TestCase):
    def test_structural_residue_is_not_flagged(self):
        """모회사 자본만 태깅하는 회사(ARES·BX)는 저장값으로 복원할 수 없다.

        0을 기대하면 매번 빨간불이 된다. mezzanine_equity를 넣고 우선주
        자본 scope를 반영한 뒤 실측 2.4%(319/13,218)가 정상 하한이다.
        """
        self.assertEqual(_run()["balance_identity"]["severity"], OK)

    def test_sudden_jump_is_an_error(self):
        broken = int(HEALTHY["balance_checkable_rows"] * (BALANCE_MISMATCH_ERROR + 0.05))
        self.assertEqual(
            _run(balance_mismatch_rows=broken)["balance_identity"]["severity"], ERROR)


class BalanceMeasurementSource(unittest.TestCase):
    def test_ratio_uses_checkable_rows_not_every_row(self):
        """부채나 자본이 없는 행은 검사 대상이 아니다.

        전체 행으로 나누면 비율이 실제보다 작게 나와 악화를 놓친다 —
        실측 검사가능 13,352행 vs 전체 18,998행으로 1.4배 차이가 난다.
        """
        check = _run(balance_checkable_rows=1000, balance_mismatch_rows=130)["balance_identity"]
        self.assertEqual(check["detail"]["total"], 1000)
        self.assertEqual(check["severity"], ERROR)  # 13% > 12% 임계치


class SessionCoverage(unittest.TestCase):
    def test_mostly_unclassified_sessions_warn(self):
        """세션이 안 붙으면 핀포인트 수집이 넓은 창으로 되돌아간다."""
        check = _run(schedule_rows=50, schedule_unknown_session=30)["session_classification"]
        self.assertEqual(check["severity"], WARNING)


class VerificationBoundary(unittest.TestCase):
    def test_verification_returns_checks_without_writing_an_issue_ledger(self):
        repository = mock.MagicMock()
        repository.collect_integrity_facts.return_value = {
            **HEALTHY, "columns_missing_in_db": ["goodwill"],
        }

        verify_integrity(
            repository=repository, today=TODAY,
            stale_filing_days=14, stale_mv_days=100,
        )

        self.assertEqual(repository.method_calls, [
            mock.call.collect_integrity_facts(),
        ])


if __name__ == "__main__":
    unittest.main()
