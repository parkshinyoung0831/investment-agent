"""Market 고정 용량 보존 작업 계약."""
from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
import tempfile
from unittest.mock import patch

from investment_agent.operations.backfill import BackfillWindow
from investment_agent.data.market import BACKFILL_YEARS
from investment_agent.data.market.domain import retention
from investment_agent.data.market.infrastructure.archive import archive_daily_rows
from investment_agent.data.market.commands import market_backfill as backfill
from investment_agent.data.market.domain.retention import compact_price_rows


class _Response:
    def __init__(self, data):
        self.data = data


class _Rpc:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return _Response(self.result)


class _Supabase:
    def __init__(self, results):
        self.results = iter(results)
        self.calls: list[tuple[str, dict]] = []

    def schema(self, name: str):
        if name != "market":
            raise AssertionError(name)
        return self

    def rpc(self, name: str, params: dict):
        self.calls.append((name, params))
        return _Rpc(next(self.results))


class MarketRetentionTest(unittest.TestCase):
    def test_backfill_archives_raw_rows_before_any_database_write(self):
        raw_rows = [{
            "ticker": "AAA", "trade_date": "2016-08-18", "open": 10.0,
            "high": 11.0, "low": 9.0, "close": 10.0, "adj_close": 9.5,
            "volume": 100, "source": "yfinance",
        }]
        order: list[str] = []
        with (
            patch("investment_agent.data.market.persistence.universe_missing_prices", return_value=["AAA"]),
            patch("investment_agent.data.market.infrastructure.sources.yahoo.download_ohlcv", return_value=raw_rows),
            patch("investment_agent.data.market.infrastructure.archive.archive_daily_rows", side_effect=lambda rows: order.append("archive")),
            patch("investment_agent.data.market.persistence.upsert_prices", side_effect=lambda rows: order.append("prices") or len(rows)),
        ):
            backfill._backfill_prices(30, "missing")
        self.assertEqual(order, ["archive", "prices"])

    def test_archive_failure_stops_before_any_database_write(self):
        raw_rows = [{
            "ticker": "AAA", "trade_date": "2016-08-18", "open": 10.0,
            "high": 11.0, "low": 9.0, "close": 10.0, "adj_close": 9.5,
            "volume": 100, "source": "yfinance",
        }]
        with (
            patch("investment_agent.data.market.persistence.universe_missing_prices", return_value=["AAA"]),
            patch("investment_agent.data.market.infrastructure.sources.yahoo.download_ohlcv", return_value=raw_rows),
            patch("investment_agent.data.market.infrastructure.archive.archive_daily_rows", side_effect=RuntimeError("archive unavailable")),
            patch("investment_agent.data.market.persistence.upsert_prices") as prices,
            self.assertRaisesRegex(RuntimeError, "archive unavailable"),
        ):
            backfill._backfill_prices(30, "missing")
        prices.assert_not_called()

    def test_archive_merges_daily_history_without_losing_older_rows(self):
        rows = [{
            "ticker": "AAA", "trade_date": "2010-01-04", "open": 10.0,
            "high": 11.0, "low": 9.0, "close": 10.0, "adj_close": 9.5,
            "volume": 100, "source": "yfinance",
        }]
        updated = [{**rows[0], "trade_date": "2010-01-05", "close": 11.0}]
        with tempfile.TemporaryDirectory() as directory:
            archive_daily_rows(rows, root=directory)
            archive_daily_rows(updated, root=directory)
            import pandas as pd
            stored = pd.read_parquet(Path(directory) / "yahoo" / "AAA" / "daily.parquet")
        self.assertEqual(stored["trade_date"].astype(str).tolist(), ["2010-01-04", "2010-01-05"])
    def test_compaction_does_not_keep_legacy_weekly_rows(self):
        rows = [
            {
                "ticker": "AAA",
                "trade_date": "2018-08-13",
            },
            {
                "ticker": "AAA",
                "trade_date": "2018-08-17",
            },
        ]

        compacted = compact_price_rows(
            rows,
            today=date(2026, 8, 18),
        )

        self.assertEqual(
            [item["trade_date"] for item in compacted],
            [],
        )

    def test_backfill_prunes_only_after_all_requested_writes_succeed(self):
        window = BackfillWindow(start=date(2016, 8, 18), end=date(2026, 8, 18))
        order: list[str] = []
        with (
            patch.object(backfill, "resolve_backfill_window", return_value=window),
            patch.object(
                backfill,
                "_backfill_prices",
                side_effect=lambda *_args: order.append("prices"),
            ),
            patch(
                "investment_agent.data.market.domain.retention.prune_history",
                side_effect=lambda **_kwargs: order.append("prune"),
            ) as prune,
        ):
            result = backfill.main([])

        self.assertEqual(result, 0)
        self.assertEqual(order, ["prices", "prune"])
        prune.assert_called_once_with(today=window.end)

    def test_backfill_write_failure_does_not_run_retention(self):
        window = BackfillWindow(start=date(2016, 8, 18), end=date(2026, 8, 18))
        with (
            patch.object(backfill, "resolve_backfill_window", return_value=window),
            patch.object(backfill, "_backfill_prices", side_effect=RuntimeError("prices failed")),
            patch("investment_agent.data.market.domain.retention.prune_history") as prune,
            self.assertRaisesRegex(RuntimeError, "prices failed"),
        ):
            backfill.main([])

        prune.assert_not_called()

    def test_history_horizons_are_aligned(self):
        self.assertEqual(BACKFILL_YEARS, 10)

        schema_sql = Path("db/postgres/v1/20_market.sql").read_text(encoding="utf-8")
        self.assertIn("market.prices_daily", schema_sql)
        self.assertNotIn("ingested_at timestamptz", schema_sql)
        self.assertNotIn("prune_history_batch", schema_sql)

    def test_retention_deletes_nothing_under_the_append_only_contract(self):
        """v1 market은 append-only 관측 원장이다 — 보존 정리는 아무것도 지우지 않는다.

        배치 삭제가 돌아오면 그것이 8초 statement timeout을 넘길 위험도 함께
        돌아온다. 전에 그랬다 — 가격을 이미 저장한 뒤 정리가 죽어 잡이 exit 1이
        되었고, market_daily 성공을 기다리던 tech_indicators가 skip됐다.
        """
        self.assertEqual({"prices_deleted": 0}, retention.prune_history())

    def test_daily_ingest_survives_a_retention_failure_and_reports_it_to_discord(self):
        """뒷정리 실패가 그날의 수집을 되돌리면 안 된다.

        2026-08-27·28에 실제로 그랬다 — 가격을 전부 저장한 뒤 보존 정리가 statement
        timeout으로 죽어 잡이 exit 1이 되었고, market_daily 성공을 기다리던
        tech_indicators가 skip되면서 이틀치 지표가 비었다.
        """
        from investment_agent.data.market.commands import market_daily as daily

        with (
            patch(
                "investment_agent.data.market.domain.retention.prune_history",
                side_effect=RuntimeError("canceling statement due to statement timeout"),
            ),
            patch.object(daily, "notify_ops") as notify,
        ):
            daily._prune_history_without_failing_ingest(date(2026, 8, 28))

        notify.assert_called_once()
        embed = notify.call_args.kwargs["embeds"][0]
        self.assertEqual(embed["title"], "일부 자동화 결과를 확인해 주세요")
        self.assertTrue(
            any("statement timeout" in str(field["value"]) for field in embed["fields"])
        )

    def test_v1_retention_does_not_call_the_removed_legacy_rpc(self):
        self.assertEqual(
            retention.prune_history(today=date(2026, 8, 18)),
            {"prices_deleted": 0},
        )


if __name__ == "__main__":
    unittest.main()
