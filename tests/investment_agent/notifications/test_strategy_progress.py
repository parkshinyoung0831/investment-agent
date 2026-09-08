"""상태가 진전되지 않는 전략 배치도 한 실행 안에서는 한 번만 처리한다."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from investment_agent.notifications.strategy import service


class StrategyProgressTest(unittest.TestCase):
    def test_unsent_batch_does_not_loop_or_block_later_months(self):
        rows = [{"apply_date": "2026-08-01"}, {"apply_date": "2026-09-01"}]
        with patch.object(service, "configured_database"), patch.object(service, "load_config"), \
                patch.object(service, "load_pending", return_value=rows) as load, \
                patch.object(service, "_build_cards", return_value=([], {})), \
                patch.object(service, "_enqueue_batch", return_value=0) as enqueue, \
                patch.object(service.time, "sleep"):
            self.assertEqual(0, service.run(service=Mock(), summary_target="123", target="456"))
        load.assert_called_once_with()
        self.assertEqual(2, enqueue.call_count)

    def test_unconfirmed_deliveries_are_not_marked_sent(self):
        from investment_agent.notifications.service import DispatchResult
        fake = Mock()
        fake.enqueue.return_value = DispatchResult("duplicate")
        fake.run_pending.return_value = [DispatchResult("unknown", "strategy", "allocation:GEM:2026-09-01")]
        card = Mock(allocation_id="GEM:2026-09-01", embed={"title": "GEM"})
        with patch.object(service, "build_summary", return_value=None), patch.object(service, "mark_sent") as mark:
            self.assertEqual(0, service._enqueue_batch(
                [{"apply_date": "2026-09-01"}], [card], {}, service=fake,
                summary_target="123", target="456",
            ))
        mark.assert_not_called()
