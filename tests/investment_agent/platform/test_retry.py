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
        self.assertTrue(is_transient(OSError(101, "Network is unreachable")))
        self.assertTrue(is_transient(ConnectionResetError()))
        self.assertTrue(is_transient(requests.ConnectionError()))
        self.assertTrue(is_transient(httpx.ConnectTimeout("x")))

    def test_transient_postgrest_codes_are_retried(self) -> None:
        for code in ("08006", "53300", "40001", "57014", "PGRST002"):
            self.assertTrue(is_transient(APIError({"code": code, "message": "x"})), code)

    def test_cloudflare_html_masquerading_as_postgrest_400_is_transient(self) -> None:
        error = APIError({
            "code": 400,
            "message": "JSON could not be generated",
            "details": "<html><center>cloudflare</center></html>",
        })
        self.assertTrue(is_transient(error))

    def test_constraint_and_permission_errors_are_not_retried(self) -> None:
        for code in ("23505", "23503", "42501", "42P01", "PGRST116"):
            self.assertFalse(is_transient(APIError({"code": code, "message": "x"})), code)

    def test_file_errors_are_not_retried_even_though_they_are_oserrors(self) -> None:
        """없는 파일·권한 오류는 다시 해도 같다 — `OSError` 전체를 일시적으로 보면 고장을 늦게 알린다."""
        from investment_agent.platform.retry import network_retry

        for error in (FileNotFoundError("x"), PermissionError("x"), IsADirectoryError("x"), FileExistsError("x")):
            with self.subTest(error=type(error).__name__):
                self.assertFalse(is_transient(error))
                calls: list[int] = []

                @network_retry(attempts=3, max_wait=0)
                def read() -> None:
                    calls.append(1)
                    raise error

                with self.assertRaises(type(error)):
                    read()
                self.assertEqual(len(calls), 1)

    def test_http2_internal_keyerror_is_retried_but_a_plain_keyerror_is_not(self) -> None:
        """여러 스레드가 한 HTTP/2 연결을 쓰다 `KeyError: 3`이 새 나온 것은 새 스트림으로 다시 보내면 된다."""
        def raised_from(filename: str) -> KeyError:
            code = compile("def boom():\n    raise KeyError(3)\n", filename, "exec")
            namespace: dict = {}
            exec(code, namespace)
            try:
                namespace["boom"]()
            except KeyError as error:
                return error
            raise AssertionError

        self.assertTrue(is_transient(raised_from("/x/site-packages/httpcore/_sync/http2.py")))
        self.assertTrue(is_transient(raised_from("/x/site-packages/h2/connection.py")))
        self.assertFalse(is_transient(raised_from("/x/our_code/reader.py")))
        self.assertFalse(is_transient(KeyError("missing")))

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
