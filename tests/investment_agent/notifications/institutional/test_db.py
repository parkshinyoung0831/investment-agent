"""gurus 알림의 공통 발송 이력 계약을 검증한다."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from investment_agent.notifications.outbox import Outbox
from investment_agent.reporting.notifications.institutional import db


class NotificationLogTest(unittest.TestCase):
    def test_sent_keys_is_scoped_to_institutional_outbox(self):
        """sent_keys()는 이제 원격 notifications 스키마가 아니라 로컬
        Outbox(notification_outbox)를 producer로 좁혀 읽는다."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sqlite3"
            with patch.dict("os.environ", {"AI_INVESTOR_RUNTIME_DB_PATH": str(path)}):
                Outbox().enqueue(
                    producer="institutional", notification_key="x", kind="report",
                    target="123", message={"content": "c"}, now=datetime.now(timezone.utc),
                )
                Outbox().enqueue(
                    producer="other", notification_key="y", kind="report",
                    target="123", message={"content": "c"}, now=datetime.now(timezone.utc),
                )
                self.assertEqual(db.sent_keys(), {"x"})


if __name__ == "__main__":
    unittest.main()
