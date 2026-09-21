from __future__ import annotations

import math
import unittest
from datetime import date, timedelta

import numpy as np

from investment_agent.trading.contracts import ContractError
from investment_agent.trading.portfolio.market_risk import (
    calculate_market_covariance,
    calculate_market_risk,
    historical_tail_losses,
    ledoit_wolf_constant_correlation,
)


def _rows(start: float, returns: list[float]) -> list[dict[str, object]]:
    value = start
    origin = date(2026, 1, 1)
    rows = [{"trade_date": origin.isoformat(), "close": value}]
    for offset, daily_return in enumerate(returns, start=1):
        value *= 1.0 + daily_return
        rows.append({"trade_date": (origin + timedelta(days=offset)).isoformat(), "close": value})
    return rows


class MarketRiskTest(unittest.TestCase):
    def test_missing_internal_price_cannot_mix_one_and_two_day_returns(self):
        returns = [0.01, -0.02, 0.03, -0.01] * 20
        complete = _rows(100, returns)
        missing = complete[:40] + complete[41:]
        with self.assertRaisesRegex(ContractError, "unaligned price intervals"):
            calculate_market_covariance(
                {"AAPL": missing, "MSFT": complete}, symbols=("AAPL", "MSFT"), horizon_days=20,
            )

    def test_different_history_starts_are_allowed_when_overlap_is_complete(self):
        rows = _rows(100, [0.01, -0.02, 0.03, -0.01] * 25)
        result = calculate_market_covariance(
            {"AAPL": rows[10:], "MSFT": rows}, symbols=("AAPL", "MSFT"), horizon_days=20,
        )
        self.assertEqual(result.observation_count, 90)

    def test_drawdown_includes_loss_from_initial_capital(self):
        returns = [-0.2] + [0.001, -0.001] * 40
        metrics = calculate_market_risk(
            {"AAPL": _rows(100, returns), "SPY": _rows(100, returns)},
            target_weights={"AAPL": 1.0, "CASH": 0.0},
        )
        wealth = np.r_[1.0, np.cumprod(1.0 + np.asarray(returns))]
        self.assertAlmostEqual(metrics.drawdown_fraction, float(np.max(1 - wealth / np.maximum.accumulate(wealth))))
        self.assertGreaterEqual(metrics.drawdown_fraction, 0.2)

    def test_covariance_uses_signal_order_and_horizon(self):
        base_returns = [0.001 + (index % 5 - 2) * 0.0004 for index in range(80)]
        covariance = calculate_market_covariance(
            {
                "MSFT": _rows(100.0, [0.7 * value for value in base_returns]),
                "AAPL": _rows(100.0, [1.1 * value for value in base_returns]),
            },
            symbols=("AAPL", "MSFT"),
            horizon_days=5,
        )
        self.assertEqual(covariance.symbols, ("AAPL", "MSFT"))
        self.assertEqual(covariance.horizon_days, 5)
        self.assertEqual(covariance.observation_count, 80)
        self.assertEqual(len(covariance.matrix), 2)
        self.assertGreater(covariance.matrix[0][1], 0.0)
        metadata = covariance.to_metadata()
        self.assertEqual(metadata["method"], "ledoit_wolf_constant_correlation")
        self.assertEqual(metadata["matrix"], [list(row) for row in covariance.matrix])
        # 두 종목이 완전 상관이면 prior와 표본이 같아 수축할 것이 없다.
        self.assertAlmostEqual(metadata["shrinkage"], 0.0, places=9)

    def test_shrinkage_matches_brute_force_estimator_and_keeps_variances(self):
        rng = np.random.default_rng(3)
        # 시장·섹터 두 요인에 서로 다르게 노출돼 참 상관이 종목쌍마다 다르다.
        factors = rng.normal(0.0, 0.01, size=(120, 2))
        loadings = np.array([[1.0, 1.2], [1.0, 1.0], [1.0, 0.8], [1.0, 0.0],
                             [0.8, -0.2], [0.6, 0.0], [1.2, 0.3], [0.4, 0.0]])
        returns = factors @ loadings.T + rng.normal(0.0, 0.006, size=(120, 8))
        shrunk, intensity = ledoit_wolf_constant_correlation(returns)

        # 정의식을 원소별로 그대로 계산한 기준값과 대조한다.
        t, n = returns.shape
        x = returns - returns.mean(axis=0)
        s = x.T @ x / t
        sd = np.sqrt(np.diag(s))
        r_bar = sum(s[i, j] / (sd[i] * sd[j]) for i in range(n) for j in range(n) if i != j) / (n * (n - 1))
        prior = r_bar * np.outer(sd, sd)
        np.fill_diagonal(prior, np.diag(s))
        pi = sum(np.mean((x[:, i] * x[:, j] - s[i, j]) ** 2) for i in range(n) for j in range(n))
        rho = sum(np.mean((x[:, i] * x[:, i] - s[i, i]) ** 2) for i in range(n))
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                theta_ii = np.mean((x[:, i] ** 2 - s[i, i]) * (x[:, i] * x[:, j] - s[i, j]))
                theta_jj = np.mean((x[:, j] ** 2 - s[j, j]) * (x[:, i] * x[:, j] - s[i, j]))
                rho += r_bar / 2 * (sd[j] / sd[i] * theta_ii + sd[i] / sd[j] * theta_jj)
        gamma = float(np.sum((s - prior) ** 2))
        expected_intensity = max(0.0, min(1.0, (pi - rho) / gamma / t))

        self.assertAlmostEqual(intensity, expected_intensity, places=10)
        self.assertGreater(intensity, 0.0)
        self.assertLess(intensity, 1.0)
        np.testing.assert_allclose(np.diag(shrunk), np.var(returns, axis=0, ddof=1), rtol=1e-10)
        sample_corr = np.corrcoef(returns, rowvar=False)
        shrunk_corr = shrunk / np.outer(np.sqrt(np.diag(shrunk)), np.sqrt(np.diag(shrunk)))
        upper = np.triu_indices(n, k=1)
        # 추정 잡음으로 벌어진 상관이 평균 쪽으로 모인다.
        self.assertLess(float(np.std(shrunk_corr[upper])), float(np.std(sample_corr[upper])))
        self.assertGreaterEqual(float(np.min(np.linalg.eigvalsh(shrunk))), 0.0)

    def test_calculates_annualized_volatility_beta_correlation_and_drawdown(self):
        spy_returns = [0.001 + (index % 5 - 2) * 0.0004 for index in range(80)]
        aapl_returns = [1.1 * value + 0.0001 for value in spy_returns]
        msft_returns = [0.7 * value - 0.0001 for value in spy_returns]
        metrics = calculate_market_risk(
            {
                "AAPL": _rows(100.0, aapl_returns),
                "MSFT": _rows(100.0, msft_returns),
                "SPY": _rows(100.0, spy_returns),
            },
            target_weights={"AAPL": 0.4, "MSFT": 0.4, "CASH": 0.2},
        )
        self.assertEqual(metrics.observation_count, 80)
        self.assertGreater(metrics.portfolio_volatility, 0.0)
        self.assertGreater(metrics.portfolio_beta, 0.0)
        self.assertAlmostEqual(metrics.max_pairwise_correlation, 1.0, places=8)
        self.assertGreaterEqual(metrics.drawdown_fraction, 0.0)
        self.assertTrue(all(math.isfinite(value) for value in (
            metrics.portfolio_volatility,
            metrics.portfolio_beta,
            metrics.max_pairwise_correlation,
            metrics.drawdown_fraction,
        )))

    def test_tail_losses_replay_the_worst_consecutive_windows(self):
        returns = [0.001] * 40 + [-0.05] * 5 + [0.001] * 40
        tail = historical_tail_losses(returns)
        expected_crash = 1.0 - 0.95 ** 5
        self.assertAlmostEqual(tail["worst_5d_loss"], expected_crash, places=9)
        self.assertGreaterEqual(tail["worst_20d_loss"], tail["worst_5d_loss"] - 0.05)
        # CVaR은 최악 5% 구간의 평균이므로 최악값을 넘지 않고 0보다 크다.
        self.assertGreater(tail["historical_cvar_95_5d"], 0.0)
        self.assertLessEqual(tail["historical_cvar_95_5d"], tail["worst_5d_loss"] + 1e-12)
        wealth = np.concatenate(([1.0], np.cumprod(1.0 + np.asarray(returns))))
        windows = np.sort(wealth[5:] / wealth[:-5] - 1.0)
        worst = windows[: int(len(windows) * 0.05)]
        self.assertAlmostEqual(tail["historical_cvar_95_5d"], -float(np.mean(worst)), places=12)
        short = historical_tail_losses([0.01, -0.02, 0.0])
        self.assertIsNone(short["worst_5d_loss"])
        self.assertIsNone(short["historical_cvar_95_5d"])

    def test_market_risk_records_stress_block(self):
        spy_returns = [0.001 + (index % 5 - 2) * 0.004 for index in range(80)]
        metrics = calculate_market_risk(
            {"AAPL": _rows(100.0, [1.5 * value for value in spy_returns]), "SPY": _rows(100.0, spy_returns)},
            target_weights={"AAPL": 0.5, "CASH": 0.5},
        )
        stress = metrics.to_metadata()["stress"]
        self.assertAlmostEqual(stress["market_shock_loss"], 0.10 * metrics.portfolio_beta)
        self.assertIsNotNone(stress["worst_20d_loss"])

    def test_fails_closed_when_one_target_lacks_aligned_history(self):
        with self.assertRaisesRegex(ContractError, "missing market price history: MSFT"):
            calculate_market_risk(
                {"AAPL": _rows(100.0, [0.001] * 80), "SPY": _rows(100.0, [0.0011] * 80)},
                target_weights={"AAPL": 0.4, "MSFT": 0.4, "CASH": 0.2},
            )


if __name__ == "__main__":
    unittest.main()


class BetaParsingReuseTest(unittest.TestCase):
    """베타 추정이 benchmark 가격을 종목마다 다시 파싱하지 않는다(감사 TR2-09).

    결과는 바뀌지 않아야 한다 — 순수 계산 재사용이다.
    """

    def _rows(self, seed: int, count: int = 80):
        import random

        rng = random.Random(seed)
        value = 100.0
        rows = []
        for index in range(count):
            value *= 1.0 + rng.gauss(0.0005, 0.01)
            rows.append({
                "trade_date": (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                "close": value,
            })
        return rows

    def test_parsing_happens_once_per_symbol_and_results_are_unchanged(self):
        from unittest import mock

        from investment_agent.trading.portfolio import market_risk

        symbols = [f"S{index}" for index in range(6)]
        rows = {symbol: self._rows(index) for index, symbol in enumerate(symbols)}
        rows["SPY"] = self._rows(99)

        original = market_risk._close_by_date
        calls: list[str] = []

        def counting(rows_arg, symbol):
            calls.append(symbol)
            return original(rows_arg, symbol)

        with mock.patch.object(market_risk, "_close_by_date", side_effect=counting):
            betas = market_risk.estimate_betas(rows, symbols=symbols, minimum_observations=60)

        # 종목 6 + benchmark 1 = 7번. 전에는 benchmark를 6번 다시 파싱했다(총 12번).
        self.assertEqual(len(calls), len(symbols) + 1)
        self.assertEqual(calls.count("SPY"), 1)

        # 캐시가 없어도 같은 값이 나온다 — 결과 동일성.
        expected = {
            symbol: market_risk.estimate_betas(
                rows, symbols=[symbol], minimum_observations=60
            )[symbol]
            for symbol in symbols
        }
        for symbol in symbols:
            self.assertAlmostEqual(betas[symbol], expected[symbol], places=12)
