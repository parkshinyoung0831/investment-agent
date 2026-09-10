"""발표 예정 알림의 preflight가 실제 상태 dict와 같은 키를 읽는지 지킨다.

이 진입점은 테스트가 없어서, `pending_state()`의 키가 `upcoming` -> `upcoming_releases`로
바뀐 뒤에도 GITHUB_OUTPUT 쓰기만 옛 이름을 남긴 채 매 실행 KeyError로 죽었다. 로컬
테스트는 전부 통과했고 Actions에서만 깨졌다. 그래서 여기서는 mock dict를 손으로 적지
않고 **실제 `pending_state()`가 돌려준 것**을 그대로 `main()`에 넣는다.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from investment_agent.notifications.earnings_calendar import candidates
from investment_agent.notifications.earnings_calendar import pending
from investment_agent.reporting.services.earnings import schedule as metrics


class CalendarPreflightTests(unittest.TestCase):
    def test_preflight_reads_only_keys_the_real_state_provides(self) -> None:
        # 관심종목이 비면 collect가 조회 없이 끝난다 — 네트워크·DB를 때리지 않는다.
        store = Mock(watchlist_members=lambda: [], sent_weeks=lambda: set(),
                     sent_schedule_keys=lambda: set())
        with patch.object(candidates, "_default_store", return_value=store):
            state = candidates.pending_state()

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "github-output.txt"
            with patch.object(pending, "pending_state", return_value=state):
                self.assertEqual(pending.main(["--github-output", str(output)]), 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "should_notify=false\n")

    def test_pending_state_keys_are_the_contract(self) -> None:
        store = Mock(watchlist_members=lambda: [], sent_weeks=lambda: set(),
                     sent_schedule_keys=lambda: set())
        with patch.object(candidates, "_default_store", return_value=store):
            state = candidates.pending_state()
        self.assertEqual(
            set(state), {"iso_week", "upcoming_releases", "schedule_updates", "should_notify"}
        )
        self.assertEqual(state["iso_week"], metrics.iso_week(date.today()))
        self.assertEqual(state["upcoming_releases"], 0)
        self.assertEqual(state["schedule_updates"], 0)
        self.assertFalse(state["should_notify"])

    def test_output_says_true_when_something_is_waiting(self) -> None:
        row = {"ticker": "TEST"}
        store = Mock(sent_weeks=lambda: set(), sent_schedule_keys=lambda: set())
        with patch.object(candidates, "collect", return_value=([row], None, "2026-W36")):
            state = candidates.pending_state(store=store)
        self.assertTrue(state["should_notify"])
        self.assertEqual(state["upcoming_releases"], 1)
        self.assertEqual(state["schedule_updates"], 0)

    def test_sent_week_with_a_new_schedule_still_runs_dispatch(self) -> None:
        row = {"ticker": "TEST", "expected": "2026-09-08", "target_fiscal_year": 2026,
               "target_fiscal_period": "Q3"}
        store = Mock(sent_weeks=lambda: {"2026-W36"}, sent_schedule_keys=lambda: set())
        with patch.object(candidates, "collect", return_value=([row], None, "2026-W36")):
            state = candidates.pending_state(store=store)

        self.assertEqual(state["schedule_updates"], 1)
        self.assertTrue(state["should_notify"])

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "github-output.txt"
            with patch.object(pending, "pending_state", return_value=state):
                self.assertEqual(pending.main(["--github-output", str(output)]), 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "should_notify=true\n")


if __name__ == "__main__":
    unittest.main()
