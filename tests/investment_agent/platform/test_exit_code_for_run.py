"""종목 몇 개의 일시 오류가 그날 feature_store 잡 전체를 세우지 않는다(RS-12).

하네스는 종료 코드가 0이 아니면 단계를 실패로 보고 10분 뒤 전체를 다시 돌리며, 두 번째도 실패하면 뒤 단계
(label·표본·평가)를 그날 건너뛴다.
"""
from __future__ import annotations

import unittest

from investment_agent.platform.cli.runtime import EXIT_FAILED, EXIT_OK, MAX_TOLERATED_FAILURE_RATIO, exit_code_for_run


class ExitCodeForRunTest(unittest.TestCase):
    def test_success_is_zero(self) -> None:
        self.assertEqual(EXIT_OK, exit_code_for_run("success", failed=0, total=503, saved=503))

    def test_a_few_failed_tickers_do_not_fail_the_run(self) -> None:
        self.assertEqual(EXIT_OK, exit_code_for_run("partial", failed=1, total=503, saved=502))

    def test_the_tolerance_boundary_is_inclusive(self) -> None:
        total = 200
        boundary = int(total * MAX_TOLERATED_FAILURE_RATIO)
        self.assertEqual(EXIT_OK, exit_code_for_run("partial", failed=boundary, total=total, saved=total - boundary))
        self.assertEqual(EXIT_FAILED, exit_code_for_run("partial", failed=boundary + 1, total=total, saved=total - boundary - 1))

    def test_a_partial_run_that_saved_nothing_is_a_failure(self) -> None:
        self.assertEqual(EXIT_FAILED, exit_code_for_run("partial", failed=1, total=503, saved=0))

    def test_failed_and_unknown_statuses_are_failures(self) -> None:
        self.assertEqual(EXIT_FAILED, exit_code_for_run("failed", failed=0, total=503, saved=0))
        self.assertEqual(EXIT_FAILED, exit_code_for_run("weird", failed=0, total=503, saved=503))

    def test_an_empty_universe_is_never_tolerated(self) -> None:
        self.assertEqual(EXIT_FAILED, exit_code_for_run("partial", failed=0, total=0, saved=1))


if __name__ == "__main__":
    unittest.main()
