"""외부 공급자 일일 호출 원장의 원자성과 fail-closed 설정을 검증한다."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from investment_agent.intelligence.infrastructure.sources.news import provider as news_provider
from investment_agent.intelligence.infrastructure.sources.news import yfinance as yfinance_source
from investment_agent.intelligence.infrastructure.sources.social import reddit as reddit_source
from investment_agent.platform.external_usage import (
    ExternalUsageError,
    UsageReservation,
    default_ledger_path,
    provider_daily_cap,
    provider_daily_caps,
    reserve_provider_call,
)


def _uncached(function):
    return getattr(function, "__wrapped__", function)


class ExternalUsageTest(unittest.TestCase):
    def test_provider_caps_have_safe_defaults_and_validate_overrides(self):
        self.assertEqual(provider_daily_cap("yfinance", ""), 25)
        self.assertEqual(provider_daily_cap("alpha_vantage", "alpha_vantage=7"), 7)
        self.assertEqual(provider_daily_cap("stocktwits", "stocktwits=40"), 40)
        with self.assertRaisesRegex(ExternalUsageError, "no daily cap configured"):
            provider_daily_cap("stocktwits", "")
        for invalid in ("alpha_vantage", "alpha_vantage=x", "alpha_vantage=0"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ExternalUsageError):
                    provider_daily_caps(invalid)
        with self.assertRaisesRegex(ExternalUsageError, "duplicate provider"):
            provider_daily_caps("yfinance=2,yfinance=3")

    def test_reservation_warns_once_at_80_percent_and_blocks_at_cap(self):
        now = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "external-usage.sqlite3"
            results = [
                reserve_provider_call(path, provider="alpha_vantage", cap=5, now=now)
                for _ in range(6)
            ]
            self.assertEqual([item.allowed for item in results], [True] * 5 + [False])
            self.assertEqual([item.warning_due for item in results], [False] * 3 + [True, False, False])
            self.assertEqual(results[-1].attempts, 5)
            connection = sqlite3.connect(path)
            try:
                row = connection.execute(
                    "SELECT usage_date, provider, attempts, cap FROM provider_daily_usage"
                ).fetchone()
                columns = {
                    item[1]
                    for item in connection.execute("PRAGMA table_info(provider_daily_usage)")
                }
            finally:
                connection.close()
            self.assertEqual(row, ("2026-08-22", "alpha_vantage", 5, 5))
            self.assertFalse({"ticker", "url", "content", "raw"} & columns)

    def test_concurrent_reservations_cannot_exceed_cap(self):
        now = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "external-usage.sqlite3"

            def reserve(_index: int):
                return reserve_provider_call(path, provider="yfinance", cap=7, now=now)

            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(reserve, range(24)))
            self.assertEqual(sum(item.allowed for item in results), 7)
            self.assertEqual(max(item.attempts for item in results), 7)

    def test_utc_date_creates_a_fresh_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "external-usage.sqlite3"
            first = reserve_provider_call(
                path,
                provider="yfinance",
                cap=1,
                now=datetime(2026, 8, 22, 23, 59, tzinfo=timezone.utc),
            )
            second = reserve_provider_call(
                path,
                provider="yfinance",
                cap=1,
                now=datetime(2026, 8, 23, 0, 1, tzinfo=timezone.utc),
            )
            self.assertTrue(first.allowed)
            self.assertTrue(second.allowed)
            self.assertNotEqual(first.usage_date, second.usage_date)


class DefaultLedgerPathSharedAcrossCallSitesTest(unittest.TestCase):
    """같은 provider의 사용량이 두 파일로 흩어지면 실효 cap이 조용히 배가된다."""

    def test_provider_yfinance_source_and_reddit_source_reserve_against_the_same_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / "external-usage.sqlite3"
            captured: list[Path] = []

            def _fake_reserve(path, *, provider, cap, now=None):
                captured.append(Path(path))
                return UsageReservation(
                    provider=provider,
                    usage_date="2026-01-01",
                    allowed=False,
                    attempts=cap,
                    cap=cap,
                )

            with patch.dict(
                os.environ,
                {
                    "AI_INVESTOR_EXTERNAL_USAGE_LEDGER_PATH": str(ledger),
                    "DASHBOARD_OFFLINE": "0",
                    "AI_INVESTOR_EXTERNAL_NEWS_SOCIAL": "true",
                    "DASHBOARD_NEWS_PROVIDER": "yfinance",
                    "AI_INVESTOR_EXTERNAL_DAILY_CAPS": "reddit=25",
                },
                clear=False,
            ):
                self.assertEqual(default_ledger_path(), ledger)

                # provider.py는 함수 안에서 지연 import하므로 원본 모듈 함수를 패치한다.
                with patch(
                    "investment_agent.platform.external_usage.reserve_provider_call",
                    side_effect=_fake_reserve,
                ):
                    _uncached(news_provider.load_live_news)("markets", "AAPL")

                with patch.object(
                    yfinance_source, "reserve_provider_call", side_effect=_fake_reserve
                ):
                    with self.assertRaises(yfinance_source.NewsQuotaExhausted):
                        yfinance_source.fetch_ticker_news("AAPL")

                with patch.object(
                    reddit_source, "reserve_provider_call", side_effect=_fake_reserve
                ), patch.object(
                    reddit_source, "credentials_available", return_value=True
                ):
                    with self.assertRaises(reddit_source.SocialQuotaExhausted):
                        reddit_source.fetch_new_posts("stocks")

            self.assertEqual(len(captured), 3)
            self.assertTrue(all(path == ledger for path in captured))


if __name__ == "__main__":
    unittest.main()
