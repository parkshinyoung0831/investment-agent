from __future__ import annotations

import unittest
from datetime import datetime, timezone

from investment_agent.trading.portfolio.contracts import PortfolioProposal
from investment_agent.trading.risk.gate import (
    DeterministicRiskGate,
    PortfolioRiskPolicy,
    portfolio_turnover,
)


def proposal(weights: dict[str, float], as_of_at: str = "2026-08-21T11:00:00+00:00"):
    return PortfolioProposal.create(
        run_id="run-1", source_type="llm", source_version="ta-v1",
        stage="shadow", as_of_at=as_of_at, weights=weights,
        confidence=0.8, reasoning=("test",),
    )


class TailRiskLimitTest(unittest.TestCase):
    DECIDED = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)

    def _evaluate(self, *, cvar, stage="shadow", policy=None):
        item = PortfolioProposal.create(
            run_id="run-1", source_type="llm", source_version="ta-v1", stage=stage,
            as_of_at="2026-08-21T11:00:00+00:00", weights={"AAPL": 0.05, "CASH": 0.95},
            confidence=0.8, reasoning=("test",),
        )
        return DeterministicRiskGate(policy or PortfolioRiskPolicy()).evaluate(
            item, current_weights={"CASH": 1.0}, tradable_symbols={"AAPL"}, decided_at=self.DECIDED,
            portfolio_volatility=0.1, portfolio_beta=1.0, max_pairwise_correlation=0.5,
            historical_cvar_95_5d=cvar,
        )

    def test_default_limit_is_the_normal_tail_at_the_volatility_limit(self):
        # 0.30 × √(5/252) × 2.0627 ≈ 0.0872
        self.assertAlmostEqual(PortfolioRiskPolicy().cvar_95_5d_limit, 0.0872, places=4)

    def test_tail_loss_beyond_the_limit_is_rejected(self):
        self.assertTrue(self._evaluate(cvar=0.05).is_approved)
        rejected = self._evaluate(cvar=0.12)
        self.assertFalse(rejected.is_approved)
        self.assertTrue(any("CVaR" in violation for violation in rejected.violations))

    def test_trading_stage_requires_the_tail_metric(self):
        rejected = self._evaluate(cvar=None, stage="live")
        self.assertFalse(rejected.is_approved)
        self.assertTrue(any("historical_cvar_95_5d" in violation for violation in rejected.violations))


class RiskGateTest(unittest.TestCase):
    def test_nonfinite_policy_cannot_disable_age_or_beta_limits(self):
        for field in ("max_proposal_age_hours", "max_abs_beta"):
            for value in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    PortfolioRiskPolicy(**{field: value})

    def test_caps_symbol_and_preserves_cash_and_total(self):
        gate = DeterministicRiskGate(PortfolioRiskPolicy(
            max_symbol_weight=0.10, max_turnover=1.0, min_cash_weight=0.05,
        ))
        result = gate.evaluate(
            proposal({"AAPL": 0.60, "CASH": 0.40}),
            current_weights={"CASH": 1.0},
            tradable_symbols={"AAPL"},
            decided_at=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
        )
        self.assertTrue(result.is_approved)
        self.assertAlmostEqual(result.approved_weights["AAPL"], 0.10)
        self.assertAlmostEqual(result.approved_weights["CASH"], 0.90)
        self.assertTrue(result.adjustments)
        self.assertAlmostEqual(result.metrics["concentration_hhi"], 0.01)
        self.assertAlmostEqual(result.metrics["turnover"], 0.10)
        self.assertIn("portfolio_volatility", result.to_dict()["metrics"])

    def test_rejects_unknown_and_stale_proposal(self):
        gate = DeterministicRiskGate(PortfolioRiskPolicy(max_proposal_age_hours=1))
        result = gate.evaluate(
            proposal({"FAKE": 0.05, "CASH": 0.95}, "2026-08-20T00:00:00+00:00"),
            current_weights={"CASH": 1.0}, tradable_symbols={"AAPL"},
            decided_at=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
        )
        self.assertFalse(result.is_approved)
        self.assertIsNone(result.approved_weights)
        self.assertEqual(len(result.violations), 2)

    def test_turnover_is_scaled_toward_current_portfolio(self):
        gate = DeterministicRiskGate(PortfolioRiskPolicy(
            max_symbol_weight=1.0, max_turnover=0.10, min_cash_weight=0.0,
        ))
        result = gate.evaluate(
            proposal({"AAPL": 1.0, "CASH": 0.0}),
            current_weights={"CASH": 1.0}, tradable_symbols={"AAPL"},
            decided_at=datetime(2026, 8, 21, 12, tzinfo=timezone.utc),
        )
        self.assertTrue(result.is_approved)
        self.assertAlmostEqual(
            portfolio_turnover({"CASH": 1.0}, result.approved_weights), 0.10
        )

def _exits_proposal(weights: dict[str, float], forced_exits: list[str]):
    return PortfolioProposal.create(
        run_id="run-1", source_type="optimizer", source_version="opt-v1",
        stage="shadow", as_of_at="2026-08-21T11:00:00+00:00", weights=weights,
        confidence=0.8, reasoning=("test",), metadata={"forced_exits": forced_exits},
    )


class MandatoryTurnoverTest(unittest.TestCase):
    decided_at = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)

    def test_turnover_scaling_does_not_revive_an_exit(self):
        gate = DeterministicRiskGate(PortfolioRiskPolicy(
            max_symbol_weight=0.5, max_turnover=0.10, min_cash_weight=0.0,
        ))
        result = gate.evaluate(
            _exits_proposal({"MSFT": 0.30, "CASH": 0.70}, ["AAPL"]),
            current_weights={"AAPL": 0.30, "CASH": 0.70},
            tradable_symbols={"AAPL", "MSFT"}, decided_at=self.decided_at,
        )
        self.assertTrue(result.is_approved, result.violations)
        self.assertEqual(result.approved_weights.get("AAPL", 0.0), 0.0)
        self.assertAlmostEqual(result.approved_weights["MSFT"], 0.10)
        self.assertAlmostEqual(result.metrics["mandatory_turnover"], 0.30)
        self.assertAlmostEqual(result.metrics["discretionary_turnover"], 0.10)

    def test_turnover_scaling_does_not_revive_a_symbol_cap_excess(self):
        gate = DeterministicRiskGate(PortfolioRiskPolicy(
            max_symbol_weight=0.10, max_turnover=0.05, min_cash_weight=0.05,
        ))
        result = gate.evaluate(
            _exits_proposal({"AAPL": 0.40, "MSFT": 0.20, "CASH": 0.40}, []),
            current_weights={"AAPL": 0.40, "CASH": 0.60},
            tradable_symbols={"AAPL", "MSFT"}, decided_at=self.decided_at,
        )
        self.assertTrue(result.is_approved, result.violations)
        self.assertLessEqual(result.approved_weights["AAPL"], 0.10 + 1e-9)
        self.assertLessEqual(result.approved_weights["MSFT"], 0.10 + 1e-9)

    def test_rejects_a_proposal_that_ignored_an_exit(self):
        gate = DeterministicRiskGate(PortfolioRiskPolicy(max_turnover=1.0))
        result = gate.evaluate(
            _exits_proposal({"AAPL": 0.05, "CASH": 0.95}, ["AAPL"]),
            current_weights={"AAPL": 0.05, "CASH": 0.95},
            tradable_symbols={"AAPL"}, decided_at=self.decided_at,
        )
        self.assertFalse(result.is_approved)
        self.assertTrue(any("forced exit kept" in item for item in result.violations))


if __name__ == "__main__":
    unittest.main()


class ConcentrationLimitReachabilityTest(unittest.TestCase):
    """HHI 한도가 종목 상한과 같은 스케일에서 골라졌는지 고정한다(감사 TR2-01).

    HHI = Σw² ≤ max(w)·Σw ≤ max_symbol_weight × (1 − min_cash_weight)다.
    기본 정책은 상한 0.095인데 한도는 0.15여서 그 검사는 어떤 입력에서도 발동하지 않는다.
    값을 임의로 바꾸지 않고, **그 사실이 코드와 원장에 드러나게** 한다 — 세 값 중
    하나를 고치는 사람은 이 테스트로 관계를 보게 된다.
    """

    def test_reachable_bound_follows_the_symbol_cap_and_cash_floor(self):
        policy = PortfolioRiskPolicy()
        self.assertAlmostEqual(policy.reachable_concentration_hhi, 0.095)
        self.assertGreater(policy.max_concentration_hhi, policy.reachable_concentration_hhi)
        self.assertFalse(policy.concentration_hhi_limit_binds)

    def test_a_limit_below_the_reachable_bound_binds(self):
        policy = PortfolioRiskPolicy(max_concentration_hhi=0.08)
        self.assertTrue(policy.concentration_hhi_limit_binds)

    def test_the_maximally_concentrated_portfolio_stays_under_the_bound(self):
        """상한을 꽉 채운 입력의 HHI가 유도한 상한을 넘지 않는다 — 부등식 자체의 검증."""
        policy = PortfolioRiskPolicy()
        count = int(round((1.0 - policy.min_cash_weight) / policy.max_symbol_weight))
        weights = {f"S{index}": policy.max_symbol_weight for index in range(count)}
        hhi = sum(weight * weight for weight in weights.values())
        self.assertLessEqual(hhi, policy.reachable_concentration_hhi + 1e-12)
        self.assertLess(hhi, policy.max_concentration_hhi)


class UnmappedSectorWeightTest(unittest.TestCase):
    """섹터 지도를 받았는데 분류가 없는 종목은 합계에서 빠져 한도가 조용히 통과했다(감사 TR2-07).

    분류 없는 비중이 섹터 상한을 넘으면 그 상한을 지켰다고 말할 수 없다 — 그 종목들이
    모두 같은 섹터일 수 있다. 새 임계를 만들지 않고 기존 상한으로 판정한다.
    """

    DECIDED = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)

    def _evaluate(self, sector_by_symbol):
        gate = DeterministicRiskGate(PortfolioRiskPolicy(max_symbol_weight=0.20, min_cash_weight=0.0))
        weights = {"AAA": 0.2, "BBB": 0.2, "CCC": 0.2, "CASH": 0.4}
        return gate.evaluate(
            proposal(weights), current_weights=weights,
            tradable_symbols={"AAA", "BBB", "CCC"},
            sector_by_symbol=sector_by_symbol, decided_at=self.DECIDED,
        )

    def test_unmapped_weight_over_the_sector_cap_is_a_violation(self):
        result = self._evaluate({"AAA": "Manufacturing"})
        self.assertFalse(result.is_approved)
        self.assertTrue(any("unmapped-sector weight" in v for v in result.violations))
        self.assertEqual(result.metrics["unmapped_sector_symbols"], ["BBB", "CCC"])
        self.assertAlmostEqual(result.metrics["unmapped_sector_weight"], 0.4)

    def test_a_fully_mapped_portfolio_has_no_unmapped_weight(self):
        result = self._evaluate({"AAA": "A", "BBB": "B", "CCC": "C"})
        self.assertEqual(result.metrics["unmapped_sector_symbols"], [])
        self.assertAlmostEqual(result.metrics["unmapped_sector_weight"], 0.0)

    def test_not_supplying_a_map_at_all_is_left_to_require_sector_map(self):
        """지도를 안 넘긴 호출은 이 검사의 대상이 아니다 — 정책 레버가 따로 있다."""
        result = self._evaluate(None)
        self.assertFalse(any("unmapped-sector weight" in v for v in result.violations))
