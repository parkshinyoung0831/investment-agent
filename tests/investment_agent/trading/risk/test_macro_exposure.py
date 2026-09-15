"""거시 노출 규칙: 신호 등급·노출 상한·전날까지 관측·오래된 값 무시·조이기만."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from investment_agent.trading.risk.gate import PortfolioRiskPolicy
from investment_agent.trading.risk.macro_exposure import assess_macro_exposure, tighten_for_macro

AS_OF = datetime(2026, 9, 15, 21, tzinfo=timezone.utc)


def _flat(value: float, *, days: int = 100, end_offset: int = 1) -> list[tuple[date, float]]:
    end = AS_OF.date() - timedelta(days=end_offset)
    return [(end - timedelta(days=offset), value) for offset in range(days)]


def _calm(**overrides):
    histories = {"HY_SPREAD": _flat(3.2), "VIX": _flat(15.0), "BREADTH_200DMA": _flat(60.0)}
    histories.update(overrides)
    return histories


class AssessTest(unittest.TestCase):
    def test_calm_markets_do_not_cap_exposure(self):
        state = assess_macro_exposure(_calm(), as_of_at=AS_OF)
        self.assertEqual(state.max_equity_exposure, 1.0)
        self.assertEqual((state.stress, state.caution, state.unavailable), ((), (), ()))

    def test_caution_only_caps_at_ninety_percent(self):
        state = assess_macro_exposure(_calm(VIX=_flat(27.0)), as_of_at=AS_OF)
        self.assertEqual(state.caution, ("volatility",))
        self.assertEqual(state.max_equity_exposure, 0.90)

    def test_one_and_two_stress_signals(self):
        one = assess_macro_exposure(_calm(VIX=_flat(35.0)), as_of_at=AS_OF)
        self.assertEqual(one.max_equity_exposure, 0.75)
        two = assess_macro_exposure(_calm(VIX=_flat(35.0), BREADTH_200DMA=_flat(15.0)), as_of_at=AS_OF)
        self.assertEqual(two.max_equity_exposure, 0.55)

    def test_rapid_credit_widening_is_stress_even_below_the_level_threshold(self):
        end = AS_OF.date() - timedelta(days=1)
        rising = [(end - timedelta(days=offset), 3.0 if offset > 30 else 4.6) for offset in range(100)]
        state = assess_macro_exposure(_calm(HY_SPREAD=rising), as_of_at=AS_OF)
        self.assertIn("credit_spread_widening", state.stress)
        self.assertIn("credit_spread_level", state.caution)

    def test_same_day_observation_is_not_used(self):
        today_spike = _flat(15.0) + [(AS_OF.date(), 45.0)]
        state = assess_macro_exposure(_calm(VIX=today_spike), as_of_at=AS_OF)
        self.assertEqual(state.max_equity_exposure, 1.0)

    def test_stale_or_missing_series_neither_tighten_nor_fail(self):
        state = assess_macro_exposure({"HY_SPREAD": _flat(9.0, end_offset=20), "VIX": _flat(15.0)}, as_of_at=AS_OF)
        self.assertEqual(state.max_equity_exposure, 1.0)
        self.assertEqual(set(state.unavailable), {"HY_SPREAD", "BREADTH_200DMA"})


class TightenTest(unittest.TestCase):
    def test_cap_becomes_minimum_cash_and_never_loosens(self):
        base = PortfolioRiskPolicy()
        stressed = assess_macro_exposure(_calm(VIX=_flat(35.0)), as_of_at=AS_OF)
        tightened = tighten_for_macro(base, stressed)
        self.assertAlmostEqual(tightened.min_cash_weight, 0.25)
        self.assertNotEqual(tightened.key, base.key)
        from dataclasses import replace
        already_safe = replace(base, min_cash_weight=0.5)
        self.assertEqual(tighten_for_macro(already_safe, stressed), already_safe)
        self.assertEqual(tighten_for_macro(base, None), base)


class RiskPolicyForTest(unittest.TestCase):
    def test_construction_paths_share_regime_and_macro_tightening(self):
        from unittest import mock
        from investment_agent.trading.portfolio import construct

        class Repository:
            def macro_histories(self, series_ids, *, as_of_at, lookback_days=120):
                return _calm(VIX=_flat(35.0))

        with mock.patch.object(construct, "_market_regime", return_value=None):
            policy, metadata = construct.risk_policy_for(Repository(), as_of_at=AS_OF, stage="shadow")
        self.assertAlmostEqual(policy.min_cash_weight, 0.25)
        self.assertEqual(metadata["macro_exposure"]["stress"], ["volatility"])

    def test_macro_reader_failure_does_not_stop_the_decision(self):
        from unittest import mock
        from investment_agent.trading.portfolio import construct

        class Repository:
            def macro_histories(self, series_ids, *, as_of_at, lookback_days=120):
                raise TimeoutError("macro down")

        with mock.patch.object(construct, "_market_regime", return_value=None):
            policy, metadata = construct.risk_policy_for(Repository(), as_of_at=AS_OF, stage="live")
        self.assertEqual(policy, PortfolioRiskPolicy())
        self.assertIsNone(metadata["macro_exposure"])

    def test_every_construction_path_uses_the_shared_policy(self):
        import ast
        import inspect
        from investment_agent.trading.portfolio import construct, factor_portfolio

        for function in (construct.evaluate_portfolio, construct.evaluate_target_weights,
                         factor_portfolio.evaluate_factor_portfolio):
            source = ast.unparse(ast.parse(inspect.getsource(function)))
            self.assertIn("risk_policy_for(", source, function.__name__)
            self.assertNotIn("tighten_for_regime(", source, function.__name__)


if __name__ == "__main__":
    unittest.main()
