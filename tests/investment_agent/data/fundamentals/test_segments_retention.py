"""세그먼트 8년 보존 정책과 외래키 안전 삭제 순서를 검증한다."""
from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

from investment_agent.data.fundamentals.application import backfill_history
from investment_agent.data.fundamentals.commands import sync_filings as sync_job
from investment_agent.data.fundamentals.infrastructure.supabase import segment_metrics


class _Response:
    def __init__(self, count: int) -> None:
        self.count = count


class _Builder:
    def __init__(self, fake: _Supabase, table: str) -> None:
        self.fake = fake
        self.table_name = table
        self.field = ""
        self.cutoff = ""
        self.filters: list[tuple[str, str]] = []
        self.selected = False

    def select(self, _columns: str, **_kwargs):
        self.selected = True
        return self

    def range(self, _start: int, _end: int):
        return self

    def order(self, _column: str, **_kwargs):
        return self

    def delete(self, **kwargs):
        self.fake.delete_options.append((self.table_name, kwargs))
        return self

    def eq(self, field: str, value: str):
        self.filters.append((field, value))
        return self

    def lt(self, field: str, cutoff: str):
        self.field = field
        self.cutoff = cutoff
        return self

    def in_(self, _field: str, _values):
        return self

    def execute(self) -> _Response:
        self.fake.executed.append((self.table_name, self.field, self.cutoff))
        self.fake.filters.append((self.table_name, tuple(self.filters)))
        response = _Response(self.fake.counts[self.table_name])
        response.data = (
            [{"accession_no": f"acc-{index}"} for index in range(self.fake.counts[self.table_name])]
            if self.selected else None
        )
        return response


class _Supabase:
    def __init__(self) -> None:
        self.counts = {"segment_metrics": 12, "filings": 3, "filing_processing": 3}
        self.delete_options: list[tuple[str, dict]] = []
        self.executed: list[tuple[str, str, str]] = []
        self.filters: list[tuple[str, tuple]] = []

    def schema(self, name: str):
        if name != "fundamentals":
            raise AssertionError(name)
        return self

    def table(self, name: str) -> _Builder:
        return _Builder(self, name)


class SegmentsRetentionTest(unittest.TestCase):
    def test_backfill_cutoff_never_precedes_retention_window(self) -> None:
        today = date(2026, 8, 18)

        # 보존 하한보다 이른 요청은 하한으로 당긴다 — 적재하자마자 지워질 구간을
        # 받아 오느라 SEC를 두 번 훑는 일이 없어야 한다.
        self.assertEqual(
            backfill_history._segment_backfill_cutoff(
                "2016-01-01",
                today=today,
            ),
            date(2023, 8, 19),
        )
        # 창 안의 요청은 그대로 쓴다.
        self.assertEqual(
            backfill_history._segment_backfill_cutoff(
                "2024-01-01",
                today=today,
            ),
            date(2024, 1, 1),
        )

    def test_default_window_is_three_years(self) -> None:
        repository = SimpleNamespace(
            delete_history_before=mock.Mock(
                return_value={"metrics_deleted": 12, "processing_deleted": 3}
            )
        )

        result = backfill_history.prune_segment_history(
            repository,
            today=date(2026, 8, 18),
        )

        self.assertEqual(result, {"metrics_deleted": 12, "processing_deleted": 3})
        repository.delete_history_before.assert_called_once_with("2023-08-19")

    def test_child_metrics_are_deleted_before_parent_filings(self) -> None:
        fake = _Supabase()
        with mock.patch.object(segment_metrics, "sb", fake):
            result = segment_metrics.delete_history_before("2018-08-20")

        self.assertEqual(result, {"metrics_deleted": 12, "processing_deleted": 3})
        self.assertEqual(
            fake.executed,
            [
                ("segment_metrics", "period_end", "2018-08-20"),
                ("filings", "report_date", "2018-08-20"),
                ("filing_processing", "", ""),
            ],
        )
        self.assertEqual(
            fake.delete_options,
            [
                ("segment_metrics", {"count": "exact", "returning": "minimal"}),
                ("filing_processing", {"count": "exact", "returning": "minimal"}),
            ],
        )
        # company 공시 상태를 함께 지우면 안 된다 — 세그먼트 행만 골라 지운다.
        self.assertEqual(
            fake.filters,
            [
                ("segment_metrics", ()),
                ("filings", ()),
                ("filing_processing", (("content_type", "segments"),)),
            ],
        )

    def test_successful_sync_runs_retention(self) -> None:
        metrics = {
            "wide_rows": 1,
            "derived_q4_rows": 0,
            "filings": 1,
            "tickers": 1,
            "failures": [],
            "unmapped_concepts": set(),
        }
        with (
            mock.patch(
                "investment_agent.data.fundamentals.application.sync_recent_filings."
                "sync_segment_filings",
                return_value=metrics,
            ) as sync,
            mock.patch(
                "investment_agent.data.fundamentals.application.backfill_history."
                "prune_segment_history",
                return_value={"metrics_deleted": 0, "processing_deleted": 0},
            ) as prune,
        ):
            result = sync_job.main(
                [
                    "--content",
                    "segments",
                    "--period",
                    "quarter",
                    "--tickers",
                    "fdxf, HONA",
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(sync.call_args.kwargs["target_tickers"], {"FDXF", "HONA"})
        prune.assert_called_once_with(segment_metrics)

    def test_ticker_scope_and_watchlist_scope_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            sync_job._parse_args(
                [
                    "--content",
                    "segments",
                    "--period",
                    "quarter",
                    "--watchlist-only",
                    "--tickers",
                    "HONA",
                ]
            )

    def test_failed_sync_does_not_prune_history(self) -> None:
        metrics = {
            "wide_rows": 0,
            "derived_q4_rows": 0,
            "filings": 0,
            "tickers": 1,
            "failures": [{"error": "collection failed"}],
            "unmapped_concepts": set(),
        }
        with (
            mock.patch(
                "investment_agent.data.fundamentals.application.sync_recent_filings."
                "sync_segment_filings",
                return_value=metrics,
            ),
            mock.patch(
                "investment_agent.data.fundamentals.application.backfill_history."
                "prune_segment_history",
            ) as prune,
        ):
            result = sync_job.main(["--content", "segments", "--period", "quarter"])

        self.assertEqual(result, 1)
        prune.assert_not_called()


if __name__ == "__main__":
    unittest.main()
