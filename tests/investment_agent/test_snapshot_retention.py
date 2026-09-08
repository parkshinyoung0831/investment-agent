"""스냅샷 정리 함수가 "계속 읽히는 한 건"을 실제로 지키는지 선언에서 확인한다.

## 왜 텍스트로 보는가

이 정리는 DELETE라서 틀리면 되돌릴 수 없다. 그런데 라이브 DB에 붙이는 검증은
별도 실행 단계라 CI에서 돌지 않는다. 그래서 되돌릴 수 없는 쪽의 전제 — 어떤 행을
남기기로 선언했는가 — 만이라도 매번 본다.

지키려는 계약은 둘이다.

* `reporting.earnings_surprise`는 `snapshot_date < filing_date` 중 마지막 한 건을
  집는다. 그 행이 사라지면 카드의 서프라이즈 숫자가 통째로 빈다.
* `reporting.macro_release_summary`는 실제치 직전(`collected_at <= first_actual`)
  예상을 집는다. 그 행이 사라지면 "예상 대비"를 계산할 기준이 없어진다.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FUNDAMENTALS = (ROOT / "db" / "postgres" / "v1" / "30_fundamentals.sql").read_text(encoding="utf-8")
MACRO = (ROOT / "db" / "postgres" / "v1" / "40_macro.sql").read_text(encoding="utf-8")
REPORTING = (ROOT / "db" / "postgres" / "v1" / "90_reporting.sql").read_text(encoding="utf-8")


def _function_body(sql: str, name: str) -> str:
    start = sql.index(f"CREATE OR REPLACE FUNCTION {name}")
    return sql[start:sql.index("$fn$;", start)]


class ExpectationRetentionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.body = _function_body(FUNDAMENTALS, "fundamentals.prune_expectation_snapshots")

    def test_only_reported_periods_are_pruned(self) -> None:
        """나이로만 자르면 아직 발표 안 한 분기의 드리프트가 먼저 사라진다."""
        self.assertIn("FROM fundamentals.earnings_results r", self.body)
        for statement in re.findall(r"DELETE FROM fundamentals\.\w+ \w+\n(?:.*\n)*?    RETURNING 1", self.body):
            if "analyst_consensus_snapshots" in statement:
                continue  # 커버리지는 기간 축이 없다.
            self.assertIn("reported_period", statement, statement)

    def test_the_pre_announcement_snapshot_is_the_keeper(self) -> None:
        """서프라이즈가 집는 바로 그 행이 keeper여야 한다."""
        self.assertIn("WHERE e.snapshot_date < rp.filing_date", self.body)
        self.assertIn("e.snapshot_date DESC", self.body)
        # 뷰도 같은 경계를 쓴다 — 한쪽만 바뀌면 남긴 행을 아무도 읽지 않게 된다.
        self.assertIn("AND est.snapshot_date < f.filing_date", REPORTING)

    def test_keeper_is_per_source_and_kind(self) -> None:
        """원천이 둘이면 한쪽이 다른 쪽을 밀어낸다."""
        self.assertIn(
            "DISTINCT ON (e.security_id, e.target_fiscal_year, e.target_fiscal_period,\n"
            "                      e.source, e.snapshot_kind)",
            self.body,
        )

    def test_recent_window_is_never_pruned(self) -> None:
        """최근 구간을 통째로 들고 있어야 그 시점 판단을 재현할 수 있다."""
        self.assertIn("p_recent_days", self.body)
        self.assertEqual(3, self.body.count("< cutoff"))

    def test_a_zero_or_negative_window_is_refused(self) -> None:
        """0이면 오늘 것까지 지운다 — 기본값 실수를 조용히 통과시키지 않는다."""
        self.assertIn("p_recent_days IS NULL OR p_recent_days < 1", self.body)

    def test_only_service_role_may_delete(self) -> None:
        self.assertIn(
            "REVOKE ALL ON FUNCTION fundamentals.prune_expectation_snapshots(int) "
            "FROM PUBLIC, anon, authenticated;",
            FUNDAMENTALS,
        )
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION fundamentals.prune_expectation_snapshots(int) TO service_role;",
            FUNDAMENTALS,
        )


class ReleaseRetentionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.body = _function_body(MACRO, "macro.prune_release_snapshots")

    def test_only_released_periods_are_pruned(self) -> None:
        """실제치가 아직 없는 발표는 일정 변경 자체가 신호다."""
        self.assertIn("FROM macro.economic_observations o", self.body)
        for statement in re.findall(r"DELETE FROM macro\.\w+ \w+\n(?:.*\n)*?    RETURNING 1", self.body):
            self.assertIn("released_period", statement, statement)

    def test_the_closing_forecast_is_the_keeper(self) -> None:
        """실제치 직전 예상이 사라지면 '예상 대비'를 계산할 기준이 없다."""
        self.assertIn("WHERE f.collected_at <= rp.first_actual_at", self.body)
        self.assertIn("min(o.available_at) AS first_actual_at", self.body)
        # 뷰도 같은 경계를 쓴다.
        self.assertIn("fv.collected_at <= first_actual.collected_at", REPORTING)

    def test_measure_id_is_compared_null_safely(self) -> None:
        """measure_id는 NULL을 허용한다. `=`로 비교하면 그 행이 전부 삭제된다."""
        self.assertIn("k.measure_id IS NOT DISTINCT FROM f.measure_id", self.body)

    def test_recent_window_is_never_pruned(self) -> None:
        self.assertIn("p_recent_days", self.body)
        self.assertEqual(2, self.body.count("< cutoff"))

    def test_a_zero_or_negative_window_is_refused(self) -> None:
        self.assertIn("p_recent_days IS NULL OR p_recent_days < 1", self.body)

    def test_only_service_role_may_delete(self) -> None:
        self.assertIn(
            "REVOKE ALL ON FUNCTION macro.prune_release_snapshots(int) "
            "FROM PUBLIC, anon, authenticated;",
            MACRO,
        )
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION macro.prune_release_snapshots(int) TO service_role;",
            MACRO,
        )


if __name__ == "__main__":
    unittest.main()
