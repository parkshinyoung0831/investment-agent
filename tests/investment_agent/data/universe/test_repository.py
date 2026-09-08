"""universe 저장소가 조용히 잘리거나 잘못 합치지 않는지 본다."""
from __future__ import annotations

import unittest
from datetime import date

from investment_agent.data.universe.domain.models import MembershipSnapshot
from investment_agent.data.universe.repository import (
    INDEX_SP500,
    RPC_REPLACE_MEMBERSHIP,
    SCHEMA,
    T_IDENTIFIERS,
    T_MEMBERSHIPS,
    T_ENTITIES,
    T_SECURITIES,
    UniverseRepository,
)
from investment_agent.platform.db.postgres import READ_PAGE_SIZE
from tests.investment_agent.fakes import FakeDatabase


def _security(security_id: int, ticker: str, *, tracked: bool = True) -> dict:
    return {
        "security_id": security_id,
        "ticker": ticker,
        "cik": f"{security_id:010d}",
        "exchange_code": "XNAS",
        "security_type": "common_stock",
        "is_active_listing": True,
        "is_tracked": tracked,
    }


def _membership_row(index_code: str, security_id: int, ticker: str, valid_from: str,
                     valid_to: str | None, *, source: str = "wikipedia") -> dict:
    return {
        "index_code": index_code, "valid_from": valid_from, "valid_to": valid_to,
        "source": source, T_SECURITIES: {"ticker": ticker},
    }


class TrackedSecuritiesTest(unittest.TestCase):
    def test_only_tracked_securities_are_returned(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_SECURITIES, [
            _security(1, "AAPL"),
            _security(2, "MSFT"),
            _security(3, "DEAD", tracked=False),
        ])
        self.assertEqual(["AAPL", "MSFT"], UniverseRepository(db).tracked_tickers())

    def test_more_than_one_page_is_read_completely(self) -> None:
        """1,000행에서 잘리면 그 뒤 종목이 통째로 사라지는데 에러는 안 난다."""
        db = FakeDatabase()
        db.put(SCHEMA, T_SECURITIES, [
            _security(i, f"T{i:05d}") for i in range(READ_PAGE_SIZE + 25)
        ])
        self.assertEqual(READ_PAGE_SIZE + 25, len(UniverseRepository(db).tracked_securities()))


class SecurityLookupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.db.put(SCHEMA, T_SECURITIES, [_security(1, "AAPL"), _security(2, "BRK-B")])
        self.repo = UniverseRepository(self.db)

    def test_input_forms_are_normalised_before_lookup(self) -> None:
        found = self.repo.security_ids(["aapl", "BRK.B"])
        self.assertEqual({"AAPL": 1, "BRK-B": 2}, found)

    def test_unknown_tickers_are_absent_not_none(self) -> None:
        """빈 껍데기를 만들면 부르는 쪽이 '있는데 값이 없다'로 읽는다."""
        self.assertEqual({"AAPL": 1}, self.repo.security_ids(["AAPL", "NOPE"]))

    def test_empty_input_never_touches_the_store(self) -> None:
        self.assertEqual({}, self.repo.security_ids([]))
        self.assertEqual([], self.db.executed)

    def test_long_ticker_lists_are_split(self) -> None:
        """PostgREST는 in 목록을 URL에 싣는다 — 길면 행 상한과 다른 벽에 걸린다."""
        tickers = [f"T{i:04d}" for i in range(250)]
        self.db.put(SCHEMA, T_SECURITIES, [_security(i, t) for i, t in enumerate(tickers, 1)])
        self.assertEqual(250, len(self.repo.securities_by_ticker(tickers)))
        self.assertEqual(3, len(self.db.in_calls))


class AllSecuritiesTest(unittest.TestCase):
    def test_returns_every_security_regardless_of_tracked_status(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_SECURITIES, [
            _security(1, "AAPL", tracked=True),
            _security(2, "DEAD", tracked=False),
        ])
        tickers = {s.ticker for s in UniverseRepository(db).all_securities()}
        self.assertEqual({"AAPL", "DEAD"}, tickers)


class TickersBySecurityIdTest(unittest.TestCase):
    def test_maps_security_id_back_to_current_ticker(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_SECURITIES, [_security(1, "AAPL"), _security(2, "MSFT")])
        self.assertEqual(
            {1: "AAPL", 2: "MSFT"},
            UniverseRepository(db).tickers_by_security_id([1, 2, 999]),
        )

    def test_empty_input_never_touches_the_store(self) -> None:
        db = FakeDatabase()
        self.assertEqual({}, UniverseRepository(db).tickers_by_security_id([]))
        self.assertEqual([], db.executed)


class ResolveIdentifiersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.db.put(SCHEMA, T_IDENTIFIERS, [
            # 같은 ticker가 두 회사에 쓰였다. 시점이 없으면 어느 쪽인지 알 수 없다.
            {"identifier": "TWTR", "identifier_type": "TICKER", "security_id": 10,
             "valid_from": "2013-11-07", "valid_to": "2022-10-27"},
            {"identifier": "TWTR", "identifier_type": "TICKER", "security_id": 11,
             "valid_from": "2024-01-01", "valid_to": None},
            {"identifier": "037833100", "identifier_type": "CUSIP", "security_id": 1,
             "valid_from": "-infinity", "valid_to": None},
            # 못 찾은 식별자도 저장소에 남아 있다. 매핑 결과에는 나오면 안 된다.
            {"identifier": "999999999", "identifier_type": "CUSIP", "security_id": None,
             "valid_from": "-infinity", "valid_to": None},
        ])
        self.repo = UniverseRepository(self.db)

    def test_cusip_maps_to_security_id(self) -> None:
        self.assertEqual({"037833100": 1}, self.repo.resolve_identifiers(["037833100"], "CUSIP"))

    def test_unmapped_identifiers_are_not_returned(self) -> None:
        self.assertEqual({}, self.repo.resolve_identifiers(["999999999"], "CUSIP"))

    def test_a_reused_ticker_resolves_by_the_date_asked_for(self) -> None:
        """시점 없이 매핑하면 서로 다른 회사가 한 종목으로 합쳐진다."""
        self.assertEqual(
            {"TWTR": 10},
            self.repo.resolve_identifiers(["TWTR"], "TICKER", on_date=date(2020, 6, 1)),
        )
        self.assertEqual(
            {"TWTR": 11},
            self.repo.resolve_identifiers(["TWTR"], "TICKER", on_date=date(2025, 6, 1)),
        )

    def test_a_date_in_the_gap_resolves_to_nothing(self) -> None:
        self.assertEqual(
            {}, self.repo.resolve_identifiers(["TWTR"], "TICKER", on_date=date(2023, 6, 1))
        )

    def test_case_and_padding_are_normalised(self) -> None:
        self.assertEqual({"TWTR": 11}, self.repo.resolve_identifiers([" twtr "], "TICKER",
                                                                     on_date=date(2025, 6, 1)))


class MembershipTest(unittest.TestCase):
    """index_memberships는 스냅샷 한 행이 아니라 종목별 유효기간 행이다 —
    관측이 쌓인 채로 세면 기간이 겹쳐 지수가 실제보다 부풀어 보인다."""

    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.db.put(SCHEMA, T_MEMBERSHIPS, [
            _membership_row(INDEX_SP500, 1, "AAPL", "2026-08-01", "2026-09-01"),
            _membership_row(INDEX_SP500, 2, "MSFT", "2026-08-01", "2026-09-01"),
            _membership_row(INDEX_SP500, 1, "AAPL", "2026-09-01", None),
            _membership_row(INDEX_SP500, 3, "NVDA", "2026-09-01", None),
        ])
        self.repo = UniverseRepository(self.db)

    def test_latest_is_the_most_recent_snapshot(self) -> None:
        snapshot = self.repo.latest_membership()
        self.assertEqual(date(2026, 9, 1), snapshot.effective_date)
        self.assertEqual(("AAPL", "NVDA"), snapshot.tickers)

    def test_a_day_without_a_snapshot_falls_back_to_the_previous_one(self) -> None:
        """그날 것이 없다고 빈 목록을 주면 backtest가 '그날 지수가 비었다'로 읽는다."""
        snapshot = self.repo.membership_on(date(2026, 8, 20))
        self.assertEqual(date(2026, 8, 1), snapshot.effective_date)
        self.assertEqual(("AAPL", "MSFT"), snapshot.tickers)

    def test_a_date_before_every_snapshot_is_none(self) -> None:
        self.assertIsNone(self.repo.membership_on(date(2020, 1, 1)))


class WatchlistTest(unittest.TestCase):
    """관심은 발행사(CIK) 단위다. 표시 ticker는 읽기 경계에서 대표 종목으로 붙인다."""

    CIK_AAPL = "0000320193"
    CIK_MSFT = "0000789019"
    CIK_ALPHABET = "0001652044"

    def setUp(self) -> None:
        self.db = FakeDatabase()
        self.db.put(SCHEMA, T_SECURITIES, [
            {**_security(1, "AAPL"), "cik": self.CIK_AAPL},
            {**_security(2, "MSFT"), "cik": self.CIK_MSFT},
        ])
        self.db.put(SCHEMA, T_ENTITIES, [
            {"cik": self.CIK_AAPL, "watchlist_sources": ["manual"], "is_watchlisted": True,
             "watch_from": "2026-01-01", "watchlist_removed_at": None},
            {"cik": self.CIK_MSFT, "watchlist_sources": [], "is_watchlisted": False,
             "watch_from": "2026-01-01", "watchlist_removed_at": "2026-02-01T00:00:00Z"},
        ])
        self.repo = UniverseRepository(self.db)

    def test_only_active_members_are_returned(self) -> None:
        members = self.repo.watchlist_members("fundamentals")
        self.assertEqual(["AAPL"], [member.ticker for member in members])
        self.assertEqual(self.CIK_AAPL, members[0].cik)
        self.assertTrue(members[0].is_active)

    def test_an_unknown_watchlist_is_empty_not_an_error(self) -> None:
        self.assertEqual([], self.repo.watchlist_members("nope"))

    def test_watchlist_member_rows_active_only_excludes_removed(self) -> None:
        rows = self.repo.watchlist_member_rows(include_inactive=False)
        self.assertEqual(["AAPL"], [row["ticker"] for row in rows])

    def test_watchlist_member_rows_include_inactive_returns_everything(self) -> None:
        rows = self.repo.watchlist_member_rows(include_inactive=True)
        self.assertEqual({"AAPL", "MSFT"}, {row["ticker"] for row in rows})

    def test_watchlist_member_returns_none_for_an_unwatched_company(self) -> None:
        self.assertIsNone(self.repo.watchlist_member_row("9999999999"))

    def test_watchlist_member_returns_the_stored_row(self) -> None:
        row = self.repo.watchlist_member_row(self.CIK_AAPL)
        self.assertEqual(["manual"], row["sources"])

    def test_a_dual_class_issuer_yields_one_member_with_a_stable_representative(self) -> None:
        """GOOG/GOOGL이 둘 다 tracked여도 관심 기업은 하나고, 대표는 매번 같아야 한다."""
        self.db.put(SCHEMA, T_SECURITIES, [
            {**_security(4, "GOOGL"), "cik": self.CIK_ALPHABET},
            {**_security(3, "GOOG"), "cik": self.CIK_ALPHABET},
        ])
        self.db.put(SCHEMA, T_ENTITIES, [
            {"cik": self.CIK_ALPHABET, "watchlist_sources": ["manual"], "is_watchlisted": True,
             "watch_from": "2026-01-01", "watchlist_removed_at": None},
        ])
        members = self.repo.watchlist_members("fundamentals")
        self.assertEqual(["GOOG"], [member.ticker for member in members])

    def test_a_watched_company_with_no_tracked_security_is_skipped(self) -> None:
        """보여줄 ticker가 없으면 빈 껍데기를 만들지 않는다."""
        self.db.put(SCHEMA, T_SECURITIES, [
            {**_security(9, "DEAD", tracked=False), "cik": self.CIK_AAPL},
        ])
        self.assertEqual([], self.repo.watchlist_members("fundamentals"))


class WatchlistMemberWriteTest(unittest.TestCase):
    """관심 상태 갱신은 upsert가 아니라 UPDATE다.

    Postgres는 `ON CONFLICT DO UPDATE`에서도 후보 행의 NOT NULL을 먼저 검사한다.
    그래서 `company_name`(NOT NULL)을 빼고 upsert하면 **기존 행이 있어도** `23502`로
    거절당한다 — 관심 기업 추가가 한 번도 성공할 수 없었다. 옛 테스트는 가짜
    저장소가 그 검사를 하지 않아 초록이었다.
    """

    def test_it_updates_the_issuer_row_keyed_by_cik(self) -> None:
        db = FakeDatabase()
        UniverseRepository(db).upsert_watchlist_member(
            cik="0000320193", sources=["manual", "toss"], watch_from="2026-09-01",
            removed_at=None,
        )
        self.assertEqual([], db.upserts, "upsert로는 일부 컬럼만 갱신할 수 없다")
        (_key, values) = db.updates[0]
        self.assertEqual(["manual", "toss"], values["watchlist_sources"])

    def test_it_never_sends_company_facts(self) -> None:
        """관심 갱신이 company_name·SIC를 덮어쓰면 SEC 수집 결과가 사라진다."""
        db = FakeDatabase()
        UniverseRepository(db).upsert_watchlist_member(
            cik="0000320193", sources=["manual"], watch_from="2026-09-01", removed_at=None,
        )
        (_key, values) = db.updates[0]
        self.assertEqual(
            {"watchlist_sources", "watch_from", "watchlist_removed_at"}, set(values),
        )


class WriteTest(unittest.TestCase):
    def test_securities_upsert_never_sends_the_identity(self) -> None:
        """security_id를 코드가 정하면 identity의 주인이 저장소가 아니게 된다."""
        db = FakeDatabase()
        repo = UniverseRepository(db)
        from investment_agent.data.universe.domain.models import Security

        repo.upsert_securities([Security(security_id=99, ticker="AAPL", cik="0000320193")])
        (_key, rows, conflict) = db.upserts[0]
        self.assertNotIn("security_id", rows[0])
        self.assertEqual("ticker", conflict)

    def test_membership_write_replaces_via_rpc_with_resolved_security_ids(self) -> None:
        """정정 가능한 원자 replace를 RPC로 위임한다 — 부분 upsert는 겹친 기간을 남긴다."""
        db = FakeDatabase()
        db.put(SCHEMA, T_SECURITIES, [_security(1, "AAPL"), _security(2, "NVDA")])
        UniverseRepository(db).record_membership(
            MembershipSnapshot("TEST_INDEX", date(2026, 9, 1), ("AAPL", "NVDA"), "wikipedia"),
            source_hash="a" * 64,
        )
        schema, name, params = db.rpc_calls[0]
        self.assertEqual(SCHEMA, schema)
        self.assertEqual(RPC_REPLACE_MEMBERSHIP, name)
        self.assertEqual("TEST_INDEX", params["p_index_code"])
        self.assertEqual("2026-09-01", params["p_effective_date"])
        self.assertEqual([1, 2], params["p_security_ids"])
        self.assertEqual("wikipedia", params["p_source"])
        self.assertEqual("a" * 64, params["p_source_hash"])

    def test_membership_write_enforces_the_sp500_member_count_range(self) -> None:
        """목록이 반쯤 잘려 들어오면 그날 하루가 통째로 틀린다."""
        db = FakeDatabase()
        db.put(SCHEMA, T_SECURITIES, [_security(1, "AAPL")])
        with self.assertRaises(ValueError):
            UniverseRepository(db).record_membership(
                MembershipSnapshot(INDEX_SP500, date(2026, 9, 2), ("AAPL",), "wikipedia"),
                source_hash="a" * 64,
            )

    def test_membership_write_rejects_unknown_securities(self) -> None:
        db = FakeDatabase()
        db.put(SCHEMA, T_SECURITIES, [_security(1, "AAPL")])
        with self.assertRaises(ValueError):
            UniverseRepository(db).record_membership(
                MembershipSnapshot("TEST_INDEX", date(2026, 9, 1), ("AAPL", "NOPE"), "wikipedia"),
                source_hash="a" * 64,
            )


if __name__ == "__main__":
    unittest.main()
