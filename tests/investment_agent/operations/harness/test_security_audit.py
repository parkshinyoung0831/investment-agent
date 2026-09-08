"""operations.harness.security_audit 단위 테스트."""
from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from investment_agent.operations.commands.security_audit import main as cli_main
from investment_agent.operations.harness.contracts import HarnessMode
from investment_agent.operations.harness.security_audit import (
    CheckStatus,
    generate_hmac_secret,
    run_security_audit,
)


class TestSecurityAudit(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[3]

    def test_generate_hmac_secret(self) -> None:
        secret = generate_hmac_secret()
        self.assertEqual(len(secret), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in secret))

        # 고유성 확인
        secret2 = generate_hmac_secret()
        self.assertNotEqual(secret, secret2)

    def test_kill_switches_safe_defaults(self) -> None:
        env = {
            "TRADING_KILL_SWITCH": "on",
            "TOSS_LIVE_ENABLED": "false",
            "TOSS_ALLOW_MARKET_ORDERS": "false",
        }
        report = run_security_audit(environ=env, repository_root=self.repo_root)
        kill_checks = [r for r in report.results if r.category == "KILL_SWITCHES"]
        self.assertTrue(all(r.status == CheckStatus.PASS for r in kill_checks))

    def test_kill_switches_market_orders_fail(self) -> None:
        env = {
            "TRADING_KILL_SWITCH": "on",
            "TOSS_LIVE_ENABLED": "false",
            "TOSS_ALLOW_MARKET_ORDERS": "true",
        }
        report = run_security_audit(environ=env, repository_root=self.repo_root)
        market_order_check = next(r for r in report.results if r.code == "MARKET_ORDERS_PROHIBITED")
        self.assertEqual(market_order_check.status, CheckStatus.FAIL)

    def test_discord_bot_tokens_identical_fail(self) -> None:
        env = {
            "DISCORD_BOT_TOKEN": "bot_token_12345",
            "DISCORD_APPROVAL_BOT_TOKEN": "bot_token_12345",
        }
        report = run_security_audit(environ=env, repository_root=self.repo_root)
        token_check = next(r for r in report.results if r.code == "DISCORD_BOT_TOKENS_IDENTICAL")
        self.assertEqual(token_check.status, CheckStatus.FAIL)

    def test_discord_hmac_secret_weak_or_short_fail(self) -> None:
        # 1. 짧은 키
        env_short = {"DISCORD_APPROVAL_HMAC_SECRET": "short_secret"}
        report_short = run_security_audit(environ=env_short, repository_root=self.repo_root)
        check_short = next(r for r in report_short.results if r.code == "HMAC_SECRET_TOO_SHORT")
        self.assertEqual(check_short.status, CheckStatus.FAIL)

        # 2. 취약/기본 키
        env_weak = {"DISCORD_APPROVAL_HMAC_SECRET": "12345678901234567890123456789012"}
        # 패스 확인
        report_pass = run_security_audit(environ=env_weak, repository_root=self.repo_root)
        check_pass = next(r for r in report_pass.results if r.code == "HMAC_SECRET_STRONG")
        self.assertEqual(check_pass.status, CheckStatus.PASS)

        env_default = {"DISCORD_APPROVAL_HMAC_SECRET": "secret"}
        report_default = run_security_audit(environ=env_default, repository_root=self.repo_root)
        check_default = next(r for r in report_default.results if r.code == "HMAC_SECRET_TOO_SHORT")
        self.assertEqual(check_default.status, CheckStatus.FAIL)

    def test_approval_workflow_requires_channel_and_approvers(self) -> None:
        env = {
            "DISCORD_BOT_TOKEN": "bot_token_1",
            "DISCORD_APPROVAL_BOT_TOKEN": "bot_token_2",
            "DISCORD_APPROVAL_HMAC_SECRET": generate_hmac_secret(),
            "DISCORD_CHANNEL_AI_APPROVALS": "",
            "DISCORD_APPROVER_USER_IDS": "",
        }
        report = run_security_audit(
            environ=env,
            repository_root=self.repo_root,
            mode=HarnessMode.APPROVAL_WORKFLOW,
        )
        channel_check = next(r for r in report.results if r.code == "APPROVAL_CHANNEL_MISSING")
        approver_check = next(r for r in report.results if r.code == "APPROVER_ALLOWLIST_EMPTY")
        self.assertEqual(channel_check.status, CheckStatus.FAIL)
        self.assertEqual(approver_check.status, CheckStatus.FAIL)
        self.assertFalse(report.healthy)

    def test_trading_limits_validation(self) -> None:
        # order limit exceeds daily limit
        env = {
            "TOSS_MAX_DAILY_NOTIONAL_USD": "1000",
            "TOSS_MAX_ORDER_NOTIONAL_USD": "5000",
        }
        report = run_security_audit(environ=env, repository_root=self.repo_root)
        check = next(r for r in report.results if r.code == "ORDER_MAX_EXCEEDS_DAILY")
        self.assertEqual(check.status, CheckStatus.FAIL)

    def test_session_windows_validation(self) -> None:
        # Invalid time format
        env = {
            "HARNESS_NY_SESSION_START": "9:40",  # missing leading zero
        }
        report = run_security_audit(environ=env, repository_root=self.repo_root)
        check = next(r for r in report.results if r.code == "INVALID_TIME_FORMAT_HARNESS_NY_SESSION_START")
        self.assertEqual(check.status, CheckStatus.FAIL)

        # Inverted session window
        env_inverted = {
            "HARNESS_NY_SESSION_START": "15:00",
            "HARNESS_NY_SESSION_END": "09:00",
        }
        report_inverted = run_security_audit(environ=env_inverted, repository_root=self.repo_root)
        check_inverted = next(r for r in report_inverted.results if r.code == "SESSION_WINDOW_INVALID")
        self.assertEqual(check_inverted.status, CheckStatus.FAIL)

    def test_cli_generate_hmac(self) -> None:
        out = io.StringIO()
        with patch("sys.stdout", out):
            code = cli_main(["--generate-hmac"])
        self.assertEqual(code, 0)
        output = out.getvalue()
        self.assertIn("Key File:", output)
        self.assertIn("Fingerprint (SHA256):", output)
        self.assertNotIn("DISCORD_APPROVAL_HMAC_SECRET=", output)

    def test_cli_json_and_healthy_exit(self) -> None:
        clean_env = {
            "TRADING_KILL_SWITCH": "on",
            "TOSS_LIVE_ENABLED": "false",
            "TOSS_ALLOW_MARKET_ORDERS": "false",
            "DISCORD_BOT_TOKEN": "bot_1",
            "DISCORD_APPROVAL_BOT_TOKEN": "bot_2",
            "DISCORD_APPROVAL_HMAC_SECRET": generate_hmac_secret(),
        }
        out = io.StringIO()
        with patch.dict("os.environ", clean_env, clear=True), patch("sys.stdout", out):
            code = cli_main(["--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(out.getvalue())
        self.assertTrue(parsed["healthy"])
        self.assertIn("summary", parsed)
        self.assertIn("results", parsed)

    def test_cli_failure_exit_code(self) -> None:
        fail_env = {
            "TOSS_ALLOW_MARKET_ORDERS": "true",
        }
        out = io.StringIO()
        with patch.dict("os.environ", fail_env, clear=True), patch("sys.stdout", out):
            code = cli_main(["--strict"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
