from __future__ import annotations

import importlib.util
import unittest

from investment_agent.execution import brokers


class TossOnlyTest(unittest.TestCase):
    def test_removed_broker_entrypoints_cannot_be_loaded(self):
        for module in (
            "investment_agent.execution.brokers.kis",
            "investment_agent.execution.brokers.router",
            "investment_agent.execution.orders.paper_worker",
        ):
            with self.subTest(module=module):
                self.assertIsNone(importlib.util.find_spec(module))

    def test_public_broker_contract_has_no_removed_adapters(self):
        for name in ("KISPaperBrokerAdapter", "KISLiveBrokerAdapter", "BrokerRouter"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(brokers, name))
