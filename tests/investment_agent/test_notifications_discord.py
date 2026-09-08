"""Discord 계약과 renderer를 가짜 HTTP로 검증한다. 실제 메시지는 보내지 않는다."""
from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from investment_agent.config import Config
from investment_agent.notifications.channels.discord import (
    DeliveryRejected, DeliveryUnknown, DiscordChannel, validate_message,
)
from investment_agent.notifications.renderers.reports import render_report
from investment_agent.reporting.models import DataResult


def response(status, body=None, headers=None):
    return SimpleNamespace(status_code=status, json=lambda: body, headers=headers or {})


class DiscordTest(unittest.TestCase):
    def setUp(self):
        self.post = Mock(return_value=response(200, {"id": "456"}))
        self.config = Config(env={"DISCORD_BOT_TOKEN": "fake-token"}, dotenv_path=None, dotenv_loaded=False)
        self.channel = DiscordChannel(self.config, post=self.post)

    def send(self):
        return self.channel.send(target="123", message={"content": "내용"})

    def test_one_post_has_fixed_host_timeout_and_no_mentions(self):
        self.assertEqual("456", self.send())
        self.post.assert_called_once()
        args, kwargs = self.post.call_args
        self.assertEqual(("https://discord.com/api/v10/channels/123/messages",), args)
        self.assertEqual(30, kwargs["timeout"])
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual({"parse": []}, kwargs["json"]["allowed_mentions"])

    def test_rate_limit_returns_server_delay_without_sleep_or_retry(self):
        self.post.return_value = response(429, {"retry_after": 123.5}, {"Retry-After": "120"})
        with self.assertRaises(DeliveryRejected) as caught:
            self.send()
        self.assertTrue(caught.exception.is_retryable)
        self.assertEqual(123.5, caught.exception.retry_after)
        self.post.assert_called_once()

    def test_timeout_and_server_error_do_not_retry(self):
        for status in (301, 500, 502, 503):
            with self.subTest(status=status):
                self.post.reset_mock()
                self.post.return_value = response(status)
                with self.assertRaises(DeliveryUnknown):
                    self.send()
                self.post.assert_called_once()
        self.post.side_effect = TimeoutError("secret")
        with self.assertRaises(DeliveryUnknown) as caught:
            self.send()
        self.assertNotIn("secret", str(caught.exception))

    def test_client_errors_are_terminal(self):
        for status in (400, 401, 403, 404):
            self.post.return_value = response(status)
            with self.assertRaises(DeliveryRejected) as caught:
                self.send()
            self.assertFalse(caught.exception.is_retryable)

    def test_missing_response_id_is_unknown(self):
        for body in ({}, {"id": ""}, {"id": "not-an-id"}, None, []):
            self.post.return_value = response(200, body)
            with self.assertRaises(DeliveryUnknown):
                self.send()

    def test_invalid_rate_limit_interval_is_held(self):
        for interval in (-1, "nan", "inf", "bad"):
            self.post.return_value = response(429, {"retry_after": interval})
            with self.assertRaises(DeliveryUnknown):
                self.send()

    def test_missing_config_and_invalid_target_never_post(self):
        channel = DiscordChannel(Config(env={}, dotenv_path=None, dotenv_loaded=False), post=self.post)
        with self.assertRaises(DeliveryRejected):
            channel.send(target="123", message={"content": "hello"})
        for target in ("", "https://other.example", "123/../456", "１２３"):
            with self.assertRaises(DeliveryRejected):
                self.channel.send(target=target, message={"content": "hello"})
        self.post.assert_not_called()

    def test_message_size_and_field_validation(self):
        invalid = [
            {}, {"content": "x" * 2001}, {"embeds": [{}] * 11},
            {"embeds": [{"title": "x" * 257}]},
            {"embeds": [{"description": "x" * 4097}]},
            {"embeds": [{"fields": [{"name": "n", "value": "v"}] * 26}]},
            {"embeds": [{"fields": [{"name": "n", "value": "x" * 1025}]}]},
            {"embeds": [{"description": "x" * 4000}] * 2},
            {"content": "x", "components": []},
        ]
        for message in invalid:
            with self.subTest(message=str(message)[:40]), self.assertRaises(ValueError):
                validate_message(message)
        source = {"content": "@everyone", "allowed_mentions": {"parse": ["everyone"]}}
        self.assertEqual({"parse": []}, validate_message(source)["allowed_mentions"])
        self.assertEqual(["everyone"], source["allowed_mentions"]["parse"])

    def test_an_embed_may_link_its_title_to_the_source(self):
        """거장 카드는 제목을 SEC 원문으로 잇는다.

        `url`이 허용 목록에 없던 동안 그 카드 6장이 매번 거절됐고, 실패는
        `notification_enqueue_failed` 경고 한 줄로 삼켜져 `sent=0`으로 끝났다 —
        보내지 못했다는 사실이 오류처럼 보이지 않았다.
        """
        validate_message({"embeds": [{
            "title": "워런 버핏 · 버크셔 해서웨이",
            "url": "https://www.sec.gov/Archives/edgar/data/1067983/x.txt",
        }]})

    def test_an_embed_may_carry_a_thumbnail(self):
        """전략 카드 2종(dmsr·gtaa5)이 QuickChart를 thumbnail로 건다.

        허용 목록에 없던 동안 그 두 장은 매번 거절됐고, 나머지 4장만 나가서
        "일부는 오니까 되는 줄" 알기 쉬웠다. url과 같은 부류의 결함이다.
        """
        validate_message({"embeds": [{
            "title": "GTAA-5",
            "thumbnail": {"url": "https://quickchart.io/chart?c=x"},
        }]})

    def test_thumbnail_is_checked_like_image(self):
        for media in ({"url": ""}, {"url": "x", "width": 1}, "https://x", {"url": "https://" + "x" * 2100}):
            with self.subTest(media=str(media)[:40]), self.assertRaises(ValueError):
                validate_message({"embeds": [{"title": "t", "thumbnail": media}]})

    def test_an_embed_url_must_be_a_real_web_link(self):
        """producer가 넣은 문자열이 그대로 링크가 되는 자리다."""
        for url in ("javascript:alert(1)", "data:text/html,x", "sec.gov/x", 123, "https://" + "x" * 2100):
            with self.subTest(url=str(url)[:40]), self.assertRaises(ValueError):
                validate_message({"embeds": [{"title": "t", "url": url}]})


class ReportRendererTest(unittest.TestCase):
    def test_preserves_zero_missing_and_stored_weights(self):
        report = DataResult.ok(source="reporting.portfolio_decisions", rows=[{"zero": 0, "missing": None, "approved_weights": {"A": 0.3, "CASH": 0.7}}])
        message = render_report(report, title="포트폴리오", fields={"zero": "실제 0", "missing": "미확인", "approved_weights": "승인 비중"})
        fields = message["embeds"][0]["fields"]
        self.assertEqual(["0", "—", '{"A":0.3,"CASH":0.7}'], [f["value"] for f in fields])
        self.assertEqual("reporting.portfolio_decisions", message["embeds"][0]["footer"]["text"])
        validate_message(message)

    def test_failed_and_empty_reports_are_not_success_messages(self):
        for status in ("empty", "offline", "unconfigured", "blocked", "error"):
            report = DataResult(status=status, source="reporting.test")
            with self.assertRaises(ValueError):
                render_report(report, title="보고서", fields={"x": "값"})
        with self.assertRaises(ValueError):
            render_report(DataResult.ok(source="reporting.test", rows=[{"x": 1}]), title="보고서", fields={"missing": "값"})
