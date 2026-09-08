"""notifications_dispatch 진입점 테스트. 네트워크나 실거래 플래그 변경 없이 검증한다."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from investment_agent.config import Config
from investment_agent.operations.commands.notifications_dispatch import build_service, dispatch_pending, main
from investment_agent.notifications.service import DispatchResult


class NotificationsDispatchEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config({"DISCORD_BOT_TOKEN": "test_bot_token"}, None, False)
        self.db = MagicMock()

    def test_build_service_wires_dry_run_mock_post(self) -> None:
        service = build_service(self.config, self.db, dry_run=True)
        self.assertIsNotNone(service)
        # Verify the channel uses a custom post function in dry_run mode
        self.assertIsNotNone(service._channel._post)
        resp = service._channel._post("http://test", json={})
        self.assertEqual(200, resp.status_code)
        self.assertEqual("dry_run_message_id", resp.json()["id"])

    def test_dispatch_pending_success_returns_zero(self) -> None:
        mock_service = MagicMock()
        mock_service.run_pending.return_value = [
            DispatchResult(status="sent", producer="p", notification_key="k1", message_id="m1"),
            DispatchResult(status="skipped", producer="p", notification_key="k2"),
        ]
        code = dispatch_pending(service=mock_service)
        self.assertEqual(0, code)
        mock_service.run_pending.assert_called_once()

    def test_dispatch_pending_with_error_returns_one(self) -> None:
        mock_service = MagicMock()
        mock_service.run_pending.return_value = [
            DispatchResult(status="sent", producer="p", notification_key="k1"),
            DispatchResult(status="error", producer="p", notification_key="k2", reason="db_error"),
        ]
        code = dispatch_pending(service=mock_service)
        self.assertEqual(1, code)

    def test_dispatch_pending_handles_failed_status_as_success_code(self) -> None:
        # Business-level failures (recorded in deliveries table) do not crash the runner
        mock_service = MagicMock()
        mock_service.run_pending.return_value = [
            DispatchResult(status="failed", producer="p", notification_key="k1", reason="429_rate_limit"),
            DispatchResult(status="abandoned", producer="p", notification_key="k2", reason="rejected"),
        ]
        code = dispatch_pending(service=mock_service)
        self.assertEqual(0, code)

    def test_dispatch_pending_limit_slices_results(self) -> None:
        mock_service = MagicMock()
        mock_service.run_pending.return_value = [
            DispatchResult(status="sent", producer="p", notification_key="k1"),
            DispatchResult(status="sent", producer="p", notification_key="k2"),
            DispatchResult(status="error", producer="p", notification_key="k3", reason="unreachable"),
        ]
        # Limiting to 2 excludes the 3rd item which had an error
        code = dispatch_pending(service=mock_service, limit=2)
        self.assertEqual(0, code)

    @patch("investment_agent.operations.commands.notifications_dispatch.dispatch_pending")
    def test_main_cli_arguments(self, mock_dispatch: MagicMock) -> None:
        mock_dispatch.return_value = 0
        code = main(["--dry-run", "--limit", "10"])
        self.assertEqual(0, code)
        mock_dispatch.assert_called_once_with(dry_run=True, limit=10)

    @patch("investment_agent.operations.commands.notifications_dispatch.dispatch_pending")
    def test_main_handles_unhandled_exception(self, mock_dispatch: MagicMock) -> None:
        mock_dispatch.side_effect = RuntimeError("unexpected crash")
        code = main([])
        self.assertEqual(1, code)


if __name__ == "__main__":
    unittest.main()
