from __future__ import annotations

import unittest

from investment_agent.execution.orders.lifecycle import (
    AutonomyEvidence, LifecyclePromotionGate, LifecycleStage,
)


_HARD_LIMITS = {
    "max_order_notional_usd": 1000, "max_daily_notional_usd": 5000,
    "max_daily_orders": 10, "max_daily_loss_usd": 500,
    "max_drawdown_fraction": 0.1,
}


def _evidence(**overrides) -> AutonomyEvidence:
    # 낙폭은 **양수** 관례다(`RuntimeRiskState.drawdown_fraction`과 같다).
    base = dict(
        oos_days=200, walk_forward_windows=10, paper_days=90, sharpe=1.0,
        max_drawdown=0.1, execution_errors=0, reconciliation_errors=0,
        risk_violations=0, data_quality_incidents=0,
        kill_switch_test_passed=True, broker_reconciliation_passed=True,
    )
    base.update(overrides)
    return AutonomyEvidence(**base)


class LifecycleAndPaperTest(unittest.TestCase):
    def _decide(self, evidence: AutonomyEvidence):
        return LifecyclePromotionGate().evaluate(
            from_stage=LifecycleStage.LIVE_MANUAL,
            to_stage=LifecycleStage.LIVE_AUTONOMOUS,
            evidence=evidence,
            hard_limits=dict(_HARD_LIMITS),
        )

    def test_autonomy_requires_clean_evidence_and_hard_limits(self):
        self.assertTrue(self._decide(_evidence()).is_approved)

    def test_a_drawdown_over_the_threshold_blocks_autonomy(self):
        """양수 관례에서 20% 낙폭은 15% 기준을 넘는다. 전에는 `< -0.15` 비교라
        **어떤 낙폭도 위반이 되지 않았다**(감사 EX2-15)."""
        decision = self._decide(_evidence(max_drawdown=0.20))
        self.assertFalse(decision.is_approved)
        self.assertTrue(any("drawdown" in v for v in decision.violations))

    def test_a_negative_drawdown_is_rejected_at_construction(self):
        """같은 사실을 어떤 부호로 넣는지에 판정이 달리면 안 된다."""
        with self.assertRaisesRegex(ValueError, "max_drawdown"):
            _evidence(max_drawdown=-0.1)



if __name__ == "__main__":
    unittest.main()
