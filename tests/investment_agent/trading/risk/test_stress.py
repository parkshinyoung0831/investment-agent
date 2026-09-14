"""스트레스 시나리오가 테마 쏠림을 잡고, RiskGate가 노출을 정확히 한도까지 줄이는지."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.contracts import PortfolioProposal
from investment_agent.trading.risk.gate import DeterministicRiskGate, PortfolioRiskPolicy
from investment_agent.trading.risk.stress import STRESS_SCENARIOS, scenario_losses, scenario_sensitivities

DECIDED = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)


def _rows(returns: list[float]) -> list[dict]:
    value, rows = 100.0, [{"trade_date": date(2026, 1, 1).isoformat(), "close": 100.0}]
    for offset, daily in enumerate(returns, start=1):
        value *= 1.0 + daily
        rows.append({"trade_date": (date(2026, 1, 1) + timedelta(days=offset)).isoformat(), "close": value})
    return rows


def _neutral_sensitivities(symbols, **overrides):
    table = {scenario.name: {symbol: 0.0 for symbol in symbols} for scenario in STRESS_SCENARIOS}
    for name, betas in overrides.items():
        table[name].update(betas)
    return table


class ScenarioMathTest(unittest.TestCase):
    def test_loss_is_weight_times_sensitivity_times_shock(self):
        sensitivities = _neutral_sensitivities(("AAA", "BBB"), tech_down_20={"AAA": 1.5, "BBB": 0.5})
        losses = scenario_losses({"AAA": 0.4, "BBB": 0.2, "CASH": 0.4}, sensitivities)
        self.assertAlmostEqual(losses["tech_down_20"], (0.4 * 1.5 + 0.2 * 0.5) * 0.20)
        self.assertEqual(losses["market_down_10"], 0.0)

    def test_commodity_spike_hurts_negative_sensitivity(self):
        sensitivities = _neutral_sensitivities(("AIR",), commodity_spike_20={"AIR": -0.8})
        self.assertAlmostEqual(scenario_losses({"AIR": 0.5, "CASH": 0.5}, sensitivities)["commodity_spike_20"], 0.08)

    def test_missing_sensitivity_for_a_holding_fails_closed(self):
        with self.assertRaises(ContractError):
            scenario_losses({"AAA": 0.5, "CASH": 0.5}, _neutral_sensitivities(("BBB",)))

    def test_sensitivities_follow_the_proxy_relationship_and_require_every_proxy(self):
        base = [0.001 + (index % 7 - 3) * 0.003 for index in range(90)]
        rows = {scenario.proxy: _rows(base) for scenario in STRESS_SCENARIOS}
        rows["AAA"] = _rows([2.0 * value for value in base])
        table = scenario_sensitivities(rows, symbols=("AAA",))
        self.assertAlmostEqual(table["tech_down_20"]["AAA"], 2.0, places=6)
        rows.pop("XLK")
        with self.assertRaisesRegex(ContractError, "XLK"):
            scenario_sensitivities(rows, symbols=("AAA",))


class GateStressLimitTest(unittest.TestCase):
    def _evaluate(self, weights, sensitivities, *, stage="shadow"):
        proposal = PortfolioProposal.create(
            run_id="run-1", source_type="llm", source_version="ta-v1", stage=stage,
            as_of_at="2026-08-21T11:00:00+00:00", weights=weights, confidence=0.8, reasoning=("test",),
        )
        policy = PortfolioRiskPolicy(max_turnover=1.0, max_concentration_hhi=1.0)
        return DeterministicRiskGate(policy).evaluate(
            proposal, current_weights={"CASH": 1.0}, tradable_symbols=set(weights) - {"CASH"},
            decided_at=DECIDED, portfolio_volatility=0.1, portfolio_beta=1.0, max_pairwise_correlation=0.5,
            historical_cvar_95_5d=0.03, stress_sensitivities=sensitivities,
        )

    def test_theme_concentration_is_scaled_exactly_to_the_limit(self):
        """시장 베타 1인 포트폴리오도 기술주에 몰려 있으면 노출을 줄인다."""
        symbols = [f"T{index}" for index in range(9)]
        weights = {symbol: 0.1 for symbol in symbols}
        weights["CASH"] = 0.1
        sensitivities = _neutral_sensitivities(symbols, tech_down_20={symbol: 1.2 for symbol in symbols})
        decision = self._evaluate(weights, sensitivities)
        self.assertTrue(decision.is_approved)
        limit = PortfolioRiskPolicy().stress_loss_limit
        self.assertAlmostEqual(decision.metrics["stress_losses"]["tech_down_20"], limit)
        self.assertLess(decision.approved_weights["T0"], 0.1)
        self.assertTrue(any("tech_down_20" in item for item in decision.adjustments))

    def test_diversified_book_is_left_alone(self):
        weights = {"AAA": 0.1, "BBB": 0.1, "CASH": 0.8}
        sensitivities = _neutral_sensitivities(("AAA", "BBB"), market_down_10={"AAA": 1.0, "BBB": 1.0})
        decision = self._evaluate(weights, sensitivities)
        self.assertAlmostEqual(decision.approved_weights["AAA"], 0.1)

    def test_trading_stage_without_stress_inputs_is_rejected(self):
        decision = self._evaluate({"AAA": 0.05, "CASH": 0.95}, None, stage="live")
        self.assertFalse(decision.is_approved)
        self.assertTrue(any("stress_sensitivities" in item for item in decision.violations))


if __name__ == "__main__":
    unittest.main()
