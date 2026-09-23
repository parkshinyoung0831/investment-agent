"""로컬 사본: Supabase 경로와 같은 결과, 증분·분할 재수집, 오래된 사본 거부, repository의 사본 우선 읽기."""
from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from investment_agent.data.market.local_mirror.store import LocalMirror
from investment_agent.data.market.local_mirror.sync import MirrorSource, sync_local_mirror
from investment_agent.data.market import persistence as market_db
from investment_agent.data.market.domain.models import DailyBar, DividendEvent, SplitEvent
from investment_agent.data.universe.domain.memberships import membership_snapshots

UTC = timezone.utc
NOW = datetime(2026, 9, 15, 23, 0, tzinfo=UTC)


def _bars(security_id: int, start: date, end: date, *, scale: float = 1.0) -> list[dict]:
    rows, day = [], start
    while day <= end:
        if day.weekday() < 5:
            price = scale * (100.0 + (day.toordinal() % 17))
            rows.append({"security_id": security_id, "trade_date": day.isoformat(), "open": price, "high": price,
                         "low": price, "close": price, "volume": 1_000 + security_id, "is_repaired": False})
        day += timedelta(days=1)
    return rows


class _World:
    """원본 창고 한 벌. Supabase owner 함수와 사본 동기화가 같은 사실을 읽는다."""

    def __init__(self):
        self.securities = [
            {"security_id": 1, "ticker": "AAA", "cik": "1", "is_active_listing": True, "is_identity_verified": True, "is_tracked": True},
            {"security_id": 2, "ticker": "BBB", "cik": "2", "is_active_listing": True, "is_identity_verified": True, "is_tracked": True},
            # 같은 ticker의 옛 자리표시 증권. 해석은 상장 중인 쪽이다.
            {"security_id": 3, "ticker": "AAA", "cik": None, "is_active_listing": False, "is_identity_verified": False, "is_tracked": False},
            {"security_id": 4, "ticker": "SPY", "cik": None, "is_active_listing": True, "is_identity_verified": True, "is_tracked": False},
        ]
        self.bars = {1: _bars(1, date(2025, 1, 1), date(2026, 9, 15)), 2: _bars(2, date(2025, 6, 1), date(2026, 9, 15)),
                     3: _bars(3, date(2020, 1, 1), date(2021, 1, 1)), 4: _bars(4, date(2025, 1, 1), date(2026, 9, 15))}
        self.dividends = [DividendEvent(1, date(2026, 3, 2), 0.5), DividendEvent(1, date(2026, 6, 1), 0.5)]
        self.splits = [SplitEvent(2, date(2026, 1, 5), 2.0)]
        self.bar_calls: list[tuple[tuple[int, ...], date]] = []

    def market_repository(self, db=None):
        world = self

        class Repository:
            def __init__(self, db):
                pass

            def bars(self, security_ids, *, start, end, known_at=None):
                world.bar_calls.append((tuple(sorted(security_ids)), start))
                return [DailyBar.from_row(row) for security_id in security_ids for row in world.bars.get(int(security_id), [])
                        if start.isoformat() <= row["trade_date"] <= end.isoformat()]

            def dividends(self, security_ids, since=None):
                return [event for event in world.dividends if event.security_id in set(security_ids)
                        and (since is None or event.ex_date >= since)]

            def splits(self, security_ids, since=None):
                return [event for event in world.splits if event.security_id in set(security_ids)
                        and (since is None or event.action_date >= since)]

        return Repository

    def source(self) -> MirrorSource:
        return MirrorSource(
            securities=lambda: [dict(row) for row in self.securities],
            memberships=lambda: [],
            profiles=lambda tickers: [{"ticker": ticker, "sic_division": "Manufacturing"} for ticker in tickers],
            bars=market_db.bars_for_securities,
            actions=market_db.actions_for_securities,
            reference_tickers=("SPY",),
        )


class LocalMirrorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = _World()
        patcher = mock.patch.object(market_db, "MarketRepository", self.world.market_repository())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.mirror = LocalMirror(Path(self.tmp.name) / "mirror")

    def sync(self, **kwargs):
        return sync_local_mirror(mirror=self.mirror, source=self.world.source(), **kwargs)

    def test_price_history_equals_the_supabase_path(self):
        self.sync(now=NOW)
        ids = {"AAA": 1, "BBB": 2, "SPY": 4}
        with mock.patch.object(market_db, "_ids", side_effect=lambda tickers: {t.upper(): ids[t.upper()] for t in tickers if t.upper() in ids}):
            for ticker in ("AAA", "BBB", "SPY", "aaa"):
                for as_of, limit in ((NOW, 260), (datetime(2026, 1, 6, 23, tzinfo=UTC), 30), (datetime(2025, 7, 1, 23, tzinfo=UTC), 500)):
                    with self.subTest(ticker=ticker, as_of=as_of, limit=limit):
                        expected = market_db.price_history_as_of(ticker, as_of, limit=limit)
                        self.assertTrue(expected)
                        self.assertEqual(self.mirror.price_history_as_of(ticker, as_of, limit=limit), expected)
            self.assertEqual(self.mirror.price_history_as_of("ZZZ", NOW), market_db.price_history_as_of("ZZZ", NOW))
        # 배당·분할이 같은 날의 가격 행에 붙는다.
        rows = self.mirror.price_history_as_of("BBB", datetime(2026, 1, 6, 23, tzinfo=UTC), limit=3)
        self.assertEqual(rows[-2]["split_ratio"], 2.0)

    def test_tickers_resolve_to_the_preferred_security_and_sector_is_for_tracked_names(self):
        self.sync(now=NOW)
        self.assertEqual(self.mirror.security_ids(["AAA", "SPY"]), {"AAA": 1, "SPY": 4})
        self.assertEqual(self.mirror.tracked_tickers(), ["AAA", "BBB"])
        self.assertEqual(self.mirror.sector_map(["AAA", "SPY"]), {"AAA": "Manufacturing"})

    def test_label_close_window_reads_all_requested_tickers_in_one_frame(self):
        self.sync(now=NOW)
        rows = self.mirror.closes_between(
            ["AAA", "BBB"], start=date(2026, 1, 2), end=date(2026, 1, 7),
        )
        self.assertEqual({row["ticker"] for row in rows}, {"AAA", "BBB"})
        self.assertTrue(all("2026-01-02" <= row["trade_date"] <= "2026-01-07" for row in rows))
        self.assertEqual(rows, sorted(rows, key=lambda row: (row["ticker"], row["trade_date"])))

    def test_incremental_sync_refetches_only_the_window_new_names_and_new_splits(self):
        self.sync(now=NOW)
        self.world.bar_calls.clear()
        # 새 추적 종목과 창 안의 새 분할, 창 안의 가격 정정.
        self.world.securities.append({"security_id": 5, "ticker": "CCC", "cik": "5", "is_active_listing": True,
                                      "is_identity_verified": True, "is_tracked": True})
        self.world.bars[5] = _bars(5, date(2024, 1, 1), date(2026, 9, 16))
        self.world.splits.append(SplitEvent(1, date(2026, 9, 14), 4.0))
        self.world.bars[1] = _bars(1, date(2025, 1, 1), date(2026, 9, 16), scale=0.25)
        self.world.bars[2][-1] = {**self.world.bars[2][-1], "close": 999.0, "high": 999.0}
        later = NOW + timedelta(days=1)
        result = self.sync(now=later)
        self.assertFalse(result.is_full)
        full_fetch = [ids for ids, start in self.world.bar_calls if start == date(1900, 1, 1)]
        window_fetch = [ids for ids, start in self.world.bar_calls if start != date(1900, 1, 1)]
        self.assertEqual(full_fetch, [(1, 5)])      # 분할 난 AAA와 새 CCC만 전체 이력
        self.assertEqual(window_fetch, [(2, 4)])    # 나머지는 최근 창만
        rows = self.mirror.price_history_as_of("AAA", later, limit=400)
        self.assertAlmostEqual(rows[0]["close"], 0.25 * (100.0 + (date.fromisoformat(rows[0]["trade_date"]).toordinal() % 17)))
        self.assertEqual(self.mirror.price_history_as_of("BBB", NOW, limit=1)[0]["close"], 999.0)
        self.assertTrue(self.mirror.price_history_as_of("CCC", later, limit=5))

    def test_a_stale_mirror_does_not_answer_the_present_but_still_answers_the_past(self):
        self.assertFalse(self.mirror.covers(NOW))  # 사본이 없다
        self.sync(now=NOW)
        self.assertTrue(self.mirror.covers(NOW - timedelta(days=300), now=NOW + timedelta(days=10)))
        self.assertTrue(self.mirror.covers(NOW + timedelta(hours=2), now=NOW + timedelta(hours=2)))
        self.assertFalse(self.mirror.covers(NOW + timedelta(days=2), now=NOW + timedelta(days=2)))

    def test_weekly_full_sync_is_automatic(self):
        self.assertTrue(self.sync(now=NOW).is_full)
        self.assertFalse(self.sync(now=NOW + timedelta(days=1)).is_full)
        self.assertTrue(self.sync(now=NOW + timedelta(days=8)).is_full)

    def test_a_former_member_on_a_placeholder_row_still_gets_its_real_prices(self):
        """멤버십이 자리표시 증권을 가리켜도 ticker 조회는 확인된 증권으로 풀린다 — 그 가격이 사본에 있어야 한다."""
        self.world.securities += [
            {"security_id": 5, "ticker": "OLD", "cik": "5", "is_active_listing": True, "is_identity_verified": True,
             "is_tracked": False},
            {"security_id": 6, "ticker": "OLD", "cik": None, "is_active_listing": False, "is_identity_verified": False,
             "is_tracked": False},
        ]
        self.world.bars[5] = _bars(5, date(2021, 1, 1), date(2026, 9, 15))
        memberships = [{"security_id": 6, "ticker": "OLD", "valid_from": "2015-01-01", "valid_to": "2024-09-23"}]
        source = MirrorSource(**{**self.world.source().__dict__, "memberships": lambda: memberships})
        sync_local_mirror(mirror=self.mirror, source=source, now=NOW)
        self.assertTrue(self.mirror.price_history_as_of("OLD", datetime(2022, 1, 5, 23, tzinfo=UTC), limit=5))

    def test_a_renamed_former_member_gets_the_prices_of_its_current_symbol(self):
        """멤버십에는 옛 표기(GPS)만 있다. 재현 유니버스는 현재 표기(GAP)로 풀므로 그 가격이 사본에 있어야 한다."""
        self.world.securities.append({"security_id": 7, "ticker": "GAP", "cik": "7", "is_active_listing": True,
                                      "is_identity_verified": True, "is_tracked": False})
        self.world.bars[7] = _bars(7, date(2021, 1, 1), date(2026, 9, 15))
        memberships = [{"security_id": 8, "ticker": "GPS", "valid_from": "2015-01-01", "valid_to": "2024-08-01"}]
        source = MirrorSource(**{**self.world.source().__dict__, "memberships": lambda: memberships})
        sync_local_mirror(mirror=self.mirror, source=source, now=NOW)
        self.assertTrue(self.mirror.price_history_as_of("GAP", datetime(2022, 1, 5, 23, tzinfo=UTC), limit=5))

    def test_membership_snapshots_use_the_same_rule_as_supabase(self):
        rows = [{"security_id": index, "ticker": f"T{index}", "valid_from": "2020-01-01",
                 "valid_to": "2026-03-01" if index == 0 else None} for index in range(501)]
        rows.append({"security_id": 999, "ticker": "NEW", "valid_from": "2026-03-01", "valid_to": None})
        world_source = self.world.source()
        source = MirrorSource(**{**world_source.__dict__, "memberships": lambda: rows})
        sync_local_mirror(mirror=self.mirror, source=source, now=NOW)
        window = dict(start_date=date(2026, 1, 1), end_date=date(2026, 6, 1))
        self.assertEqual(self.mirror.membership_snapshots(**window), membership_snapshots(rows, **window))
        self.assertEqual([snapshot["effective_date"] for snapshot in self.mirror.membership_snapshots(**window)],
                         ["2026-01-01", "2026-03-01"])


class RepositoryPrefersTheMirrorTest(unittest.TestCase):
    def test_fresh_mirror_answers_and_missing_mirror_falls_back_to_supabase(self):
        from investment_agent.research.evidence import reader as module

        repository = module.PitReader()
        with mock.patch.object(module.market_db, "price_history_as_of", return_value=[{"from": "supabase"}]) as remote:
            self.assertEqual(repository.market_prices("AAA", NOW), [{"from": "supabase"}])
            self.assertEqual(remote.call_count, 1)
        fake = mock.Mock()
        fake.covers.return_value = True
        fake.price_history_as_of.return_value = [{"from": "mirror"}]
        fake.tracked_tickers.return_value = ["AAA"]
        repository._reader_cache().__dict__["_local_mirror"] = fake
        with mock.patch.object(module.market_db, "price_history_as_of", side_effect=AssertionError("remote read")), \
                mock.patch.object(module, "select_tracked_tickers", side_effect=AssertionError("remote read")):
            self.assertEqual(repository.market_prices("AAA", NOW + timedelta(minutes=1)), [{"from": "mirror"}])
            self.assertEqual(repository.current_tracked_tickers(), ["AAA"])
        fake.covers.return_value = False
        with mock.patch.object(module.market_db, "price_history_as_of", return_value=[{"from": "supabase"}]):
            self.assertEqual(repository.market_prices("AAA", NOW + timedelta(minutes=2)), [{"from": "supabase"}])


if __name__ == "__main__":
    unittest.main()
