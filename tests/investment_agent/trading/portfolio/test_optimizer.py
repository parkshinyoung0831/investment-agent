from __future__ import annotations

import unittest

from investment_agent.trading.portfolio.optimizer import (
    CONSTRAINT_BLOCK_INCREASE,
    CONSTRAINT_FORCE_EXIT,
    ExpectedReturnSignal,
    OptimizerPolicy,
    RiskAwareOptimizer,
)
from investment_agent.trading.portfolio.market_risk import TradingCostInputs, estimate_trading_costs


class OptimizerTest(unittest.TestCase):
    def test_beta_constraint_inputs_change_audit_hash(self):
        optimizer = RiskAwareOptimizer(OptimizerPolicy(max_portfolio_beta=0.2))
        inputs = dict(signals=(_signal("AAPL", 0.04),), current_weights={"CASH": 1.0})
        first = optimizer.optimize(**inputs, betas={"AAPL": 1.0})
        repeated = optimizer.optimize(**inputs, betas={"aapl": 1.0})
        changed = optimizer.optimize(**inputs, betas={"AAPL": 2.0})
        self.assertEqual(first.input_hash, repeated.input_hash)
        self.assertNotEqual(first.input_hash, changed.input_hash)

    def test_correlated_assets_receive_a_larger_variance_penalty(self):
        signals = (
            ExpectedReturnSignal("AAPL", 0.04, 1.0, 0.1, 5, "test", "2026-08-20T22:00:00+00:00", "v1"),
            ExpectedReturnSignal("MSFT", 0.04, 1.0, 0.1, 5, "test", "2026-08-20T22:00:00+00:00", "v1"),
        )
        policy = OptimizerPolicy(risk_aversion=100.0, max_turnover=1.0, turnover_penalty=0.0)
        optimizer = RiskAwareOptimizer(policy)
        independent = optimizer.optimize(
            signals,
            current_weights={"CASH": 1.0},
            covariance=((0.01, 0.0), (0.0, 0.01)),
        )
        correlated = optimizer.optimize(
            signals,
            current_weights={"CASH": 1.0},
            covariance=((0.01, 0.009), (0.009, 0.01)),
        )
        self.assertLess(
            correlated.weights["AAPL"] + correlated.weights["MSFT"],
            independent.weights["AAPL"] + independent.weights["MSFT"],
        )
        self.assertGreater(correlated.estimated_variance, 0.0)
        self.assertAlmostEqual(
            correlated.objective_value,
            correlated.expected_return_component - correlated.risk_penalty - correlated.turnover_penalty,
        )

    def test_trade_words_are_not_an_optimizer_input(self):
        """사고팔기 행동은 결과 비중에서 파생된다 — 신호 계약에 그 자리가 없다."""
        fields = set(ExpectedReturnSignal.__dataclass_fields__)
        self.assertNotIn("action", fields)
        self.assertIn("constraint", fields)
        with self.assertRaises(ValueError):
            ExpectedReturnSignal("AAPL", 0.01, 1.0, 0.1, 5, "t", "2026-08-20T22:00:00+00:00", "v", constraint="buy")


_AT = "2026-08-20T22:00:00+00:00"


def _signal(symbol: str, expected: float, constraint: str | None = None) -> ExpectedReturnSignal:
    return ExpectedReturnSignal(symbol, expected, 1.0, 0.1, 5, "test", _AT, "v1", constraint=constraint)


class BenchmarkRelativeRiskTest(unittest.TestCase):
    """기대수익이 SPY 대비 초과수익이면 위험도 SPY 대비로 재야 한다(설계 §9.2)."""

    # 20거래일 기준. 두 종목 모두 연 변동성 약 25%, SPY와 상관 약 0.7.
    _COV = [[0.0050, 0.0020], [0.0020, 0.0050]]
    _BENCH = {"AAPL": 0.0023, "MSFT": 0.0023}

    def _invested(self, **extra) -> float:
        policy = OptimizerPolicy(max_symbol_weight=0.5, max_turnover=1.0, turnover_penalty=0.0)
        result = RiskAwareOptimizer(policy).optimize(
            (_signal("AAPL", 0.003), _signal("MSFT", 0.003)), current_weights={"CASH": 1.0},
            covariance=self._COV, **extra,
        )
        return 1.0 - result.weights["CASH"]

    def test_absolute_variance_leaves_most_of_the_book_in_cash(self):
        """작은 초과수익과 시장 위험 전체를 맞바꾸면 현금이 이긴다 — 고치려는 편향 그 자체다."""
        self.assertLess(self._invested(), 0.2)

    def test_benchmark_relative_risk_holds_the_market_like_exposure(self):
        """최적은 SPY 노출을 복제하는 비중이다. 두 종목이 SPY보다 변동성이 커서 그 비중은 E(0.95)보다 작다:
        대칭 1계 조건 w·(σ² + σ_ij) = E·c_b + α/(2λ) → w ≈ 0.355, 합 ≈ 0.71."""
        invested = self._invested(benchmark_covariance=self._BENCH)
        self.assertAlmostEqual(invested, 2 * (0.95 * 0.0023 + 0.003 / 10.0) / 0.007, places=3)
        self.assertGreater(invested, 3 * self._invested())

    def test_minimum_cash_still_binds(self):
        """더 강한 시장 공분산이면 한도(1 − 최소 현금)에 닿고 넘지 않는다."""
        invested = self._invested(benchmark_covariance={"AAPL": 0.0060, "MSFT": 0.0060})
        self.assertAlmostEqual(invested, 0.95, places=4)

    def test_missing_benchmark_covariance_is_refused(self):
        with self.assertRaises(Exception):
            self._invested(benchmark_covariance={"AAPL": 0.0023})

    def test_benchmark_inputs_change_the_audit_hash(self):
        policy = OptimizerPolicy(max_symbol_weight=0.5, max_turnover=1.0)
        optimizer = RiskAwareOptimizer(policy)
        inputs = dict(signals=(_signal("AAPL", 0.003), _signal("MSFT", 0.003)),
                      current_weights={"CASH": 1.0}, covariance=self._COV)
        self.assertNotEqual(optimizer.optimize(**inputs).input_hash,
                            optimizer.optimize(**inputs, benchmark_covariance=self._BENCH).input_hash)


class FixedHoldingCovarianceTest(unittest.TestCase):
    """움직일 수 없는 보유와 같은 방향으로 움직이는 종목은 더 담을수록 위험이 커진다(w'Σ_wf·f 항)."""

    def test_a_name_correlated_with_a_fixed_holding_gets_less_weight(self):
        policy = OptimizerPolicy(max_symbol_weight=0.5, max_turnover=1.0, turnover_penalty=0.0)
        cov = [[0.0050, 0.0010], [0.0010, 0.0050]]

        def weights(**extra):
            return RiskAwareOptimizer(policy).optimize(
                (_signal("AAPL", 0.004), _signal("MSFT", 0.004)),
                current_weights={"CASH": 0.8, "FIX": 0.2}, covariance=cov, fixed_weights={"FIX": 0.2}, **extra,
            ).weights

        without = weights()
        # FIX는 AAPL과 공분산 0.0045(거의 같은 종목), MSFT와는 0 — 보유 20%면 AAPL 쪽 항은 0.0009다.
        with_cross = weights(fixed_covariance={"AAPL": 0.2 * 0.0045, "MSFT": 0.0})
        self.assertAlmostEqual(without["AAPL"], without["MSFT"], places=6)
        self.assertLess(with_cross["AAPL"], without["AAPL"] - 0.01)
        self.assertAlmostEqual(with_cross["FIX"], 0.2)


class ConstraintTest(unittest.TestCase):
    def test_force_exit_is_full_liquidation_even_when_turnover_is_expensive(self):
        # 기대수익을 양수로 둬도(잘못된 입력) 청산 제약은 비중을 남기지 않는다.
        policy = OptimizerPolicy(turnover_penalty=1.0, max_turnover=1.0)
        result = RiskAwareOptimizer(policy).optimize(
            (_signal("AAPL", 0.05, CONSTRAINT_FORCE_EXIT), _signal("MSFT", 0.01)),
            current_weights={"AAPL": 0.08, "MSFT": 0.05, "CASH": 0.87},
        )
        self.assertEqual(result.weights.get("AAPL", 0.0), 0.0)

    def test_exits_larger_than_the_turnover_budget_stay_feasible(self):
        # 여섯 종목 60%를 한꺼번에 빼야 해도 25% 재량 turnover 한도가 청산을 막지 않는다.
        # (매도쪽 합만 따져도, 현금쪽 합만 따져도 0.25를 넘도록 잡았다.)
        symbols = ("AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN")
        policy = OptimizerPolicy(max_turnover=0.25)
        result = RiskAwareOptimizer(policy).optimize(
            tuple(_signal(symbol, -0.01, CONSTRAINT_FORCE_EXIT) for symbol in symbols),
            current_weights={**{symbol: 0.1 for symbol in symbols}, "CASH": 0.4},
        )
        for symbol in symbols:
            self.assertEqual(result.weights.get(symbol, 0.0), 0.0)
        self.assertAlmostEqual(result.weights["CASH"], 1.0)

    def test_exit_proceeds_do_not_widen_the_discretionary_buy_budget(self):
        policy = OptimizerPolicy(max_turnover=0.05, turnover_penalty=0.0, risk_aversion=0.1)
        result = RiskAwareOptimizer(policy).optimize(
            (_signal("AAPL", -0.01, CONSTRAINT_FORCE_EXIT), _signal("META", 0.10)),
            current_weights={"AAPL": 0.10, "CASH": 0.90},
        )
        self.assertEqual(result.weights.get("AAPL", 0.0), 0.0)
        self.assertLessEqual(result.weights["META"], 0.05 + 1e-6)

    def test_block_increase_never_adds_to_a_position(self):
        policy = OptimizerPolicy(max_turnover=1.0, turnover_penalty=0.0, risk_aversion=0.1)
        result = RiskAwareOptimizer(policy).optimize(
            (_signal("AAPL", 0.20, CONSTRAINT_BLOCK_INCREASE),),
            current_weights={"AAPL": 0.03, "CASH": 0.97},
        )
        self.assertLessEqual(result.weights["AAPL"], 0.03 + 1e-9)

    def test_capital_a_blocked_name_cannot_use_goes_to_other_candidates(self):
        # 사후에 잘라내기만 하면 막힌 종목 몫이 현금으로 놀고, 다른 후보가 받지 못한다.
        policy = OptimizerPolicy(
            max_turnover=1.0, turnover_penalty=0.0, risk_aversion=0.1,
            max_symbol_weight=0.10, min_cash_weight=0.85,
        )
        result = RiskAwareOptimizer(policy).optimize(
            (_signal("AAPL", 0.20, CONSTRAINT_BLOCK_INCREASE), _signal("MSFT", 0.05)),
            current_weights={"AAPL": 0.03, "CASH": 0.97},
        )
        self.assertLessEqual(result.weights["AAPL"], 0.03 + 1e-9)
        self.assertGreaterEqual(result.weights["MSFT"], 0.10 - 1e-6)

    def test_unconstrained_name_can_lose_to_a_better_candidate(self):
        # 기대수익이 양수여도 자리가 부족하면 0이 될 수 있어야 한다.
        policy = OptimizerPolicy(
            max_turnover=1.0, turnover_penalty=0.0, risk_aversion=0.1,
            max_symbol_weight=0.10, min_cash_weight=0.85,
        )
        result = RiskAwareOptimizer(policy).optimize(
            (_signal("NVDA", 0.05), _signal("AMZN", 0.001)),
            current_weights={"CASH": 1.0},
            covariance=((0.001, 0.0), (0.0, 0.001)),
        )
        self.assertGreater(result.weights["NVDA"], result.weights.get("AMZN", 0.0))
        self.assertLess(result.weights.get("AMZN", 0.0), 0.05)


class ExpectedReturnCapTest(unittest.TestCase):
    def test_forecast_beyond_one_horizon_sigma_is_capped_and_recorded(self):
        policy = OptimizerPolicy(max_turnover=1.0, turnover_penalty=0.0)
        cov = ((0.0025, 0.0), (0.0, 0.0025))  # 신호 기간 σ = 5%
        result = RiskAwareOptimizer(policy).optimize(
            (_signal("MU", 0.25, ), _signal("AAPL", 0.03, )),
            current_weights={"CASH": 1.0}, covariance=cov,
        )
        self.assertEqual(result.capped_expected_returns, {"MU": {"raw": 0.25, "capped": 0.05}})

    def test_capping_changes_the_allocation_of_an_outsized_forecast(self):
        cov = ((0.0025, 0.0), (0.0, 0.0025))
        signals = (_signal("MU", 0.25, ), _signal("AAPL", 0.05, ))
        loose = RiskAwareOptimizer(OptimizerPolicy(max_turnover=1.0, turnover_penalty=0.0, risk_aversion=20,
                                                   max_symbol_weight=1.0, min_cash_weight=0.0,
                                                   max_expected_return_sigma=None))
        capped = RiskAwareOptimizer(OptimizerPolicy(max_turnover=1.0, turnover_penalty=0.0, risk_aversion=20,
                                                    max_symbol_weight=1.0, min_cash_weight=0.0))
        free = loose.optimize(signals, current_weights={"CASH": 1.0}, covariance=cov)
        bounded = capped.optimize(signals, current_weights={"CASH": 1.0}, covariance=cov)
        self.assertGreater(free.weights["MU"], bounded.weights["MU"] + 0.1)
        self.assertAlmostEqual(bounded.weights["MU"], bounded.weights["AAPL"], places=4)

    def test_fallback_without_covariance_does_not_cap(self):
        result = RiskAwareOptimizer(OptimizerPolicy(max_turnover=1.0)).optimize(
            (_signal("MU", 0.25, ),), current_weights={"CASH": 1.0},
        )
        self.assertEqual(result.capped_expected_returns, {})


class TradeReasonTest(unittest.TestCase):
    def test_each_changed_position_gets_one_reason(self):
        from investment_agent.trading.system.target import trade_reasons

        signals = (
            _signal("OVER", 0.01), _signal("BAD", -0.02, CONSTRAINT_BLOCK_INCREASE),
            _signal("LOSER", 0.001), _signal("NEW", 0.04), _signal("GONE", -0.03, CONSTRAINT_FORCE_EXIT),
        )
        reasons = trade_reasons(
            signals,
            current_weights={"OVER": 0.15, "BAD": 0.08, "LOSER": 0.08, "GONE": 0.05, "CASH": 0.64},
            target_weights={"OVER": 0.10, "BAD": 0.04, "LOSER": 0.02, "NEW": 0.05, "CASH": 0.79},
            max_symbol_weight=0.10, min_cash_weight=0.05, capped_expected_returns={"NEW": {}},
        )
        self.assertEqual({symbol: row["code"] for symbol, row in reasons.items()}, {
            "OVER": "HARD_RISK_LIMIT", "BAD": "ALPHA_DECAY", "LOSER": "REBALANCE",
            "NEW": "ALPHA_OPPORTUNITY", "GONE": "THESIS_EXIT",
        })
        self.assertTrue(reasons["NEW"]["expected_return_capped"])


def _cost(symbol: str, *, adv: float, spread: float = 0.0001) -> TradingCostInputs:
    return TradingCostInputs(symbol, spread, adv)


class TradingCostTest(unittest.TestCase):
    policy = OptimizerPolicy(
        max_turnover=1.0, turnover_penalty=0.0, risk_aversion=5.0, max_symbol_weight=0.5, min_cash_weight=0.0,
    )

    def test_expensive_to_trade_names_get_less_capital_than_their_raw_alpha_suggests(self):
        signals = (_signal("LIQD", 0.020), _signal("THIN", 0.022))
        # 두 종목 모두 상한(0.5)에 닿지 않도록 분산을 잡아, 차이가 비용에서만 나오게 한다.
        cov = ((0.01, 0.0), (0.0, 0.01))
        costs = {"LIQD": _cost("LIQD", adv=5e9), "THIN": _cost("THIN", adv=2e6, spread=0.004)}
        free = RiskAwareOptimizer(self.policy).optimize(signals, current_weights={"CASH": 1.0}, covariance=cov)
        costly = RiskAwareOptimizer(self.policy).optimize(
            signals, current_weights={"CASH": 1.0}, covariance=cov,
            trading_costs=costs,
        )
        self.assertGreater(free.weights["THIN"], free.weights["LIQD"])
        self.assertLess(costly.weights.get("THIN", 0.0), costly.weights["LIQD"])
        self.assertGreater(costly.transaction_cost, 0.0)
        self.assertAlmostEqual(
            costly.objective_value,
            costly.expected_return_component - costly.risk_penalty
            - costly.turnover_penalty - costly.transaction_cost,
        )

    def test_cost_is_linear_half_spread_without_market_impact_or_adv_caps(self):
        """개인 계좌 규모라 거래대금 대비 주문 크기를 따지지 않는다. 비용은 반스프레드 × 거래 비중뿐이다."""
        policy = OptimizerPolicy(max_turnover=1.0, turnover_penalty=0.0, risk_aversion=0.01,
                                 max_symbol_weight=0.5, min_cash_weight=0.0)
        result = RiskAwareOptimizer(policy).optimize(
            (_signal("THIN", 0.10), _signal("OLD", -0.01, CONSTRAINT_FORCE_EXIT)),
            current_weights={"OLD": 0.40, "CASH": 0.60},
            covariance=((0.001, 0.0), (0.0, 0.001)),
            trading_costs={"THIN": _cost("THIN", adv=4_000.0, spread=0.001), "OLD": _cost("OLD", adv=1_000.0, spread=0.001)},
        )
        self.assertAlmostEqual(result.weights["THIN"], 0.5, places=5)
        self.assertEqual(result.weights.get("OLD", 0.0), 0.0)
        self.assertAlmostEqual(result.transaction_cost, 0.001 * (0.5 + 0.40), places=6)
        self.assertFalse(hasattr(policy, "impact_coefficient"))
        self.assertFalse(hasattr(policy, "max_adv_participation"))

    def test_partial_cost_inputs_are_rejected(self):
        with self.assertRaisesRegex(Exception, "trading cost inputs are missing"):
            RiskAwareOptimizer(self.policy).optimize(
                (_signal("AAPL", 0.01), _signal("MSFT", 0.01)),
                current_weights={"CASH": 1.0},
                trading_costs={"AAPL": _cost("AAPL", adv=1e9)},
            )


class TradingCostEstimateTest(unittest.TestCase):
    def rows(self, volume: int, n: int = 70):
        from datetime import date, timedelta
        start = date(2026, 1, 1)
        return [
            {"trade_date": (start + timedelta(days=i)).isoformat(), "close": 100.0 + (i % 3), "volume": volume}
            for i in range(n)
        ]

    def test_buckets_half_spread_by_dollar_volume(self):
        costs = estimate_trading_costs(
            {"BIG": self.rows(20_000_000), "MID": self.rows(2_000_000), "TINY": self.rows(10_000)},
            symbols=("BIG", "MID", "TINY"),
        )
        self.assertLess(costs["BIG"].half_spread, costs["MID"].half_spread)
        self.assertLess(costs["MID"].half_spread, costs["TINY"].half_spread)
        self.assertGreater(costs["BIG"].adv_usd, costs["TINY"].adv_usd)

    def test_missing_volume_fails_closed(self):
        with self.assertRaisesRegex(Exception, "no usable dollar volume"):
            estimate_trading_costs({"AAPL": self.rows(0)}, symbols=("AAPL",))


if __name__ == "__main__":
    unittest.main()
