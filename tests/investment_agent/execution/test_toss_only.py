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

    def test_no_broker_neutral_contract_exists_without_an_implementation(self):
        """구현체도 호출자도 없는 broker 중립 계약은 두 번째 broker의 근거가 아니라 오해의 근거다."""
        self.assertIsNone(importlib.util.find_spec("investment_agent.execution.brokers.contracts"))
        for name in ("BrokerAdapter", "CanonicalOrderRequest", "BrokerOrder", "BrokerFill"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(brokers, name))
