"""전송 도중 죽어 `sending`에 남은 알림은 자동으로 다시 보내지 않으므로, 최소한 드러나야 한다(NT-08)."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from investment_agent.notifications import db as ledger_db
from investment_agent.notifications.ledger import STUCK_SENDING_SECONDS, MemoryLedger

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
KEY = ("earnings.report", "AAPL", "0001")


def _sending_ledger(age: timedelta) -> MemoryLedger:
    clock = {"now": NOW - age}
    ledger = MemoryLedger(clock=lambda: clock["now"])
    ledger.ensure_baseline(KEY[0], NOW - timedelta(days=30))
    ledger.reserve(KEY[0], [{"subject": KEY[1], "occurrence": KEY[2], "revision": "a" * 64, "fact_at": NOW.isoformat()}],
                   owner="run-1", lease_seconds=60, revisable=False)
    ledger.begin_send(KEY[0], [(KEY[1], KEY[2])], owner="run-1")
    clock["now"] = NOW
    return ledger


class StuckSendingTest(unittest.TestCase):
    def test_a_notice_stuck_in_sending_is_listed(self) -> None:
        ledger = _sending_ledger(timedelta(seconds=STUCK_SENDING_SECONDS + 60))
        self.assertEqual([KEY], ledger.stuck_sending())

    def test_a_send_that_is_still_in_flight_is_not(self) -> None:
        ledger = _sending_ledger(timedelta(seconds=30))
        self.assertEqual([], ledger.stuck_sending())

    def test_the_postgres_adapter_asks_for_old_sending_rows_only(self) -> None:
        seen: dict = {}

        class Query:
            def select(self, columns):
                seen["columns"] = columns
                return self

            def eq(self, column, value):
                seen["eq"] = (column, value)
                return self

            def lt(self, column, value):
                seen["lt"] = (column, value)
                return self

        class Database:
            def table(self, schema, table):
                seen["table"] = (schema, table)
                return Query()

            def select_paged(self, factory, *, order_by):
                factory()
                seen["order_by"] = order_by
                return [{"topic": "earnings.report", "subject": "AAPL", "occurrence": "0001"}]

        ledger = ledger_db.PostgresNotificationLedger(Database())
        self.assertEqual([KEY], ledger.stuck_sending())
        self.assertEqual(("notifications", "notices"), seen["table"])
        self.assertEqual(("status", "sending"), seen["eq"])
        self.assertEqual("updated_at", seen["lt"][0])


if __name__ == "__main__":
    unittest.main()
