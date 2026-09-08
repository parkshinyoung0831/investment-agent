"""다시 해서 달라질 수 있는 것만 다시 한다."""
from __future__ import annotations

import unittest

import httpx
import requests
from postgrest.exceptions import APIError

from investment_agent.platform.retry import is_transient, transient_retry


def _requests_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


def _httpx_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test")
    return httpx.HTTPStatusError("x", request=request, response=httpx.Response(status, request=request))


class IsTransientTest(unittest.TestCase):
    def test_rate_limit_and_server_errors_are_retried(self) -> None:
        for status in (429, 500, 502, 503):
            self.assertTrue(is_transient(_requests_error(status)), status)
            self.assertTrue(is_transient(_httpx_error(status)), status)

    def test_client_errors_are_not_retried(self) -> None:
        """401·404는 몇 번을 해도 같다. 재시도하면 고장을 늦게 알아챌 뿐이다."""
        for status in (400, 401, 403, 404, 422):
            self.assertFalse(is_transient(_requests_error(status)), status)
            self.assertFalse(is_transient(_httpx_error(status)), status)

    def test_transport_failures_are_retried(self) -> None:
        self.assertTrue(is_transient(TimeoutError()))
        self.assertTrue(is_transient(requests.ConnectionError()))
        self.assertTrue(is_transient(httpx.ConnectTimeout("x")))

    def test_transient_postgrest_codes_are_retried(self) -> None:
        for code in ("08006", "53300", "40001", "57014", "PGRST002"):
            self.assertTrue(is_transient(APIError({"code": code, "message": "x"})), code)

    def test_constraint_and_permission_errors_are_not_retried(self) -> None:
        for code in ("23505", "23503", "42501", "42P01", "PGRST116"):
            self.assertFalse(is_transient(APIError({"code": code, "message": "x"})), code)

    def test_programming_errors_are_not_retried(self) -> None:
        self.assertFalse(is_transient(ValueError("bad input")))
        self.assertFalse(is_transient(KeyError("missing")))


class TransientRetryTest(unittest.TestCase):
    def test_retries_until_it_succeeds(self) -> None:
        calls = {"n": 0}

        @transient_retry(attempts=3, max_wait=0.01)
        def flaky() -> str:
            calls["n"] += 1
            if calls["n"] < 3:
                raise requests.ConnectionError("boom")
            return "ok"

        self.assertEqual("ok", flaky())
        self.assertEqual(3, calls["n"])

    def test_permanent_failure_raises_immediately(self) -> None:
        calls = {"n": 0}

        @transient_retry(attempts=4, max_wait=0.01)
        def broken() -> None:
            calls["n"] += 1
            raise ValueError("bad input")

        with self.assertRaises(ValueError):
            broken()
        self.assertEqual(1, calls["n"])

    def test_original_exception_is_reraised_not_wrapped(self) -> None:
        """tenacity가 감싸면 부르는 쪽의 except 절이 안 잡힌다."""

        @transient_retry(attempts=2, max_wait=0.01)
        def always_down() -> None:
            raise requests.ConnectionError("down")

        with self.assertRaises(requests.ConnectionError):
            always_down()


if __name__ == "__main__":
    unittest.main()
