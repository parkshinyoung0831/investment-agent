"""producer가 Discord 채널 환경변수로 subscription 경계를 우회하지 않는지 검증한다."""
from __future__ import annotations

import unittest
from pathlib import Path


class SubscriptionRoutingContractTest(unittest.TestCase):
    def test_notification_producers_do_not_read_channel_environment_variables(self) -> None:
        root = Path(__file__).resolve().parents[3]
        producer_files = (
            "notifications/macro/core.py",
            "notifications/macro/watch.py",
            "notifications/econ_calendar/run.py",
            "notifications/earnings_calendar/run.py",
            "notifications/earnings_flash/run.py",
            "notifications/earnings_report/run.py",
            "notifications/institutional/run.py",
            "notifications/strategy/service.py",
            "notifications/investment/run_portfolio.py",
            "notifications/investment/run_candidates.py",
            "notifications/investment/run_trades.py",
        )
        for relative in producer_files:
            with self.subTest(producer=relative):
                text = (root / "src" / "investment_agent" / relative).read_text(
                    encoding="utf-8"
                )
                self.assertNotIn("DISCORD_CHANNEL_", text)


if __name__ == "__main__":
    unittest.main()
