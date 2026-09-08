"""persistence.py의 조회 함수가 UniverseRepository로 위임한 뒤에도 같은 값을
주는지 굳힌다. 리팩터 전 특성화 테스트 — 이 테스트들은 옛 구현(직접 쿼리)과
새 구현(UniverseRepository 위임) 양쪽에서 통과해야 한다."""
from __future__ import annotations

import unittest

from investment_agent.data.universe import persistence as db
from investment_agent.data.universe.repository import SCHEMA, T_ENTITIES, T_SECURITIES
from tests.investment_agent.fakes import FakeDatabase


def _security(security_id: int, ticker: str, cik: str, *, tracked: bool = True) -> dict:
    return {
        "security_id": security_id,
        "ticker": ticker,
        "cik": cik,
        "exchange_code": "XNAS",
        "security_type": "common_stock",
        "security_title": None,
        "is_active_listing": True,
        "is_tracked": tracked,
    }


class PersistenceSecurityQueriesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeDatabase()
        self.fake.put(SCHEMA, T_SECURITIES, [
            _security(1, "AAPL", "0000320193", tracked=True),
            _security(2, "MSFT", "0000789019", tracked=True),
            _security(3, "DEAD", "0000000003", tracked=False),
        ])
        db.configure(self.fake)
        self.addCleanup(db.configure, None)

    def test_select_tracked_tickers_excludes_untracked(self) -> None:
        self.assertEqual(["AAPL", "MSFT"], db.select_tracked_tickers())

    def test_select_tracked_ciks_are_ten_digit_and_sorted(self) -> None:
        self.assertEqual(["0000320193", "0000789019"], db.select_tracked_ciks())

    def test_select_security_ids_by_ticker_finds_known_tickers(self) -> None:
        self.assertEqual(
            {"AAPL": 1, "MSFT": 2},
            db.select_security_ids_by_ticker(["aapl", "msft"]),
        )

    def test_select_security_ids_by_ticker_omits_unknown_tickers(self) -> None:
        self.assertEqual({"AAPL": 1}, db.select_security_ids_by_ticker(["AAPL", "NOPE"]))

    def test_select_tickers_by_security_id_round_trips(self) -> None:
        self.assertEqual({1: "AAPL", 2: "MSFT"}, db.select_tickers_by_security_id([1, 2]))

    def test_select_common_stock_tickers_by_cik_includes_untracked_active_listings(
        self,
    ) -> None:
        """common_stock+active면 tracked 여부와 무관하게 포함된다 — DEAD도
        active_listing이므로 나온다(이 저장소는 delisting을 별도로 표시하지
        않는다)."""
        mapping = db.select_common_stock_tickers_by_cik()
        self.assertEqual(["DEAD"], mapping["0000000003"])

    def test_select_common_stock_tickers_by_cik_filters_to_requested_ciks(self) -> None:
        mapping = db.select_common_stock_tickers_by_cik(["0000320193"])
        self.assertEqual({"0000320193": ["AAPL"]}, mapping)


class PersistenceDotTickerNormalizationTest(unittest.TestCase):
    """UniverseRepository 위임 이후 넓어지는 동작 한 가지 — 명시적으로 표시."""

    def setUp(self) -> None:
        self.fake = FakeDatabase()
        self.fake.put(SCHEMA, T_SECURITIES, [_security(2, "BRK-B", "0001067983")])
        db.configure(self.fake)
        self.addCleanup(db.configure, None)

    def test_dotted_ticker_input_now_resolves_to_the_dashed_canonical_form(self) -> None:
        """이전 구현은 `.upper()`만 하고 점을 하이픈으로 바꾸지 않아 'BRK.B'가
        저장된 'BRK-B'와 매치되지 않았다(빈 결과). UniverseRepository의
        `securities_by_ticker()`는 domain.identifiers.normalize_ticker를 거치므로
        이제 올바르게 매치된다 — 의도한 개선이며 동작 변경으로 명시한다."""
        self.assertEqual({"BRK-B": 2}, db.select_security_ids_by_ticker(["BRK.B"]))


class PersistenceSecurityProfilesTrackedOnlyTest(unittest.TestCase):
    """select_security_profiles(tickers=..., tracked_only=True)의 두 필터가
    AND로 합쳐지는지 굳힌다 — _security_rows()의 실제 버그가 여기서 났었다:
    tracked_only=True가 tickers 필터를 통째로 무시하고 전체 tracked 종목을
    돌려줬다."""

    def setUp(self) -> None:
        self.fake = FakeDatabase()
        self.fake.put(SCHEMA, T_SECURITIES, [
            _security(1, "AAPL", "0000320193", tracked=True),
            _security(2, "MSFT", "0000789019", tracked=True),
            _security(3, "DEAD", "0000000003", tracked=False),
        ])
        self.fake.put(SCHEMA, T_ENTITIES, [
            {"cik": "0000320193", "company_name": "Apple Inc.", "company_name_ko": None,
             "sic_industry_name": None, "sic_division_name": None},
        ])
        db.configure(self.fake)
        self.addCleanup(db.configure, None)

    def test_requested_tickers_are_intersected_with_tracked_status_not_ignored(self) -> None:
        rows = db.select_security_profiles(["AAPL"], tracked_only=True)
        self.assertEqual(["AAPL"], [row["ticker"] for row in rows])

    def test_a_requested_but_untracked_ticker_is_excluded_when_tracked_only(self) -> None:
        rows = db.select_security_profiles(["DEAD"], tracked_only=True)
        self.assertEqual([], rows)


if __name__ == "__main__":
    unittest.main()


class SetMembershipTest(unittest.TestCase):
    """수집 게이트를 정하는 자리다. 여기서 틀리면 모든 하류가 조용히 더 돈다.

    실제로 두 가지가 함께 틀려 있었다.

    * 과거 멤버 행에는 `is_tracked` 키가 없는데 기본값이 `True`였다 — 지수에서
      빠진 종목이 다시 tracked가 됐다(실측 129종목이 그렇게 남았다).
    * 없는 ticker에 UPDATE만 걸어서 과거 멤버 증권이 만들어지지 않았고, 0행을
      고치고도 성공으로 세어 그 사실이 가려졌다. 그 다음 단계인 과거 멤버십
      snapshot 적재는 "unknown securities"로 통째로 실패했다.
    """

    def setUp(self) -> None:
        self.fake = FakeDatabase()
        self.fake.put(SCHEMA, T_SECURITIES, [
            _security(1, "KEEP", "0000000001", tracked=True),
            _security(2, "DROPPED", "0000000002", tracked=True),
        ])
        db.configure(self.fake)
        self.addCleanup(db.configure, None)

    def test_an_explicit_gate_value_is_written(self) -> None:
        db.set_membership([{"ticker": "DROPPED", "is_tracked": False}])
        self.assertEqual([((SCHEMA, T_SECURITIES), {"is_tracked": False})], self.fake.updates)

    def test_a_past_member_row_never_touches_the_gate(self) -> None:
        """`is_tracked` 키가 없는 행은 게이트에 대해 아무 말도 하지 않는다."""
        db.set_membership([{"ticker": "DROPPED"}])
        self.assertEqual([], self.fake.updates)
        self.assertEqual([], self.fake.inserts)

    def test_an_unknown_past_member_is_registered_as_a_delisted_security(self) -> None:
        written = db.set_membership([{"ticker": "YHOO"}])
        self.assertEqual(1, written)
        (_key, payload), = self.fake.inserts
        self.assertEqual(
            [{"ticker": "YHOO", "cik": None, "is_active_listing": False, "is_tracked": False}],
            payload,
        )

    def test_an_unknown_current_member_is_reported_not_invented(self) -> None:
        """현재 멤버인데 마스터에 없으면 CIK를 모른다 — 지어내면 재무가 영영 안 붙는다."""
        written = db.set_membership([{"ticker": "NEWCO", "is_tracked": True}])
        self.assertEqual(0, written)
        self.assertEqual([], self.fake.inserts)
        self.assertEqual([], self.fake.updates)


class ListingSyncDoesNotOwnTheGateTest(unittest.TestCase):
    """거래소 master 동기화는 수집 게이트에 대해 아무 말도 하지 않는다.

    전에는 `upsert_securities`가 매번 `is_tracked=False`를 실어 7천여 종목의 게이트를
    통째로 껐다. `universe_membership` 워크플로는 그 직후 `reconcile_membership`을
    부르는데, S&P 변동이 없는 날은 **조기 반환**해서 게이트를 되돌리지 않는다.
    결과는 tracked 0 — 모든 하류 수집이 0종목이 되고 에러는 하나도 나지 않는다.

    upsert는 payload에 있는 컬럼만 갱신하므로, 싣지 않는 것이 곧 "건드리지 않음"이다.
    """

    def test_the_listing_payload_carries_no_tracked_flag(self) -> None:
        fake = FakeDatabase()
        db.configure(fake)
        self.addCleanup(db.configure, None)
        db.upsert_securities([
            {"ticker": "AAPL", "cik": "320193", "exchange_code": "Nasdaq"},
        ])
        securities = [entry for entry in fake.upserts if entry[0][1] == T_SECURITIES]
        self.assertEqual(1, len(securities))
        (_key, rows, conflict) = securities[0]
        self.assertEqual("ticker", conflict)
        self.assertNotIn("is_tracked", rows[0])
        # 상장 여부는 반대로 이 동기화가 소유한다.
        self.assertIn("is_active_listing", rows[0])
