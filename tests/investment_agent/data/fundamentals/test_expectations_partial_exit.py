"""부분 성공을 실패로 올리면 알림이 매일 울리고 진짜 고장을 못 가린다.

실측 2026-09-04: Yahoo 레이트리밋으로 503종목 중 359건이 실패했지만 2,312행은
정상 적재됐다. 그런데 `return 1 if failures else 0`이라 잡이 실패로 끝났고,
Discord #시스템-로그가 이 알림으로 뒤덮였다.
"""
from __future__ import annotations

import unittest

from investment_agent.data.fundamentals.commands.refresh_expectations import expectations_exit_code


class ExpectationsExitCodeTest(unittest.TestCase):
    def test_a_clean_run_succeeds(self):
        self.assertEqual(expectations_exit_code(rows=2312, tickers=503, failures=0), 0)

    def test_partial_failure_within_the_threshold_still_succeeds(self):
        """레이트리밋은 상시 조건이다 — 대부분 적재됐으면 성공이다."""
        self.assertEqual(expectations_exit_code(rows=2312, tickers=503, failures=359), 0)

    def test_a_collapsed_run_fails(self):
        self.assertEqual(expectations_exit_code(rows=0, tickers=503, failures=503), 1)

    def test_writing_nothing_fails_even_without_recorded_failures(self):
        """행이 하나도 안 들어갔는데 성공이라고 하면 조용히 비어 간다."""
        self.assertEqual(expectations_exit_code(rows=0, tickers=503, failures=0), 1)

    def test_a_run_that_wrote_less_than_one_row_per_ticker_fails(self):
        """행이 거의 안 들어갔으면 실패 수와 무관하게 붕괴한 실행이다."""
        self.assertEqual(expectations_exit_code(rows=10, tickers=100, failures=0), 1)

    def test_failure_count_alone_does_not_decide(self):
        """실패는 (종목 × 단계) 단위라 종목 수와 단위가 다르다 — 게이트는 적재량이 정한다."""
        self.assertEqual(expectations_exit_code(rows=900, tickers=100, failures=400), 0)

    def test_no_ticker_requested_is_not_a_failure(self):
        self.assertEqual(expectations_exit_code(rows=0, tickers=0, failures=0), 0)


if __name__ == "__main__":
    unittest.main()
