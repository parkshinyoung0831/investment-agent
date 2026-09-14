from __future__ import annotations

import unittest

from investment_agent.trading.portfolio.contracts import SecurityProposal
from investment_agent.trading.portfolio.optimizer import (
    ExpectedReturnSignal,
    OptimizerPolicy,
    RiskAwareOptimizer,
)
from investment_agent.trading.portfolio.market_risk import TradingCostInputs, estimate_trading_costs
from investment_agent.trading.portfolio.proposals import from_optimized_security_proposals


def _proposal(target: float) -> SecurityProposal:
    return SecurityProposal(
        ticker="AAPL", as_of_at="2026-08-20T22:00:00+00:00", signal="open",
        probability_up=0.7, confidence=0.8, expected_excess_return=0.04,
        target_weight=target, reasoning=("evidence",), evidence_ids=("EV-1",),
    )


class OptimizerTest(unittest.TestCase):
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

    def test_llm_target_weight_is_not_an_optimizer_input(self):
        policy = OptimizerPolicy(max_turnover=1.0, min_cash_weight=0.1)
        left = from_optimized_security_proposals(
            [_proposal(0.01)], run_id="run-1", source_version="ta-v1",
            current_weights={"CASH": 1.0}, optimizer_policy=policy,
        )
        right = from_optimized_security_proposals(
            [_proposal(0.99)], run_id="run-1", source_version="ta-v1",
            current_weights={"CASH": 1.0}, optimizer_policy=policy,
        )
        self.assertEqual(left.weights, right.weights)
        self.assertFalse(left.metadata["llm_target_weight_used"])
        self.assertLessEqual(left.weights["AAPL"], policy.max_symbol_weight + 1e-8)
        self.assertGreaterEqual(left.weights["CASH"], policy.min_cash_weight - 1e-8)


_AT = "2026-08-20T22:00:00+00:00"


def _signal(symbol: str, expected: float, action: str | None) -> ExpectedReturnSignal:
    return ExpectedReturnSignal(symbol, expected, 1.0, 0.1, 5, "test", _AT, "v1", action=action)


class SignalActionConstraintTest(unittest.TestCase):
    def test_exit_is_full_liquidation_even_when_turnover_is_expensive(self):
        # 기대수익을 양수로 둬도(잘못된 입력) 청산 명령은 비중을 남기지 않는다.
        policy = OptimizerPolicy(turnover_penalty=1.0, max_turnover=1.0)
        result = RiskAwareOptimizer(policy).optimize(
            (_signal("AAPL", 0.05, "exit"), _signal("MSFT", 0.01, "hold")),
            current_weights={"AAPL": 0.08, "MSFT": 0.05, "CASH": 0.87},
        )
        self.assertEqual(result.weights.get("AAPL", 0.0), 0.0)

    def test_exits_larger_than_the_turnover_budget_stay_feasible(self):
        # 여섯 종목 60%를 한꺼번에 빼야 해도 25% 재량 turnover 한도가 청산을 막지 않는다.
        # (매도쪽 합만 따져도, 현금쪽 합만 따져도 0.25를 넘도록 잡았다.)
        symbols = ("AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN")
        policy = OptimizerPolicy(max_turnover=0.25)
        result = RiskAwareOptimizer(policy).optimize(
            tuple(_signal(symbol, -0.01, "exit") for symbol in symbols),
            current_weights={**{symbol: 0.1 for symbol in symbols}, "CASH": 0.4},
        )
        for symbol in symbols:
            self.assertEqual(result.weights.get(symbol, 0.0), 0.0)
        self.assertAlmostEqual(result.weights["CASH"], 1.0)

    def test_exit_proceeds_do_not_widen_the_discretionary_buy_budget(self):
        policy = OptimizerPolicy(max_turnover=0.05, turnover_penalty=0.0, risk_aversion=0.1)
        result = RiskAwareOptimizer(policy).optimize(
            (_signal("AAPL", -0.01, "exit"), _signal("META", 0.10, "open")),
            current_weights={"AAPL": 0.10, "CASH": 0.90},
        )
        self.assertEqual(result.weights.get("AAPL", 0.0), 0.0)
        self.assertLessEqual(result.weights["META"], 0.05 + 1e-6)

    def test_reduce_avoid_watch_never_add_to_a_position(self):
        policy = OptimizerPolicy(max_turnover=1.0, turnover_penalty=0.0, risk_aversion=0.1)
        for action in ("reduce", "avoid", "watch"):
            with self.subTest(action=action):
                result = RiskAwareOptimizer(policy).optimize(
                    (_signal("AAPL", 0.20, action),),
                    current_weights={"AAPL": 0.03, "CASH": 0.97},
                )
                self.assertLessEqual(result.weights["AAPL"], 0.03 + 1e-9)

    def test_capital_a_reduce_cannot_use_goes_to_other_candidates(self):
        # 사후에 잘라내기만 하면 reduce 종목 몫이 현금으로 놀고, 다른 후보가 받지 못한다.
        policy = OptimizerPolicy(
            max_turnover=1.0, turnover_penalty=0.0, risk_aversion=0.1,
            max_symbol_weight=0.10, min_cash_weight=0.85,
        )
        result = RiskAwareOptimizer(policy).optimize(
            (_signal("AAPL", 0.20, "reduce"), _signal("MSFT", 0.05, "open")),
            current_weights={"AAPL": 0.03, "CASH": 0.97},
        )
        self.assertLessEqual(result.weights["AAPL"], 0.03 + 1e-9)
        self.assertGreaterEqual(result.weights["MSFT"], 0.10 - 1e-6)

    def test_buy_opinion_can_lose_to_a_better_candidate(self):
        # open은 명령이 아니라 의견이다. 자리가 부족하면 0이 될 수 있어야 한다.
        policy = OptimizerPolicy(
            max_turnover=1.0, turnover_penalty=0.0, risk_aversion=0.1,
            max_symbol_weight=0.10, min_cash_weight=0.85,
        )
        result = RiskAwareOptimizer(policy).optimize(
            (_signal("NVDA", 0.05, "open"), _signal("AMZN", 0.001, "open")),
            current_weights={"CASH": 1.0},
            covariance=((0.001, 0.0), (0.0, 0.001)),
        )
        self.assertGreater(result.weights["NVDA"], result.weights.get("AMZN", 0.0))
        self.assertLess(result.weights.get("AMZN", 0.0), 0.05)

    def test_security_proposal_action_reaches_the_optimizer(self):
        proposal = SecurityProposal(
            ticker="AAPL", as_of_at=_AT, signal="exit", probability_up=0.3, confidence=0.8,
            expected_excess_return=0.02, target_weight=0.0, reasoning=("e",), evidence_ids=("EV-1",),
        )
        signal = ExpectedReturnSignal.from_security_proposal(proposal, source="ta", version="v1")
        self.assertEqual(signal.action, "exit")
        self.assertLessEqual(signal.expected_return, 0.0)


def _cost(symbol: str, *, adv: float, spread: float = 0.0001, vol: float = 0.02) -> TradingCostInputs:
    return TradingCostInputs(symbol, spread, vol, adv)


class TradingCostTest(unittest.TestCase):
    policy = OptimizerPolicy(
        max_turnover=1.0, turnover_penalty=0.0, risk_aversion=5.0, max_symbol_weight=0.5, min_cash_weight=0.0,
        # ADV 한도를 풀어 비용 항만으로 차이가 나는지 본다.
        max_adv_participation=1.0,
    )

    def test_expensive_to_trade_names_get_less_capital_than_their_raw_alpha_suggests(self):
        signals = (_signal("LIQD", 0.020, "open"), _signal("THIN", 0.022, "open"))
        # 두 종목 모두 상한(0.5)에 닿지 않도록 분산을 잡아, 차이가 비용에서만 나오게 한다.
        cov = ((0.01, 0.0), (0.0, 0.01))
        costs = {"LIQD": _cost("LIQD", adv=5e9), "THIN": _cost("THIN", adv=2e6, spread=0.004, vol=0.04)}
        free = RiskAwareOptimizer(self.policy).optimize(signals, current_weights={"CASH": 1.0}, covariance=cov)
        costly = RiskAwareOptimizer(self.policy).optimize(
            signals, current_weights={"CASH": 1.0}, covariance=cov,
            trading_costs=costs, portfolio_value=1_000_000.0,
        )
        self.assertGreater(free.weights["THIN"], free.weights["LIQD"])
        self.assertLess(costly.weights.get("THIN", 0.0), costly.weights["LIQD"])
        self.assertGreater(costly.transaction_cost, 0.0)
        self.assertAlmostEqual(
            costly.objective_value,
            costly.expected_return_component - costly.risk_penalty
            - costly.turnover_penalty - costly.transaction_cost,
        )

    def test_buys_are_capped_by_adv_participation_but_exits_are_not(self):
        policy = OptimizerPolicy(
            max_turnover=1.0, turnover_penalty=0.0, risk_aversion=0.01,
            max_symbol_weight=0.5, min_cash_weight=0.0, max_adv_participation=0.05, impact_coefficient=0.0,
        )
        nav = 10_000_000.0
        result = RiskAwareOptimizer(policy).optimize(
            (_signal("THIN", 0.10, "open"), _signal("OLD", -0.01, "exit")),
            current_weights={"OLD": 0.40, "CASH": 0.60},
            covariance=((0.001, 0.0), (0.0, 0.001)),
            trading_costs={"THIN": _cost("THIN", adv=4_000_000.0), "OLD": _cost("OLD", adv=1_000_000.0)},
            portfolio_value=nav,
        )
        # 20일 평균 거래대금 $4M의 5% = $200k = NAV의 2%.
        self.assertLessEqual(result.weights["THIN"], 0.02 + 1e-6)
        # $4M 청산은 OLD 거래대금의 4배지만 위험 축소라 막히지 않는다.
        self.assertEqual(result.weights.get("OLD", 0.0), 0.0)

    def test_partial_cost_inputs_are_rejected(self):
        with self.assertRaisesRegex(Exception, "trading cost inputs are missing"):
            RiskAwareOptimizer(self.policy).optimize(
                (_signal("AAPL", 0.01, "open"), _signal("MSFT", 0.01, "open")),
                current_weights={"CASH": 1.0},
                trading_costs={"AAPL": _cost("AAPL", adv=1e9)}, portfolio_value=1e6,
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
        self.assertGreater(costs["BIG"].daily_volatility, 0.0)

    def test_missing_volume_fails_closed(self):
        with self.assertRaisesRegex(Exception, "no usable dollar volume"):
            estimate_trading_costs({"AAPL": self.rows(0)}, symbols=("AAPL",))


if __name__ == "__main__":
    unittest.main()
