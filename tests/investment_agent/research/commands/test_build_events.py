"""DuckDB 원문 → 사건 → 학습용 feature snapshot 배선을 검증한다."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from investment_agent.research.commands.build_events import build_events
from investment_agent.trading.evidence.cache import ExternalContent, LocalEvidenceCache

AS_OF = datetime(2026, 8, 20, tzinfo=timezone.utc)


class _Repository:
    def __init__(self) -> None:
        self.events: list = []
        self.snapshots: list = []

    def save_events(self, events) -> None:
        self.events.extend(events)

    def save_event_features(self, snapshots) -> None:
        self.snapshots.extend(snapshots)


def _item(*, symbol, title, content, days_ago: int, provider="yfinance", content_type="news"):
    fetched = AS_OF - timedelta(days=days_ago)
    return ExternalContent(
        provider=provider,
        content_type=content_type,
        symbol=symbol,
        published_at=fetched.isoformat(),
        fetched_at=fetched.isoformat(),
        url=f"https://example.com/{title.replace(' ', '-').lower()}",
        title=title,
        content=content,
        source=provider,
    )


class BuildEventsTest(unittest.TestCase):
    def _cache(self, temp: str) -> LocalEvidenceCache:
        cache = LocalEvidenceCache(Path(temp) / "cache.duckdb")
        cache.store([
            _item(
                symbol="AAPL", title="Apple beats on earnings", days_ago=1,
                content="Apple beat quarterly EPS and revenue estimates.",
            ),
            _item(
                symbol="AAPL", title="Apple lifts guidance", days_ago=2,
                content="Apple raised its full-year outlook and forecast.",
            ),
            _item(
                symbol="MSFT", title="Microsoft faces a lawsuit", days_ago=1,
                content="A court filing opened new litigation against Microsoft.",
            ),
        ])
        return cache

    def test_persists_events_and_one_feature_snapshot_per_ticker(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _Repository()

            result = build_events(
                cache=self._cache(temp),
                repository=repository,
                as_of_at=AS_OF.isoformat(),
                tickers=("AAPL", "MSFT"),
            )

            self.assertGreaterEqual(len(repository.events), 3)
            self.assertEqual(
                sorted(snapshot.ticker for snapshot in repository.snapshots), ["AAPL", "MSFT"]
            )
            self.assertEqual(result["events"], len(repository.events))
            self.assertEqual(result["snapshots"], 2)

    def test_untracked_ticker_is_dropped_before_the_foreign_key_can_reject_it(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _Repository()

            build_events(
                cache=self._cache(temp),
                repository=repository,
                as_of_at=AS_OF.isoformat(),
                tickers=("AAPL",),
            )

            self.assertEqual({event.ticker for event in repository.events}, {"AAPL"})
            self.assertEqual([snapshot.ticker for snapshot in repository.snapshots], ["AAPL"])

    def test_content_fetched_after_the_cutoff_never_reaches_an_event(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = LocalEvidenceCache(Path(temp) / "cache.duckdb")
            future = AS_OF + timedelta(days=1)
            cache.store([
                _item(symbol="AAPL", title="Apple beats on earnings", days_ago=1,
                      content="Apple beat quarterly EPS estimates."),
                ExternalContent(
                    provider="yfinance", content_type="news", symbol="AAPL",
                    published_at=future.isoformat(), fetched_at=future.isoformat(),
                    url="https://example.com/leak", title="Tomorrow's headline",
                    content="This was collected after the cutoff.", source="yfinance",
                ),
            ])
            repository = _Repository()

            build_events(
                cache=cache,
                repository=repository,
                as_of_at=AS_OF.isoformat(),
                tickers=("AAPL",),
            )

            joined = " ".join(
                str(value) for event in repository.events for value in event.evidence_ids
            )
            self.assertEqual(len(repository.events), 1)
            self.assertNotIn("leak", joined)

    def test_dry_run_computes_without_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            repository = _Repository()

            result = build_events(
                cache=self._cache(temp),
                repository=repository,
                as_of_at=AS_OF.isoformat(),
                tickers=("AAPL", "MSFT"),
                dry_run=True,
            )

            self.assertEqual(repository.events, [])
            self.assertEqual(repository.snapshots, [])
            self.assertGreater(result["events"], 0)


if __name__ == "__main__":
    unittest.main()
