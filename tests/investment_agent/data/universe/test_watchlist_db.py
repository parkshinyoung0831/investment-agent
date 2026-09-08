"""watchlists/db.py의 공개 함수가 injectable Database로도 같은 값을 주는지
굳힌다. 관심은 발행사(CIK) 단위로 저장하고 표시만 대표 종목 ticker로 한다."""
from __future__ import annotations

import unittest

from investment_agent.data.universe.watchlists import db as watchlist_db
from investment_agent.data.universe.repository import SCHEMA, T_ENTITIES, T_SECURITIES
from tests.investment_agent.fakes import FakeDatabase

CIK_AAPL = "0000320193"
CIK_MSFT = "0000789019"
CIK_NVDA = "0001045810"


def _security(security_id: int, ticker: str, cik: str, *, tracked: bool) -> dict:
    return {"security_id": security_id, "ticker": ticker, "cik": cik, "is_tracked": tracked}


def _entity(cik: str, sources: list[str], *, removed_at: str | None = None) -> dict:
    return {
        "cik": cik,
        "watchlist_sources": sources,
        "is_watchlisted": bool(sources),
        "watch_from": "2026-01-01",
        "watchlist_removed_at": removed_at,
    }


class ActiveMembersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeDatabase()
        self.fake.put(SCHEMA, T_SECURITIES, [
            _security(1, "AAPL", CIK_AAPL, tracked=True),
            _security(2, "MSFT", CIK_MSFT, tracked=True),
        ])
        self.fake.put(SCHEMA, T_ENTITIES, [
            _entity(CIK_AAPL, ["manual"]),
            _entity(CIK_MSFT, [], removed_at="2026-02-01T00:00:00Z"),
        ])
        watchlist_db.configure(self.fake)
        self.addCleanup(watchlist_db.configure, None)

    def test_active_members_excludes_removed(self) -> None:
        rows = watchlist_db.active_members()
        self.assertEqual(["AAPL"], [row["ticker"] for row in rows])

    def test_list_members_include_inactive_returns_everything(self) -> None:
        rows = watchlist_db.list_members(include_inactive=True)
        self.assertEqual({"AAPL", "MSFT"}, {row["ticker"] for row in rows})

    def test_a_company_never_watched_stays_out_of_the_inactive_listing(self) -> None:
        """해제 이력조차 없는 회사까지 내면 전 종목이 목록에 들어온다."""
        self.fake.put(SCHEMA, T_ENTITIES, [
            _entity(CIK_AAPL, ["manual"]),
            _entity(CIK_MSFT, []),
        ])
        rows = watchlist_db.list_members(include_inactive=True)
        self.assertEqual(["AAPL"], [row["ticker"] for row in rows])


class AddRemoveMemberTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeDatabase()
        self.fake.put(SCHEMA, T_SECURITIES, [_security(5, "NVDA", CIK_NVDA, tracked=True)])
        self.fake.put(SCHEMA, T_ENTITIES, [])
        watchlist_db.configure(self.fake)
        self.addCleanup(watchlist_db.configure, None)

    def test_add_member_updates_the_issuer_row_with_manual_source(self) -> None:
        cik = watchlist_db.add_member("nvda")
        self.assertEqual(CIK_NVDA, cik)
        (_key, values) = self.fake.updates[0]
        (_key2, terms) = self.fake.update_filters[0]
        self.assertEqual({"cik": CIK_NVDA}, terms, "한 발행사만 골라야 한다")
        self.assertEqual(["manual"], values["watchlist_sources"])

    def test_add_member_writes_no_company_facts(self) -> None:
        """관심 갱신이 SEC metadata 수집 결과를 덮어쓰면 회사 이름이 사라진다."""
        watchlist_db.add_member("NVDA")
        (_key, values) = self.fake.updates[0]
        self.assertEqual(
            {"watchlist_sources", "watch_from", "watchlist_removed_at"}, set(values),
        )

    def test_add_member_rejects_an_untracked_ticker(self) -> None:
        self.fake.put(SCHEMA, T_SECURITIES, [_security(6, "DEAD", "0000000006", tracked=False)])
        with self.assertRaises(ValueError):
            watchlist_db.add_member("DEAD")


class SyncTossMembersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeDatabase()
        self.fake.put(SCHEMA, T_SECURITIES, [
            _security(1, "AAPL", CIK_AAPL, tracked=True),
            _security(2, "MSFT", CIK_MSFT, tracked=True),
        ])
        self.fake.put(SCHEMA, T_ENTITIES, [_entity(CIK_AAPL, ["toss"])])
        watchlist_db.configure(self.fake)
        self.addCleanup(watchlist_db.configure, None)

    def test_adds_new_holdings_and_drops_the_toss_source_from_missing_ones(self) -> None:
        result = watchlist_db.sync_toss_members(["MSFT"])
        self.assertEqual(1, result["added"])
        self.assertEqual(1, result["removed"])
        written = {
            terms["cik"]: values
            for (_k, values), (_k2, terms) in zip(self.fake.updates, self.fake.update_filters)
        }
        self.assertEqual([], written[CIK_AAPL]["watchlist_sources"])
        self.assertEqual(["toss"], written[CIK_MSFT]["watchlist_sources"])

    def test_two_share_classes_of_one_issuer_are_a_single_watchlisted_company(self) -> None:
        """보유는 종목 단위로 오지만 관심 기업은 하나여야 한다."""
        self.fake.put(SCHEMA, T_SECURITIES, [
            _security(3, "GOOG", "0001652044", tracked=True),
            _security(4, "GOOGL", "0001652044", tracked=True),
        ])
        self.fake.put(SCHEMA, T_ENTITIES, [])
        result = watchlist_db.sync_toss_members(["GOOG", "GOOGL"])
        self.assertEqual(1, result["active"])
        self.assertEqual(1, result["added"])
        self.assertEqual(
            ["0001652044"], [terms["cik"] for (_k, terms) in self.fake.update_filters]
        )


if __name__ == "__main__":
    unittest.main()
