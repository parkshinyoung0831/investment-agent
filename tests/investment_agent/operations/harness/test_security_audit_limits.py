"""보안 사전점검이 실주문 게이트가 읽는 한도를 **전부**, 그리고 잘못된 값도 잡는다.

전에는 ① 파싱 실패를 `None`으로 바꾼 뒤 소비자가 "검사 대상 아님"으로 읽어 잘못된 한도가
점검을 통째로 건너뛰고 healthy로 나왔고(감사 OP2-11), ② 게이트가 쓰는 다섯 한도 중
`TOSS_MAX_DAILY_ORDERS`를 아예 보지 않았다(감사 OP2-12). 손으로 나열한 목록은 한도가 늘 때
다시 벌어지므로, 게이트가 읽는 키 집합과 대조해 고정한다.
"""
from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from investment_agent.execution.safety import control
from investment_agent.operations.harness.security_audit import (
    CheckStatus,
    _check_trading_limits,
)

# 한도가 아닌 것(계좌·플래그·불리언 토글)은 이 점검의 대상이 아니다.
_NON_LIMIT_KEYS = {"TOSS_ALLOW_MARKET_ORDERS"}


def _gate_limit_keys() -> set[str]:
    """`LiveTradingControls.from_config`가 실제로 읽는 `TOSS_MAX_*` 키."""
    source = inspect.getsource(control.LiveTradingControls.from_config)
    tree = ast.parse(inspect.cleandoc(source))
    return {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value.startswith("TOSS_MAX_")
    } - _NON_LIMIT_KEYS


class SecurityAuditLimitsTest(unittest.TestCase):
    def test_every_gate_limit_is_audited(self):
        audited = {
            result.code.removesuffix("_NOT_NUMERIC")
            for key in _gate_limit_keys()
            for result in _check_trading_limits({key: "not-a-number"})
            if result.code.endswith("_NOT_NUMERIC")
        }
        self.assertEqual(_gate_limit_keys() - audited, set(),
                         "게이트가 읽는 한도인데 사전점검이 보지 않는다")

    def test_a_non_numeric_limit_is_a_failure_not_a_skip(self):
        for key in sorted(_gate_limit_keys()):
            with self.subTest(key=key):
                results = _check_trading_limits({key: "오백달러"})
                failures = [r for r in results if r.status is CheckStatus.FAIL]
                self.assertTrue(failures, f"{key}가 숫자가 아닌데 FAIL이 없다")

    def test_a_default_environment_passes_every_limit(self):
        results = _check_trading_limits({})
        self.assertTrue(results)
        self.assertEqual([r for r in results if r.status is not CheckStatus.PASS], [])

    def test_an_absurd_order_count_is_surfaced(self):
        codes = {r.code for r in _check_trading_limits({"TOSS_MAX_DAILY_ORDERS": "10000"})}
        self.assertIn("DAILY_ORDER_COUNT_OUT_OF_BOUNDS", codes)


if __name__ == "__main__":
    unittest.main()
