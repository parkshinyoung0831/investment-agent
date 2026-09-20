"""Hypothesis 기반 포트폴리오 비중 계약 불변식(Invariants) 검증.

포트폴리오 비중은 수동 테스트 케이스 몇 개만으로는 부동소수점 오차나
경계값(0.0, 1.0, 다수 종목 분할)에서의 불변식을 보장하기 어렵다.
Hypothesis property-based testing을 통해 임의의 유효/무효 입력에 대해
수학적 불변성이 항상 유지되는지 검증한다.
"""
from __future__ import annotations

import math
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from investment_agent.platform.serialization import ContractError
from investment_agent.portfolio_weights import CASH_SYMBOL, validated_weights

TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META"]


class PortfolioContractsHypothesisTest(unittest.TestCase):
    """validated_weights 함수의 수학적 불변식 및 경계 조건 검증."""

    @given(
        raw_weights=st.lists(
            st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=5,
        )
    )
    @settings(max_examples=50)
    def test_valid_simplex_weights_satisfy_invariants(self, raw_weights: list[float]) -> None:
        """합이 1.0으로 정규화된 임의의 유효 비중은 모든 불변식을 만족해야 한다."""
        total = math.fsum(raw_weights)
        norm = [w / total for w in raw_weights]
        # 부동소수점 누적 오차를 마지막 요소에 보정하여 sum == 1.0 보장
        norm[-1] = 1.0 - math.fsum(norm[:-1])
        if norm[-1] < 0.0 or norm[-1] > 1.0:
            return

        symbols = TICKERS[: len(norm)]
        weights_map = dict(zip(symbols, norm))

        result = validated_weights(weights_map, require_total=True)

        # 1. CASH 심볼이 항상 결과에 포함되어야 함
        self.assertIn(CASH_SYMBOL, result)

        # 2. 결과 딕셔너리의 키는 항상 사전순으로 정렬되어야 함
        self.assertEqual(list(result.keys()), sorted(result.keys()))

        # 3. 모든 비중은 0 이상 1 이하의 유한한 실수여야 함
        for sym, weight in result.items():
            self.assertTrue(0.0 <= weight <= 1.0, f"{sym} weight {weight} out of bounds")
            self.assertTrue(math.isfinite(weight))

        # 4. 전체 합(CASH 포함)은 1.0이어야 함 (허용오차 1e-7)
        self.assertTrue(math.isclose(math.fsum(result.values()), 1.0, abs_tol=1e-7))

    @given(
        bad_sum=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False).filter(
            lambda x: not math.isclose(x, 1.0, abs_tol=1e-4)
        )
    )
    @settings(max_examples=30)
    def test_invalid_sum_weights_rejected(self, bad_sum: float) -> None:
        """합이 1.0이 아닌 비중은 require_total=True 일 때 반드시 ContractError를 발생시켜야 한다."""
        weights = {"AAPL": bad_sum / 2.0, CASH_SYMBOL: bad_sum / 2.0}
        if bad_sum / 2.0 > 1.0:
            # 개별 가중치 한도 초과
            with self.assertRaises(ContractError):
                validated_weights(weights, require_total=True)
        else:
            with self.assertRaises(ContractError):
                validated_weights(weights, require_total=True)

    @given(
        negative_weight=st.floats(min_value=-100.0, max_value=-0.0001, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=30)
    def test_negative_weights_always_rejected(self, negative_weight: float) -> None:
        """음수 가중치는 long-only 계약 위반으로 항상 거부되어야 한다."""
        weights = {"AAPL": negative_weight, CASH_SYMBOL: 1.0 - negative_weight}
        with self.assertRaises(ContractError):
            validated_weights(weights, require_total=False)

    @given(
        invalid_ticker=st.text(
            alphabet=st.sampled_from(list("!@#$%^&*()+=~`{}[]|:;'<>,?/")),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=30)
    def test_invalid_ticker_symbols_rejected(self, invalid_ticker: str) -> None:
        """정규표현식에 맞지 않는 비정상 티커 심볼은 거부되어야 한다."""
        weights = {invalid_ticker: 1.0}
        with self.assertRaises(ContractError):
            validated_weights(weights, require_total=False)

    @given(
        prob_up=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        conf=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        target_w=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        excess_ret=st.floats(min_value=-10.0, max_value=10.0, allow_nan=False),
    )
    @settings(max_examples=30)
    def test_security_proposal_invariants_hold(
        self, prob_up: float, conf: float, target_w: float, excess_ret: float
    ) -> None:
        """유효한 범위의 확률 및 가중치를 가진 제안은 항상 정상 생성되어야 한다."""
        from investment_agent.trading.portfolio.contracts import SecurityProposal

        prop = SecurityProposal(
            ticker="AAPL",
            as_of_at="2026-09-20T12:00:00+00:00",
            signal="open",
            probability_up=prob_up,
            confidence=conf,
            expected_excess_return=excess_ret,
            target_weight=target_w,
            reasoning=("Hypothesis property test",),
            evidence_ids=(),
        )
        self.assertEqual(prop.ticker, "AAPL")
        self.assertTrue(0.0 <= prop.probability_up <= 1.0)
        self.assertTrue(0.0 <= prop.confidence <= 1.0)
        self.assertTrue(0.0 <= prop.target_weight <= 1.0)


if __name__ == "__main__":
    unittest.main()
