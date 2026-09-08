"""예상치 전체 수집의 일괄 저장·예산 폐기를 검증한다."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from threading import Barrier
from unittest.mock import patch

from investment_agent.data.fundamentals.application.analyst_coverage import (
    changed_analyst_snapshots,
)
from investment_agent.data.fundamentals.application.refresh_expectations import (
    refresh_expectations,
)
from investment_agent.data.fundamentals.commands.refresh_expectations import _parse_args
from investment_agent.data.fundamentals.infrastructure.supabase import expectations as db_expectations


class _Source:
    def __init__(self) -> None:
        self.called: list[str] = []

    def fetch_consensus(self, ticker: str, *, today: date) -> dict:
        self.called.append(ticker)
        return {
            "snapshots": [{
                "ticker": ticker,
                "snapshot_date": today.isoformat(),
                "horizon": "q+0",
                "target_period_end": "2026-09-30",
            }],
            "trend_seed": [],
            "analyst_snapshot": {
                "ticker": ticker,
                "snapshot_date": today.isoformat(),
                "source": "yfinance",
                "target_mean": 100.0,
                "target_median": 99.0,
                "target_high": 120.0,
                "target_low": 80.0,
                "strong_buy": 4,
                "buy": 6,
                "hold": 2,
                "sell": 1,
                "strong_sell": 0,
            },
        }


class _Repository:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, list[dict]]] = []
        self.latest: list[dict] = []
        self.pruned = 0
        self.period_pruned = 0

    def tickers_missing_consensus(self, _tickers: list[str]) -> set[str]:
        return set()

    def fiscal_periods(self, tickers: list[str]) -> list[dict]:
        return [{
            "ticker": ticker,
            "fiscal_year": 2026,
            "fiscal_period": "Q3",
            "period_end": "2026-09-30",
        } for ticker in tickers]

    def latest_analyst_snapshots(self, _tickers: list[str]) -> list[dict]:
        return self.latest

    def upsert_consensus(self, rows: list[dict]) -> int:
        self.upserts.append(("consensus", rows))
        return len(rows)

    def upsert_schedules(self, rows: list[dict]) -> int:
        self.upserts.append(("schedules", rows))
        return len(rows)

    def upsert_analyst_snapshots(self, rows: list[dict]) -> int:
        self.upserts.append(("analyst", rows))
        return len(rows)

    def prune_earnings_estimates(self, days: int = 1095) -> dict:
        self.pruned += 1
        return {
            "cutoff": "2023-08-28",
            "consensus_deleted": 0,
            "days": days,
        }

    def prune_expectation_snapshots(self, recent_days: int = 180) -> dict:
        self.period_pruned += 1
        return {"estimates_deleted": 3, "schedules_deleted": 2, "consensus_deleted": 0}


class RefreshExpectationsTest(unittest.TestCase):
    _TODAY = date(2026, 8, 27)

    def test_default_scope_is_all_with_a_collection_budget(self) -> None:
        args = _parse_args(["--workers", "4"])

        self.assertEqual(args.scope, "all")
        self.assertEqual(args.collection_budget_sec, 1500)
        self.assertEqual(args.workers, 4)

    def test_negative_collection_budget_is_rejected_by_argparse(self) -> None:
        with self.assertRaises(SystemExit):
            _parse_args(["--collection-budget-sec", "-1"])

    def test_worker_count_is_bounded(self) -> None:
        for invalid in ("0", "17"):
            with self.subTest(invalid=invalid), self.assertRaises(SystemExit):
                _parse_args(["--workers", invalid])

    def test_budget_exceeded_discards_all_collected_rows_before_upsert(self) -> None:
        source = _Source()
        repository = _Repository()
        readings = iter((0.0, 0.0, 31.0))

        metrics = refresh_expectations(
            ["AAA", "BBB"],
            source=source,
            expectations_repository=repository,
            today=self._TODAY,
            request_gap_sec=0,
            collection_budget_sec=30,
            monotonic=lambda: next(readings),
        )

        self.assertNotIn("BBB", source.called)
        self.assertEqual(repository.upserts, [])
        self.assertEqual(repository.pruned, 0)
        self.assertTrue(metrics["discarded"])
        self.assertEqual(metrics["rows"], 0)
        self.assertEqual(metrics["failures"][0]["type"], "collection_budget_exceeded")

    def test_completed_collection_upserts_once_after_all_tickers_are_fetched(self) -> None:
        source = _Source()
        repository = _Repository()

        metrics = refresh_expectations(
            ["AAA", "BBB"],
            source=source,
            expectations_repository=repository,
            today=self._TODAY,
            request_gap_sec=0,
            collection_budget_sec=30,
            monotonic=lambda: 0.0,
        )

        self.assertEqual(source.called, ["AAA", "BBB"])
        self.assertFalse(metrics.get("discarded", False))
        self.assertGreater(metrics["rows"], 0)
        self.assertEqual([name for name, _rows in repository.upserts], [
            "consensus", "schedules", "analyst",
        ])
        self.assertEqual(repository.pruned, 1)
        # 나이 기준 정리와 발표 기준 정리는 서로를 대신하지 못한다 — 둘 다 돌아야 한다.
        self.assertEqual(repository.period_pruned, 1)
        self.assertEqual(metrics["retention"]["consensus_deleted"], 0)
        self.assertEqual(metrics["retention"]["estimates_deleted"], 3)
        self.assertEqual(metrics["retention"]["schedules_deleted"], 2)
        # 정리 단계가 조용히 실패하면 여기 failure로만 남고 지표는 그대로 0이 된다.
        self.assertEqual([], [item for item in metrics["failures"]
                              if item.get("stage") == "consensus_retention"])

    def test_collection_uses_the_configured_bounded_concurrency(self) -> None:
        barrier = Barrier(2)

        class ConcurrentSource(_Source):
            def fetch_consensus(self, ticker: str, *, today: date) -> dict:
                barrier.wait(timeout=2)
                return super().fetch_consensus(ticker, today=today)

        source = ConcurrentSource()
        repository = _Repository()
        metrics = refresh_expectations(
            ["AAA", "BBB"],
            source=source,
            expectations_repository=repository,
            today=self._TODAY,
            request_gap_sec=0,
            max_workers=2,
        )

        self.assertEqual(set(source.called), {"AAA", "BBB"})
        self.assertEqual(metrics["tickers"], 2)

    def test_partial_provider_failure_is_persisted_but_fails_the_run(self) -> None:
        class PartialSource(_Source):
            def fetch_consensus(self, ticker: str, *, today: date) -> dict:
                result = super().fetch_consensus(ticker, today=today)
                result["source_failures"] = [
                    {"stage": "calendar", "error": "RuntimeError('unavailable')"}
                ]
                return result

        source = PartialSource()
        repository = _Repository()
        metrics = refresh_expectations(
            ["AAA"],
            source=source,
            expectations_repository=repository,
            today=self._TODAY,
            request_gap_sec=0,
        )

        self.assertGreater(metrics["rows"], 0)
        self.assertEqual(metrics["failures"][0]["ticker"], "AAA")
        self.assertEqual(metrics["failures"][0]["stage"], "calendar")
        self.assertEqual(repository.pruned, 0)

    def test_unchanged_analyst_coverage_does_not_create_a_daily_row(self) -> None:
        source = _Source()
        repository = _Repository()
        repository.latest = [source.fetch_consensus("AAA", today=self._TODAY)["analyst_snapshot"]]

        metrics = refresh_expectations(
            ["AAA"],
            source=source,
            expectations_repository=repository,
            today=self._TODAY,
            request_gap_sec=0,
        )

        analyst_rows = next(rows for name, rows in repository.upserts if name == "analyst")
        self.assertEqual(analyst_rows, [])
        self.assertEqual(metrics["counts"]["analyst_coverage"], 0)

    def test_changed_analyst_coverage_keeps_only_the_changed_ticker(self) -> None:
        snapshots = [
            {"ticker": "AAA", "source": "yfinance", "target_mean": 100.0},
            {"ticker": "BBB", "source": "yfinance", "target_mean": 120.0},
        ]
        latest = [
            {"ticker": "AAA", "source": "yfinance", "target_mean": 100.0},
            {"ticker": "BBB", "source": "yfinance", "target_mean": 110.0},
        ]

        changed = changed_analyst_snapshots(snapshots, latest)

        self.assertEqual([row["ticker"] for row in changed], ["BBB"])


class ExpectationsRepositoryPagingTest(unittest.TestCase):
    def test_point_in_time_fundamentals_exclude_late_availability(self) -> None:
        """canonical 정책은 우리 처리 시각(ingested_at)이 아니라 공시 자체의
        provenance(source_filing_date + filings.available_at)로 PIT 경계를 긋는다."""
        as_of_at = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
        versions = [
            {
                "cik": "0000000001",
                "source_accession_no": "0001",
                "period_end": "2026-06-30",
                "source_filing_date": "2026-08-01",
                "revenue": 100,
            },
            {
                "cik": "0000000001",
                "source_accession_no": "0002",
                "period_end": "2026-03-31",
                # filing_date 자체는 cutoff 이전이지만, 실제로 공개된(available_at)
                # 시각은 cutoff 이후다 — 늦게 알려진 공시는 제외해야 한다.
                "source_filing_date": "2026-07-01",
                "revenue": 90,
            },
        ]
        filings = [
            {"accession_no": "0001", "filing_date": "2026-08-01", "available_at": "2026-08-01T12:00:00+00:00", "form_type": "10-Q"},
            {"accession_no": "0002", "filing_date": "2026-07-01", "available_at": "2026-09-01T12:00:00+00:00", "form_type": "10-Q"},
        ]
        with patch.object(
            db_expectations,
            "select_all_paged",
            side_effect=[[{"ticker": "AAA", "cik": "0000000001"}], versions, filings],
        ):
            rows = db_expectations.security_fundamentals_as_of("AAA", as_of_at)

        self.assertEqual([row["accession_no"] for row in rows], ["0001"])

    def test_fiscal_calendar_pages_use_the_full_primary_key_order(self) -> None:
        with patch.object(
            db_expectations,
            "select_all_paged",
            side_effect=[[{"ticker": "AAA", "cik": "0000000001"}], []],
        ) as paged:
            db_expectations.fiscal_periods(["AAA"])

        self.assertEqual(
            paged.call_args_list[-1].kwargs["order_by"],
            "cik,fiscal_year,fiscal_period,period_end",
        )

    def test_existing_consensus_pages_use_the_full_primary_key_order(self) -> None:
        with patch.object(
            db_expectations,
            "select_all_paged",
            side_effect=[[{"ticker": "AAA", "security_id": 1}], []],
        ) as paged:
            db_expectations.tickers_missing_consensus(["AAA"])

        self.assertEqual(
            paged.call_args_list[-1].kwargs["order_by"],
            "security_id",
        )


if __name__ == "__main__":
    unittest.main()
