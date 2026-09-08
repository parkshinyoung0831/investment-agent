"""fundamentals 외부 시스템 어댑터의 공개 모듈을 검증한다."""
from __future__ import annotations

import importlib
import unittest


class InfrastructureAdapterContractTest(unittest.TestCase):
    def test_expected_adapter_modules_are_importable(self) -> None:
        names = (
            "investment_agent.data.fundamentals.infrastructure.sec.companyfacts",
            "investment_agent.data.fundamentals.infrastructure.sec.filing_documents",
            "investment_agent.data.fundamentals.infrastructure.sec.press_releases",
            "investment_agent.data.fundamentals.infrastructure.yahoo_finance.consensus",
            "investment_agent.data.fundamentals.infrastructure.yahoo_finance.reported_earnings",
            "investment_agent.data.fundamentals.infrastructure.supabase.company_financials",
            "investment_agent.data.fundamentals.infrastructure.supabase.earnings_events",
        )
        for name in names:
            with self.subTest(module=name):
                self.assertIsNotNone(importlib.import_module(name))


if __name__ == "__main__":
    unittest.main()
