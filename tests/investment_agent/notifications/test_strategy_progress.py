"""월간 전략 알림 — 적용월마다 요약 한 장과 전략별 카드가 한 번씩 닿는다."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from investment_agent.notifications.strategy import service
from tests.investment_agent.notifications.fakes import memory_context


def _row(strategy_id: str, apply_date: str) -> dict:
    return {"strategy_id": strategy_id, "apply_date": apply_date, "weights": {"SPY": 1.0}, "signals": {}}


class StrategyNotificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context, self.ledger, self.channel = memory_context()

    def _run(self, rows) -> int:
        with (
            patch.object(service, "load_config", return_value=None),
            patch.object(service, "load_recent_allocations", return_value=rows),
            patch.object(service, "discord_target", side_effect=lambda kind, **_k: {"strategy_summary": "111"}.get(kind, "222")),
            patch.object(service, "_card", side_effect=lambda raw: (
                SimpleNamespace(allocation_id=f"{raw['strategy_id']}:{raw['apply_date']}", embed={"title": raw["strategy_id"]}),
                raw["weights"])),
            patch.object(service, "build_summary", return_value={"title": "summary"}),
            patch.object(service, "_strategy_tags", return_value=()),
        ):
            return service.run(context=self.context)

    def test_a_month_is_announced_once_with_one_card_per_strategy(self) -> None:
        rows = [_row("gem", "2026-10-01"), _row("haa", "2026-10-01")]

        self.assertEqual(self._run(rows), 3)
        self.assertEqual(self._run(rows), 0)
        summary, *cards = self.channel.created
        self.assertEqual(summary["target"], "111")
        self.assertEqual([(c["target"], c["thread"].key) for c in cards], [("222", "gem"), ("222", "haa")])

    def test_an_earlier_unsent_month_does_not_block_the_next(self) -> None:
        """한 달의 실패가 다음 달을 막거나 같은 실행에서 무한히 다시 돌지 않는다."""
        self.channel.failures.append(RuntimeError("transport"))

        delivered = self._run([_row("gem", "2026-09-01"), _row("gem", "2026-10-01")])

        self.assertEqual(delivered, 3)
        self.assertEqual(self.ledger.status("strategy.month", "all", "2026-09-01"), "unknown")


if __name__ == "__main__":
    unittest.main()
