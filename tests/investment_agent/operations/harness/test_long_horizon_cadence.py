"""중장기 보유 전략의 실행 주기: 분석·System 목표 갱신이 분 단위 매매 주기로 되돌아가지 않는다."""
from __future__ import annotations

import inspect
import unittest

from investment_agent.operations.commands import investment_harness
from investment_agent.operations.harness.pipeline import system_portfolio_job


class LongHorizonCadenceTest(unittest.TestCase):
    def test_system_portfolio_wakes_at_most_hourly_by_default(self):
        job = system_portfolio_job(run_system_portfolio=lambda context: None)
        self.assertGreaterEqual(job.interval_seconds, 60 * 60)

    def test_analysis_wakes_at_most_every_three_hours_by_default(self):
        default = inspect.signature(investment_harness.build_registry).parameters["analysis_interval_seconds"].default
        self.assertGreaterEqual(default, 3 * 60 * 60)
        parser_default = None
        source = inspect.getsource(investment_harness.main)
        for line in source.splitlines():
            if '"--analysis-interval-seconds"' in line:
                parser_default = line
        self.assertIn("default=3 * 60 * 60", parser_default or "")


if __name__ == "__main__":
    unittest.main()
