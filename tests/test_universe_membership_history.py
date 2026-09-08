from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

from investment_agent.data.universe import persistence as db
from investment_agent.data.universe.application import collection as etl
from investment_agent.data.universe.domain.normalization import build_membership_snapshots


class MembershipHistoryTransformTest(unittest.TestCase):
    def test_reverse_events_build_point_in_time_snapshots(self):
        # 안전 개수 조건을 유지하면서 한 종목 교체를 역재생한다.
        base = [f"X{i:03d}" for i in range(499)]
        members = pd.DataFrame({"ticker": [*base, "NEW"], "name": ["n"] * 500})
        changes = pd.DataFrame([
            {"change_date": date(2025, 1, 2), "ticker": "NEW", "action": "added", "name": "New"},
            {"change_date": date(2025, 1, 2), "ticker": "OLD", "action": "removed", "name": "Old"},
        ])
        rows = build_membership_snapshots(members, changes)
        self.assertEqual(len(rows), 1)
        self.assertIn("NEW", rows[0]["symbols"])
        self.assertNotIn("OLD", rows[0]["symbols"])
        self.assertEqual(rows[0]["member_count"], 500)
        self.assertEqual(len(rows[0]["source_hash"]), 64)

    def test_inconsistent_change_history_fails_closed(self):
        members = pd.DataFrame({
            "ticker": [f"X{i:03d}" for i in range(500)],
            "name": ["n"] * 500,
        })
        changes = pd.DataFrame([
            {"change_date": date(2025, 1, 2), "ticker": "ABSENT", "action": "added"},
        ])
        with self.assertRaisesRegex(ValueError, "cannot reverse"):
            build_membership_snapshots(members, changes)

    def test_ticker_reuse_stops_history_instead_of_guessing_older_identity(self):
        base = [f"X{i:03d}" for i in range(499)]
        members = pd.DataFrame({"ticker": [*base, "REUSE"], "name": ["n"] * 500})
        changes = pd.DataFrame([
            {"change_date": date(2020, 1, 2), "ticker": "REUSE", "action": "removed"},
            {"change_date": date(2019, 1, 2), "ticker": "OLD", "action": "removed"},
        ])
        rows = build_membership_snapshots(members, changes)
        self.assertEqual([row["effective_date"] for row in rows], ["2020-01-02"])


class MembershipHistoryStorageTest(unittest.TestCase):
    def test_full_security_sync_writes_v1_entities_and_securities(self):
        fake = mock.Mock()
        fake.upsert.return_value = 1001
        fake.select_in_chunks.return_value = []
        rows = [
            {
                "ticker": f"X{i:04d}",
                "cik": f"{i:010d}",
                "company_name": f"Company {i}",
                "exchange_code": "Nasdaq",
                "is_active_listing": True,
            }
            for i in range(1001)
        ]
        with mock.patch.object(db, "_database", fake):
            self.assertEqual(db.upsert_securities(rows), 1001)
        self.assertEqual(fake.upsert.call_count, 2)
        self.assertEqual(fake.upsert.call_args_list[0].kwargs["table"], "entities")
        self.assertEqual(fake.upsert.call_args_list[1].kwargs["table"], "securities")

    def test_append_writes_canonical_membership_rows(self):
        """append_memberships는 이제 자체 upsert 대신 UniverseRepository의 원자
        replace RPC 경로(record_membership)로 위임한다."""
        from investment_agent.data.universe.repository import UniverseRepository

        rows = [{"effective_date": "2025-01-02", "symbols": ["aapl", "AAPL", "MSFT"],
                 "member_count": 2, "source": "test", "source_hash": "a" * 64}]
        with mock.patch.object(UniverseRepository, "record_membership", return_value=1) as record:
            self.assertEqual(db.append_memberships(rows), 1)
        record.assert_called_once()
        snapshot = record.call_args.args[0]
        self.assertEqual(("AAPL", "MSFT"), snapshot.tickers)
        self.assertEqual(date(2025, 1, 2), snapshot.effective_date)
        self.assertEqual("a" * 64, record.call_args.kwargs["source_hash"])

    def test_schema_keeps_history_readable_and_append_only(self):
        sql = Path("db/postgres/v1/10_universe.sql").read_text(encoding="utf-8").lower()
        self.assertIn("create table if not exists universe.entities", sql)
        self.assertIn("create table if not exists universe.index_memberships", sql)
        self.assertIn("source_hash", sql)
        self.assertIn("primary key (index_code, security_id, valid_from)", sql)
        # 유일한 delete는 같은 날 재적용 시 잘못 들어간 당일 신규 행만 지우는
        # 원자 replace 함수 안의 좁은 정정이다 — 과거 이력을 통째로 지우지 않는다.
        self.assertIn(
            "delete from universe.index_memberships\n"
            "    where index_code=p_index_code and valid_from=p_effective_date and valid_to is null",
            sql,
        )
        self.assertIn("to service_role", sql)

    def test_schema_uses_canonical_physical_names(self):
        sql = Path("db/postgres/v1/10_universe.sql").read_text(encoding="utf-8").lower()
        self.assertIn("create table if not exists universe.securities", sql)
        self.assertIn("create table if not exists universe.index_memberships", sql)
        self.assertRegex(sql, r"cik\s+text primary key")
        self.assertIn("company_name_ko", sql)
        self.assertIn("exchange_code", sql)
        self.assertIn("sic_industry_name", sql)
        self.assertIn("sic_division_name", sql)
        self.assertIn("create table if not exists universe.securities", sql)
        # 회원 수 검증은 SQL CHECK가 아니라 RPC(replace_index_membership) 안의
        # SP500 cardinality 검사로 옮겨졌다.
        self.assertIn("cardinality(p_security_ids) not between 450 and 520", sql)
        self.assertNotIn("function universe.replace_memberships", sql)
        self.assertNotIn("function universe.apply_sic_results", sql)
        self.assertNotIn("function universe.apply_ciks", sql)
        # 승계 원장과 관심종목 원장은 v1에서 사라졌다. 되살아나면 저장 identity가
        # 다시 둘로 갈라진다.
        self.assertNotIn("universe.entity_successions", sql)
        self.assertNotIn("universe.watchlist_members", sql)
        self.assertIn("on universe.securities (ticker) where is_tracked", sql)
        securities_start = sql.index("create table if not exists universe.securities")
        securities_end = sql.index("create index", securities_start)
        securities_block = sql[securities_start:securities_end]
        for old_column in ("company_name text", "sic_code text", "sic_industry_name text", "sic_division_name text"):
            self.assertNotIn(old_column, securities_block)


class MembershipReconcileTest(unittest.TestCase):
    def test_malformed_historical_symbols_do_not_enter_security_master(self):
        members = pd.DataFrame({"ticker": ["KEEP"], "name": ["Keep"]})
        changes = pd.DataFrame([
            {"change_date": date(2020, 1, 1), "ticker": "ITT |", "action": "removed", "name": "ITT"},
            {"change_date": date(2020, 1, 1), "ticker": "VALID", "action": "removed", "name": "Valid"},
        ])

        from investment_agent.data.universe.domain.normalization import build_reconcile_rows

        plan = build_reconcile_rows(members, changes)

        self.assertEqual(plan["past_rows"], [{"ticker": "VALID"}])

    def _lightweight(self, tracked):
        members = pd.DataFrame({"ticker": ["A", "B"], "name": ["A", "B"]})
        with (
            mock.patch.object(etl, "fetch_current_members", return_value=members),
            mock.patch.object(etl.db, "select_latest_sp500_symbols", return_value={"A", "B"}),
            mock.patch.object(etl.db, "select_tracked_tickers", return_value=tracked),
            mock.patch.object(etl, "fetch_selected_changes") as fetch_changes,
            mock.patch.object(etl.db, "set_membership", return_value=1) as set_membership,
            mock.patch.object(etl.db, "append_memberships") as append_snapshots,
        ):
            result = etl.reconcile_membership(audit_history=False)
        return result, fetch_changes, set_membership, append_snapshots

    def test_lightweight_check_does_not_write_when_membership_is_unchanged(self):
        result, fetch_changes, set_membership, append_snapshots = self._lightweight(["A", "B"])

        self.assertEqual(
            result,
            {"changed": False, "added": [], "removed": [], "snapshots_inserted": 0},
        )
        fetch_changes.assert_not_called()
        set_membership.assert_not_called()
        append_snapshots.assert_not_called()

    def test_lightweight_check_repairs_a_gate_that_drifted(self):
        """멤버십이 그대로여도 게이트가 그대로라는 뜻은 아니다.

        상류의 거래소 master 동기화가 게이트를 통째로 껐고, 이 경로가 조기 반환하는
        바람에 아무도 되돌리지 않아 **모든 하류 수집이 0종목**이 됐다 — 에러 없이.
        """
        _result, _fetch, set_membership, _append = self._lightweight([])

        set_membership.assert_called_once_with(
            [{"ticker": "A", "is_tracked": True}, {"ticker": "B", "is_tracked": True}]
        )

    def test_changed_membership_only_disables_removed_sp500_symbols(self):
        members = pd.DataFrame({"ticker": ["KEEP", "NEW"], "name": ["Keep", "New"]})
        plan = {
            "current_rows": [
                {"ticker": "KEEP", "is_tracked": True},
                {"ticker": "NEW", "is_tracked": True},
            ],
            "past_rows": [{"ticker": "PAST"}],
        }
        snapshots = [{"effective_date": "2026-08-26", "symbols": ["KEEP", "NEW"]}]
        with (
            mock.patch.object(etl, "fetch_current_members", return_value=members),
            mock.patch.object(
                etl.db,
                "select_latest_sp500_symbols",
                return_value={"KEEP", "REMOVED"},
            ),
            mock.patch.object(etl, "fetch_selected_changes", return_value=pd.DataFrame()),
            mock.patch.object(etl, "build_reconcile_rows", return_value=plan),
            mock.patch.object(etl, "build_membership_snapshots", return_value=snapshots),
            mock.patch.object(etl.db, "set_membership", side_effect=[2, 1, 1]) as set_membership,
            mock.patch.object(etl.db, "append_memberships", return_value=1),
        ):
            result = etl.reconcile_membership(audit_history=False)

        self.assertEqual(result["added"], ["NEW"])
        self.assertEqual(result["removed"], ["REMOVED"])
        self.assertTrue(result["changed"])
        self.assertEqual(
            set_membership.call_args_list,
            [
                mock.call(plan["current_rows"]),
                mock.call(plan["past_rows"]),
                mock.call([{"ticker": "REMOVED", "is_tracked": False}]),
            ],
        )


if __name__ == "__main__":
    unittest.main()
