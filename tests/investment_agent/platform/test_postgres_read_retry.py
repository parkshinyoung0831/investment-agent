from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from httpx import RemoteProtocolError
from investment_agent.platform.db.postgres import select_all_paged


class PostgresReadRetryTest(unittest.TestCase):
    def test_failed_page_rebuilt_without_duplicate_rows(self):
        ranges = []
        results = iter([[{"id": 1}], RemoteProtocolError("GOAWAY"), [{"id": 2}], []])

        def factory():
            builder = Mock()
            builder.range.side_effect = lambda start, end: ranges.append((start, end)) or builder
            builder.order.return_value = builder

            def execute():
                result = next(results)
                if isinstance(result, Exception):
                    raise result
                return SimpleNamespace(data=result)
            builder.execute.side_effect = execute
            return builder

        self.assertEqual(select_all_paged(factory, page_size=1, order_by="id"), [{"id": 1}, {"id": 2}])
        self.assertEqual(ranges, [(0, 0), (1, 1), (1, 1), (2, 2)])

    def test_persistent_protocol_error_is_bounded(self):
        builder = Mock()
        builder.range.return_value = builder
        builder.order.return_value = builder
        builder.execute.side_effect = RemoteProtocolError("GOAWAY")
        with self.assertRaises(RemoteProtocolError):
            select_all_paged(lambda: builder, order_by="id")
        self.assertEqual(builder.execute.call_count, 3)
