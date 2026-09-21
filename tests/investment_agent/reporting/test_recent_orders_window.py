"""주문 알림 창은 갱신 시각을 시각으로 비교한다 — 문자열 사전순은 표기가 다르면 경계에서 어긋난다(NT-10)."""
from __future__ import annotations

import unittest
from unittest import mock

from investment_agent.reporting.notifications.investment import db

SINCE = "2026-09-21T00:00:00+00:00"


def _order(order_id: str, updated_at) -> dict:
    return {"client_order_id": order_id, "intent_id": f"i-{order_id}", "updated_at": updated_at}


def _rows(dataset: str):
    if dataset == "orders":
        return [
            _order("z-suffix", "2026-09-21T00:00:01Z"),          # 'Z' 표기: 사전순으로는 '+00:00'보다 크다
            _order("space-separated", "2026-09-21 09:00:00+09:00"),  # 공백 구분·KST: 00:00 UTC 정각, 경계 포함
            _order("before", "2026-09-20T23:59:59+00:00"),
            _order("kst-before", "2026-09-21T08:59:59+09:00"),    # UTC로 전날 23:59:59
        ]
    return []


class RecentOrdersWindowTest(unittest.TestCase):
    def test_the_window_compares_instants_not_strings(self):
        with mock.patch.object(db, "read_runtime_rows", side_effect=_rows):
            found = {row["order"]["client_order_id"] for row in db.recent_orders(since_at=SINCE)}
        self.assertEqual({"z-suffix", "space-separated"}, found)

    def test_an_unreadable_timestamp_is_kept_not_silently_dropped(self):
        def rows(dataset):
            return [_order("garbled", "yesterday-ish")] if dataset == "orders" else []

        with mock.patch.object(db, "read_runtime_rows", side_effect=rows):
            found = [row["order"]["client_order_id"] for row in db.recent_orders(since_at=SINCE)]
        self.assertEqual(["garbled"], found)


if __name__ == "__main__":
    unittest.main()
