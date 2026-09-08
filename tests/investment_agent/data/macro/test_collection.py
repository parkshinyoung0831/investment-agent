"""소스별 벽시계 예산 — 느린 출처 하나가 수집 전체를 삼키지 못하게 한다.

ECOS가 응답하지 않던 날, 요청당 30초 타임아웃에 재시도 4회가 지표 15종에 곱해져
워크플로 캡(20분)을 넘겼다. 그러면 이미 받아둔 미국 지표까지 통째로 버려진다.
예산을 넘긴 뒤에는 호출을 멈추고 실패로 적어 부분 성공을 남기는지 확인한다.
"""
from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from investment_agent.data.macro.infrastructure import fetch as _shared
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)


def _indicator(sid: str) -> dict:
    return {"series_id": sid, "name_ko": sid, "unit": "index",
            "series_kind": "level", "frequency": "daily"}


def _series() -> pd.Series:
    return pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-08-17", "2026-08-18"]))


class SourceBudgetTest(unittest.TestCase):
    def _run(self, clock_steps, budget):
        """clock_steps를 monotonic 반환값으로 흘려보내며 3개 지표를 수집한다."""
        indicators = [_indicator(s) for s in ("A", "B", "C")]
        with mock.patch.object(_shared.time, "monotonic", side_effect=list(clock_steps)), \
             mock.patch.object(_shared, "validate_series"):
            return _shared.safe_fetch(log, indicators, lambda _ind: _series(),
                                    budget_sec=budget)

    def test_all_fetched_when_inside_the_budget(self):
        # start=0, 각 지표 진입 시각 1/2/3초 — 예산 60초 안이다.
        out, failures = self._run([0, 1, 2, 3], 60)

        self.assertEqual(failures, [])
        self.assertEqual(sorted(k for k, v in out.items() if not v.empty), ["A", "B", "C"])

    def test_remaining_series_fail_once_the_budget_is_gone(self):
        # start=0, A는 1초에 진입(통과), B는 100초에 진입 — 예산 10초를 넘겼다.
        out, failures = self._run([0, 1, 100, 101], 10)

        self.assertEqual([f["series_id"] for f in failures], ["B", "C"])
        self.assertEqual([f["type"] for f in failures], ["TimeoutError", "TimeoutError"])
        # 예산 전에 받은 값은 살아 있어야 한다 — 부분 성공을 버리지 않는 게 요점이다.
        self.assertFalse(out["A"].empty)

    def test_zero_budget_means_unlimited(self):
        out, failures = self._run([0, 10_000, 20_000, 30_000], 0)

        self.assertEqual(failures, [])
        self.assertFalse(out["C"].empty)

    def test_empty_result_is_fail_closed(self):
        indicators = [_indicator("EMPTY")]
        with mock.patch.object(_shared, "validate_series"):
            out, failures = _shared.safe_fetch(
                log, indicators, lambda _ind: pd.Series(dtype=float), budget_sec=0
            )

        self.assertTrue(out["EMPTY"].empty)
        self.assertEqual(failures[0]["type"], "ValueError")

    def test_default_budget_fits_inside_the_workflow_cap(self):
        """예산이 잡 캡(20분)보다 크면 상한을 둔 의미가 없다."""
        self.assertLess(_shared.SOURCE_BUDGET_SEC, 20 * 60)


if __name__ == "__main__":
    unittest.main()
