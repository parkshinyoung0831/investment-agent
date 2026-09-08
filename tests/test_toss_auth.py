"""토스 OAuth 공용 token manager의 동시성·보안 경계를 검증한다."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
import time
import traceback
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from investment_agent.data.universe.infrastructure.sources import toss_holdings as alerts_toss
from investment_agent.execution.brokers.toss import auth as toss_auth
from investment_agent.execution.brokers.toss.auth import TossAuthError, TossTokenManager
from investment_agent.execution.brokers.toss import client as execution_toss
from investment_agent.data.universe.infrastructure.sources import toss as universe_toss


class FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code < 400:
            return
        response = requests.Response()
        response.status_code = self.status_code
        response.url = "https://openapi.tossinvest.com/oauth2/token"
        raise requests.HTTPError(response=response)

    def json(self) -> object:
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


def token_response(token: str, *, expires_in: int = 3600) -> FakeResponse:
    return FakeResponse(200, {"access_token": token, "expires_in": expires_in})


class TossTokenManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.temporary.name) / "toss-auth" / "oauth-token.json"

    def tearDown(self) -> None:
        toss_auth._reset_shared_managers_for_tests()
        self.temporary.cleanup()

    def test_default_cache_stays_at_the_repository_artifact_path(self) -> None:
        """모듈 이동이 worker 간 OAuth cache 공유 경로를 바꾸면 안 된다."""
        with patch.dict(os.environ, {"TOSS_TOKEN_CACHE_PATH": ""}, clear=False):
            expected = Path(__file__).resolve().parents[1] / "artifacts" / "toss_auth" / "oauth-token.json"
            self.assertEqual(toss_auth._default_cache_path(), expected.resolve())

    def manager(self, http_post, **changes) -> TossTokenManager:
        values = {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "cache_path": self.cache_path,
            "http_post": http_post,
            "lock_poll_seconds": 0.01,
            "sleep": lambda _seconds: None,
        }
        values.update(changes)
        return TossTokenManager(**values)

    def test_disk_cache_is_shared_and_written_atomically_with_private_mode(self) -> None:
        issue = Mock(return_value=token_response("token-one"))
        first = self.manager(issue)
        self.assertEqual(first.access_token(), "token-one")

        second_post = Mock(side_effect=AssertionError("토큰을 다시 발급하면 안 됩니다"))
        second = self.manager(second_post)
        self.assertEqual(second.access_token(), "token-one")
        issue.assert_called_once()
        second_post.assert_not_called()

        mode = stat.S_IMODE(self.cache_path.stat().st_mode)
        if os.name != "nt":
            self.assertEqual(mode, stat.S_IRUSR | stat.S_IWUSR)
        else:
            self.assertTrue(os.access(self.cache_path, os.R_OK | os.W_OK))
        temporary_files = list(self.cache_path.parent.glob(".oauth-token.json.*.tmp"))
        self.assertEqual(temporary_files, [])
        payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertNotIn("client-id", payload["credential_fingerprint"])
        self.assertNotIn("client-secret", self.cache_path.read_text(encoding="utf-8"))

    def test_two_independent_managers_issue_only_once(self) -> None:
        count = 0
        count_lock = threading.Lock()
        start = threading.Barrier(3)

        def issue(*_args, **_kwargs):
            nonlocal count
            with count_lock:
                count += 1
            time.sleep(0.08)
            return token_response("shared-token")

        managers = (self.manager(issue), self.manager(issue))

        def read(manager: TossTokenManager) -> str:
            start.wait()
            return manager.access_token()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(read, manager) for manager in managers]
            start.wait()
            results = [future.result(timeout=3) for future in futures]

        self.assertEqual(results, ["shared-token", "shared-token"])
        self.assertEqual(count, 1)

    def test_401_refreshes_inside_manager_and_retries_request_once(self) -> None:
        issue = Mock(side_effect=[token_response("old-token"), token_response("new-token")])
        manager = self.manager(issue)
        responses = iter([FakeResponse(401, {}), FakeResponse(200, {"result": "ok"})])
        sent_headers: list[dict[str, str]] = []

        def send(_url: str, *, headers: dict[str, str], timeout: int) -> FakeResponse:
            self.assertEqual(timeout, 30)
            sent_headers.append(dict(headers))
            return next(responses)

        result = manager.authorized_request(
            send,
            "https://openapi.tossinvest.com/api/v1/accounts",
            headers={"Accept": "application/json", "Authorization": "Bearer stale"},
            timeout=30,
        )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(issue.call_count, 2)
        self.assertEqual(len(sent_headers), 2)
        self.assertEqual(sent_headers[0]["Authorization"], "Bearer old-token")
        self.assertEqual(sent_headers[1]["Authorization"], "Bearer new-token")

    def test_second_401_is_returned_without_an_infinite_refresh_loop(self) -> None:
        issue = Mock(side_effect=[token_response("old-token"), token_response("new-token")])
        manager = self.manager(issue)
        send = Mock(side_effect=[FakeResponse(401, {}), FakeResponse(401, {})])

        result = manager.authorized_request(send, "https://example.invalid")

        self.assertEqual(result.status_code, 401)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(issue.call_count, 2)

    def test_concurrent_401_refreshes_converge_on_one_new_token(self) -> None:
        seed = self.manager(Mock(return_value=token_response("old-token")))
        self.assertEqual(seed.access_token(), "old-token")

        refresh_count = 0
        count_lock = threading.Lock()

        def refresh(*_args, **_kwargs):
            nonlocal refresh_count
            with count_lock:
                refresh_count += 1
            time.sleep(0.08)
            return token_response("new-token")

        managers = (self.manager(refresh), self.manager(refresh))
        self.assertEqual([manager.access_token() for manager in managers], ["old-token"] * 2)
        start = threading.Barrier(3)

        def run(manager: TossTokenManager) -> str:
            start.wait()
            return manager.refresh_access_token(rejected_token="old-token")

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, manager) for manager in managers]
            start.wait()
            results = [future.result(timeout=3) for future in futures]

        self.assertEqual(results, ["new-token", "new-token"])
        self.assertEqual(refresh_count, 1)

    def test_corrupt_cache_is_replaced_without_exposing_its_contents(self) -> None:
        self.cache_path.parent.mkdir(parents=True)
        self.cache_path.write_text("not-json-private-value", encoding="utf-8")
        manager = self.manager(Mock(return_value=token_response("replacement")))

        self.assertEqual(manager.access_token(), "replacement")
        payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["access_token"], "replacement")

    def test_expired_disk_token_is_replaced_under_the_same_lock(self) -> None:
        first_post = Mock(return_value=token_response("expired-token", expires_in=100))
        first = self.manager(first_post, wall_clock=lambda: 1_000.0)
        self.assertEqual(first.access_token(), "expired-token")

        second_post = Mock(return_value=token_response("fresh-token", expires_in=100))
        second = self.manager(second_post, wall_clock=lambda: 1_091.0)
        self.assertEqual(second.access_token(), "fresh-token")

        first_post.assert_called_once()
        second_post.assert_called_once()

    def test_403_maps_to_ip_allowlist_error_without_response_details(self) -> None:
        manager = self.manager(Mock(return_value=FakeResponse(403, {"secret": "body"})))

        with self.assertRaises(TossAuthError) as caught:
            manager.access_token()

        self.assertEqual(caught.exception.status_code, 403)
        self.assertIn("IP", str(caught.exception))
        self.assertNotIn("body", "".join(traceback.format_exception(caught.exception)))

    def test_network_error_message_never_contains_client_secret(self) -> None:
        secret = "do-not-log-this-secret"
        post = Mock(side_effect=requests.ConnectionError(f"transport included {secret}"))
        manager = TossTokenManager(
            client_id="client-id",
            client_secret=secret,
            cache_path=self.cache_path,
            http_post=post,
            sleep=lambda _seconds: None,
        )

        with self.assertRaises(TossAuthError) as caught:
            manager.access_token()

        self.assertNotIn(secret, str(caught.exception))
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn(secret, rendered)
        self.assertEqual(post.call_count, 3)


class TossSharedClientIntegrationTest(unittest.TestCase):
    def tearDown(self) -> None:
        toss_auth._reset_shared_managers_for_tests()

    def test_alerts_universe_and_execution_share_one_process_manager(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "oauth-token.json"
            environment = {
                "TOSS_CLIENT_ID": "client-id",
                "TOSS_CLIENT_SECRET": "client-secret",
                "TOSS_TOKEN_CACHE_PATH": str(cache_path),
            }
            issue = Mock(return_value=token_response("one-process-token"))
            with patch.dict(os.environ, environment, clear=False), patch.object(
                toss_auth.requests,
                "post",
                issue,
            ):
                toss_auth._reset_shared_managers_for_tests()
                first_manager = toss_auth.get_token_manager()
                self.assertIs(first_manager, toss_auth.get_token_manager())
                tokens = (
                    alerts_toss.access_token(),
                    universe_toss._access_token(),
                    execution_toss.access_token(),
                )

        self.assertEqual(tokens, ("one-process-token",) * 3)
        issue.assert_called_once()

    def test_missing_credentials_preserves_optional_universe_semantics(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            toss_auth._reset_shared_managers_for_tests()
            self.assertIsNone(universe_toss._access_token())
            with self.assertRaises(alerts_toss.TossApiError):
                alerts_toss.access_token()
            with self.assertRaises(execution_toss.TossExecutionError):
                execution_toss.access_token()


if __name__ == "__main__":
    unittest.main()
