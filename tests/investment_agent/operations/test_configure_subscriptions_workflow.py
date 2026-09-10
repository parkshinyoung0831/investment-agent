"""notify_strategy 워크플로의 단계 순서·산출물 계약을 검증한다."""
from __future__ import annotations

import unittest
from pathlib import Path


class StrategyWorkflowOrderingTest(unittest.TestCase):
    def test_strategy_dependencies_and_exact_source_artifact_precede_send(self):
        root = Path(__file__).resolve().parents[3]
        text = (root / ".github/workflows/notify_strategy.yml").read_text(encoding="utf-8")
        # 준비가 먼저다 — 지금은 composite action이 그 자리를 대신한다.
        self.assertLess(
            text.index("./.github/actions/python-job"),
            text.index("commands.validate_subscriptions"),
        )
        self.assertLess(text.index("name: Validate source run"), text.index("uses: actions/download-artifact@v4"))
        self.assertLess(text.index("uses: actions/download-artifact@v4"), text.index("notify --kind strategy"))
        self.assertIn("run-id: ${{ github.event.workflow_run.id || inputs.source_run_id }}", text)
        self.assertIn('run["head_branch"] == "main"', text)
        for workflow, artifact in (("strategy_monthly", "research-strategy"), ("tech_indicators", "research-features")):
            producer = (root / f".github/workflows/{workflow}.yml").read_text(encoding="utf-8")
            self.assertIn(f"name: {artifact}", producer)
            self.assertIn("if-no-files-found: error", producer)

    def test_regular_notification_workflows_declare_their_own_channel_env(self) -> None:
        """channel routing은 이제 DB가 아니라 각 워크플로의 env가 SSOT다 —
        validate_subscriptions는 그 env가 실제로 설정됐는지만 확인한다."""
        root = Path(__file__).resolve().parents[3]
        workflow_dir = root / ".github" / "workflows"
        expected = {
            "notify_macro_core.yml": ("--kind macro_core", "DISCORD_CHANNEL_MACRO_DAILY"),
            "notify_macro_watch.yml": ("--kind macro_watch", "DISCORD_CHANNEL_MACRO_ALERT"),
            "notify_econ_calendar_release.yml": (
                "--kind econ_calendar_release", "DISCORD_CHANNEL_ECON_CALENDAR_RELEASE",
            ),
            "notify_fundamentals.yml": (
                "--kind fundamentals_flash", "--kind fundamentals_earnings",
                "DISCORD_CHANNEL_EARNINGS",
            ),
            "notify_fundamentals_calendar.yml": (
                "--kind fundamentals_calendar", "DISCORD_CHANNEL_EARNINGS_CALENDAR",
            ),
            "notify_investment.yml": (
                "--kind investment_portfolio", "--kind investment_candidates",
                "--kind investment_trades",
                "DISCORD_CHANNEL_AI_REPORTS", "DISCORD_CHANNEL_AI_TRADES",
            ),
            "notify_strategy.yml": (
                "--kind strategy_summary", "--kind strategy",
                "DISCORD_CHANNEL_STRATEGY_MONTHLY", "DISCORD_CHANNEL_STRATEGY_FORUM",
            ),
            "institutional_13f.yml": ("--kind institutional", "DISCORD_CHANNEL_GURUS"),
            "econ_calendar_watch.yml": (
                "--kind econ_calendar_release", "DISCORD_CHANNEL_ECON_CALENDAR_RELEASE",
            ),
        }
        for name in sorted(expected):
            with self.subTest(workflow=name):
                text = (workflow_dir / name).read_text(encoding="utf-8")
                self.assertIn("validate_subscriptions", text)
                for token in expected[name]:
                    self.assertIn(token, text)

        institutional = (workflow_dir / "institutional_13f.yml").read_text(encoding="utf-8")
        self.assertIn("notify --kind gurus_13f", institutional)

    def test_bootstrap_no_longer_writes_a_database_subscription(self) -> None:
        root = Path(__file__).resolve().parents[3]
        text = (root / ".github" / "workflows" / "notify_bootstrap.yml").read_text(encoding="utf-8")
        self.assertNotIn("configure_subscriptions", text)
        self.assertIn("DISCORD_CHANNEL_AI_REPORTS", text)
        self.assertIn("DISCORD_CHANNEL_AI_TRADES", text)


if __name__ == "__main__":
    unittest.main()
