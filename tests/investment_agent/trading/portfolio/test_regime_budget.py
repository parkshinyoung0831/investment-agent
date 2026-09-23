from __future__ import annotations

import unittest
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from investment_agent.trading.decision.regime import build_market_regime
from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.contracts import PortfolioProposal
from investment_agent.trading.portfolio.optimizer import ExpectedReturnSignal, OptimizerPolicy, RiskAwareOptimizer
from investment_agent.trading.risk.gate import DeterministicRiskGate, PortfolioRiskPolicy, portfolio_turnover
from investment_agent.trading.risk.regime_budget import (
    REGIME_LIMITS,
    regime_from_benchmark_prices,
    tighten_for_regime,
)

AS_OF = datetime(2026, 9, 14, 20, tzinfo=timezone.utc)


def _regime(state_inputs: dict):
    return build_market_regime(AS_OF.isoformat(), **state_inputs)


def _prices(returns: list[float]) -> list[dict]:
    value, rows = 100.0, []
    start = AS_OF.date() - timedelta(days=len(returns))
    for offset, daily in enumerate(returns):
        value *= 1.0 + daily
        rows.append({"trade_date": (start + timedelta(days=offset)).isoformat(), "close": value})
    return rows


class RegimeBudgetTest(unittest.TestCase):
    def test_stale_benchmark_does_not_reopen_normal_risk_budget(self):
        with self.assertRaisesRegex(ContractError, "stale benchmark"):
            regime_from_benchmark_prices(_prices([0.001] * 120), as_of_at=AS_OF + timedelta(days=30))

    def test_unfinalized_same_day_bar_is_not_a_close(self):
        rows = _prices([0.001] * 120)
        baseline = regime_from_benchmark_prices(rows, as_of_at=AS_OF)
        rows.append({"trade_date": AS_OF.date().isoformat(), "close": 1.0})
        self.assertEqual(regime_from_benchmark_prices(rows, as_of_at=AS_OF), baseline)

    def test_conflicting_or_nonfinite_benchmark_rows_are_not_silently_dropped(self):
        rows = _prices([0.001] * 120)
        for close in (float("nan"), float("inf"), -1.0, 99.0):
            with self.subTest(close=close), self.assertRaises(ContractError):
                regime_from_benchmark_prices(rows + [{**rows[-1], "close": close}], as_of_at=AS_OF)

    def test_weekend_holiday_gap_is_accepted(self):
        # 금요일 확정 봉은 월요일 휴장 다음 화요일 장전에도 사용할 수 있다.
        rows = [row for row in _prices([0.001] * 120) if row["trade_date"] <= "2026-09-11"]
        regime = regime_from_benchmark_prices(rows, as_of_at="2026-09-15T13:00:00+00:00")
        self.assertIn(regime.risk_state, {"RISK_ON", "NORMAL"})

    def test_no_regime_ever_loosens_the_base_policy(self):
        base = PortfolioRiskPolicy()
        for inputs in ({"benchmark_return": 0.05, "volatility": 0.10}, {}, {"volatility": 0.35}, {"drawdown": 0.3}):
            regime = _regime(inputs)
            with self.subTest(state=regime.risk_state):
                policy = tighten_for_regime(base, regime)
                self.assertLessEqual(policy.max_symbol_weight, base.max_symbol_weight)
                self.assertLessEqual(policy.max_sector_weight, base.max_sector_weight)
                self.assertGreaterEqual(policy.min_cash_weight, base.min_cash_weight)
                self.assertLessEqual(policy.allow_risk_increase, base.allow_risk_increase)
        self.assertEqual(set(REGIME_LIMITS), {"RISK_ON", "NORMAL", "RISK_OFF", "CRISIS"})

    def test_normal_market_keeps_the_exact_base_policy(self):
        base = PortfolioRiskPolicy()
        self.assertEqual(asdict(tighten_for_regime(base, _regime({}))), asdict(base))
        self.assertEqual(tighten_for_regime(base, None), base)

    def test_crisis_blocks_new_risk_and_records_a_distinct_policy_key(self):
        policy = tighten_for_regime(PortfolioRiskPolicy(), _regime({"drawdown": 0.25}))
        self.assertFalse(policy.allow_risk_increase)
        self.assertAlmostEqual(policy.min_cash_weight, 0.40)
        self.assertAlmostEqual(policy.max_symbol_weight, 0.05)
        self.assertEqual(policy.key, "portfolio-risk:crisis")

    def test_regime_is_derived_from_benchmark_history_only_up_to_the_decision(self):
        calm = regime_from_benchmark_prices(_prices([0.002] * 120), as_of_at=AS_OF)
        self.assertIn(calm.risk_state, {"RISK_ON", "NORMAL"})
        crash = regime_from_benchmark_prices(_prices([0.001] * 100 + [-0.03] * 10), as_of_at=AS_OF)
        self.assertEqual(crash.risk_state, "CRISIS")
        future = _prices([0.002] * 120) + [{"trade_date": (AS_OF.date() + timedelta(days=3)).isoformat(), "close": 1.0}]
        self.assertEqual(regime_from_benchmark_prices(future, as_of_at=AS_OF).risk_state, calm.risk_state)


class NoIncreaseAndCashFloorTest(unittest.TestCase):
    def test_gate_blocks_increases_and_keeps_the_cash_floor_through_turnover_scaling(self):
        policy = PortfolioRiskPolicy(
            max_symbol_weight=0.5, max_turnover=0.10, min_cash_weight=0.40, allow_risk_increase=False,
            max_concentration_hhi=1.0,
        )
        proposal = PortfolioProposal.create(
            run_id="r", source_type="optimizer", source_version="v", stage="shadow",
            as_of_at=AS_OF.isoformat(), weights={"AAPL": 0.30, "MSFT": 0.50, "CASH": 0.20},
            confidence=0.5, reasoning=("t",),
        )
        result = DeterministicRiskGate(policy).evaluate(
            proposal, current_weights={"AAPL": 0.45, "MSFT": 0.45, "CASH": 0.10},
            tradable_symbols={"AAPL", "MSFT"}, decided_at=AS_OF,
        )
        self.assertTrue(result.is_approved, result.violations)
        weights = result.approved_weights
        self.assertLessEqual(weights["MSFT"], 0.45 + 1e-9)
        self.assertGreaterEqual(weights["CASH"], 0.40 - 1e-9)

    def test_gate_clamps_an_increase_that_no_other_limit_would_touch(self):
        policy = PortfolioRiskPolicy(
            max_symbol_weight=0.6, max_turnover=1.0, min_cash_weight=0.05, allow_risk_increase=False,
            max_concentration_hhi=1.0,
        )
        proposal = PortfolioProposal.create(
            run_id="r", source_type="optimizer", source_version="v", stage="shadow",
            as_of_at=AS_OF.isoformat(), weights={"AAPL": 0.05, "MSFT": 0.55, "CASH": 0.40},
            confidence=0.5, reasoning=("t",),
        )
        result = DeterministicRiskGate(policy).evaluate(
            proposal, current_weights={"AAPL": 0.30, "MSFT": 0.30, "CASH": 0.40},
            tradable_symbols={"AAPL", "MSFT"}, decided_at=AS_OF,
        )
        self.assertTrue(result.is_approved, result.violations)
        self.assertAlmostEqual(result.approved_weights["MSFT"], 0.30)
        self.assertTrue(any("increase blocked" in item for item in result.adjustments))

    def test_optimizer_raises_cash_to_the_floor_even_beyond_the_turnover_budget(self):
        policy = OptimizerPolicy(
            max_symbol_weight=0.5, max_turnover=0.25, min_cash_weight=0.40, allow_increases=False,
            turnover_penalty=0.0, risk_aversion=0.1,
        )
        signals = (
            ExpectedReturnSignal("AAPL", 0.05, 1.0, 0.1, 5, "t", AS_OF.isoformat(), "v"),
            ExpectedReturnSignal("MSFT", 0.08, 1.0, 0.1, 5, "t", AS_OF.isoformat(), "v"),
        )
        result = RiskAwareOptimizer(policy).optimize(
            signals, current_weights={"AAPL": 0.50, "MSFT": 0.45, "CASH": 0.05},
        )
        self.assertGreaterEqual(result.weights["CASH"], 0.40 - 1e-6)
        self.assertLessEqual(result.weights["MSFT"], 0.45 + 1e-6)
        self.assertLessEqual(result.weights["AAPL"], 0.50 + 1e-6)
        self.assertGreater(portfolio_turnover({"AAPL": 0.5, "MSFT": 0.45, "CASH": 0.05}, result.weights), 0.25)


if __name__ == "__main__":
    unittest.main()


class ContinuousExposureTest(unittest.TestCase):
    """계단(현금 0→15→40%) 대신 변동성·낙폭의 연속 함수. 한도를 푸는 방향으로는 절대 가지 않는다."""

    def _policy(self):
        from investment_agent.trading.risk.regime_budget import MarketRiskPolicy

        return MarketRiskPolicy(continuous_exposure=True)

    def test_calm_markets_keep_full_exposure(self):
        from investment_agent.trading.risk.regime_budget import continuous_exposure

        self.assertEqual(1.0, continuous_exposure(0.12, 0.02, policy=self._policy()))

    def test_drawdown_interpolates_between_the_old_step_boundaries(self):
        from investment_agent.trading.risk.regime_budget import continuous_exposure

        policy = self._policy()
        self.assertAlmostEqual(0.85, continuous_exposure(None, 0.08, policy=policy))
        self.assertAlmostEqual(0.775, continuous_exposure(None, 0.14, policy=policy))
        self.assertAlmostEqual(0.60, continuous_exposure(None, 0.25, policy=policy))

    def test_volatility_scales_down_to_the_floor(self):
        from investment_agent.trading.risk.regime_budget import continuous_exposure

        policy = self._policy()
        self.assertAlmostEqual(0.191 / 0.30, continuous_exposure(0.30, None, policy=policy))
        self.assertAlmostEqual(0.60, continuous_exposure(0.90, None, policy=policy))

    def test_the_result_is_never_looser_than_the_base_policy_and_the_key_carries_the_value(self):
        from investment_agent.trading.decision.regime import build_market_regime
        from investment_agent.trading.risk.gate import PortfolioRiskPolicy
        from investment_agent.trading.risk.regime_budget import tighten_for_regime

        base = PortfolioRiskPolicy()
        calm = build_market_regime("2026-01-05T21:00:00+00:00", benchmark_return=0.01, volatility=0.10, drawdown=0.01)
        stressed = build_market_regime("2026-01-05T21:00:00+00:00", benchmark_return=-0.05, volatility=0.30,
                                       drawdown=0.14)
        self.assertEqual(base.min_cash_weight, tighten_for_regime(base, calm, self._policy()).min_cash_weight)
        tightened = tighten_for_regime(base, stressed, self._policy())
        self.assertAlmostEqual(1 - 0.191 / 0.30, tightened.min_cash_weight)
        self.assertIn("cash0.363", tightened.key)
