from __future__ import annotations

import unittest

from investment_agent.execution.orders.lifecycle import (
    AutonomyEvidence, LifecyclePromotionGate, LifecycleStage,
)


class LifecycleAndPaperTest(unittest.TestCase):
    def test_autonomy_requires_clean_evidence_and_hard_limits(self):
        evidence = AutonomyEvidence(
            oos_days=200, walk_forward_windows=10, paper_days=90, sharpe=1.0,
            max_drawdown=-0.1, execution_errors=0, reconciliation_errors=0,
            risk_violations=0, data_quality_incidents=0,
            kill_switch_test_passed=True, broker_reconciliation_passed=True,
        )
        decision = LifecyclePromotionGate().evaluate(
            from_stage=LifecycleStage.LIVE_MANUAL,
            to_stage=LifecycleStage.LIVE_AUTONOMOUS,
            evidence=evidence,
            hard_limits={
                "max_order_notional_usd": 1000, "max_daily_notional_usd": 5000,
                "max_daily_orders": 10, "max_daily_loss_usd": 500,
                "max_drawdown_fraction": 0.1,
            },
        )
        self.assertTrue(decision.is_approved)



if __name__ == "__main__":
    unittest.main()
