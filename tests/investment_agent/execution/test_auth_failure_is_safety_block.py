"""요청 **전** 인증 실패는 사전 안전 차단이다 — 결과 불명이 아니다.

`_request`는 첫 POST 전에 토큰을 발급받는다. 거기서 `TossAuthError`(RuntimeError)를 그대로
올리면 live worker의 except 세 개(`TossOrderOutcomeUnknown`·`TossOrderRejected`·
`ExecutionSafetyError`)를 모두 빠져나가, 원장에 `planned` 주문과 `executing` intent가 남는다.
대사는 `planned`를 보지 않으므로(`reconcilable_orders`) 사람 손 없이는 풀리지 않는다(감사 EX2-07).
"""
from __future__ import annotations

import unittest

from investment_agent.execution.brokers.toss.auth import TossAuthError
from investment_agent.execution.brokers.toss.orders import TossOrderApi
from investment_agent.execution.contracts import ExecutionSafetyError


class _Session:
    def __init__(self) -> None:
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("토큰 발급이 실패했는데 요청이 나갔다")

    get = post


class AuthFailureBeforeRequestTest(unittest.TestCase):
    def _api(self, session):
        def token_provider() -> str:
            raise TossAuthError("IP is not registered")

        return TossOrderApi(session=session, token_provider=token_provider)

    def test_it_raises_a_safety_error_and_sends_nothing(self):
        session = _Session()
        api = self._api(session)
        with self.assertRaises(ExecutionSafetyError):
            api._request("post", "https://example.invalid/orders", account_seq=7, json={})
        self.assertEqual(session.calls, 0)

    def test_the_worker_catches_that_type(self):
        """worker가 실제로 잡는 집합에 속하는지 — 이것이 이 수정의 요점이다."""
        import inspect

        from investment_agent.execution.orders import live_worker

        source = inspect.getsource(live_worker)
        self.assertIn("ExecutionSafetyError", source)


if __name__ == "__main__":
    unittest.main()
