"""7인 레이더 코드 계약 + manager_groups 스냅샷 + active 수집 기준 테스트.

외부 의존성 없음(DB/네트워크 미접근). DB 조회는 recorder로 대체한다.
"""
from __future__ import annotations

import unittest

from investment_agent.data.institutional import persistence as db

from investment_agent.data.institutional.domain import managers
from investment_agent.data.institutional.domain.analysis import build_snapshot
from tests.investment_agent.fakes import FakeDatabase


class RadarCodeContractTest(unittest.TestCase):
    def test_contrarian_value_is_allowed_role(self):
        self.assertIn("contrarian_value", managers.SIGNAL_ROLES)
        self.assertNotIn("risk_signal", managers.SIGNAL_ROLES)

    def test_group_order_and_off_13f_watchlist(self):
        self.assertEqual(
            [role for role, _ in managers.SIGNAL_GROUP_LABELS],
            ["copyable_core", "market_signal", "contrarian_value"],
        )
        self.assertIn("Michael Burry / Scion Asset Management", managers.OFF_13F_WATCHLIST)


class BlindSpotCaveatTest(unittest.TestCase):
    def test_caveat_lists_korean_labels(self):
        caveat = managers.blind_spot_caveat(["short", "private"])
        self.assertIn("숏 포지션", caveat)
        self.assertIn("비상장·프리IPO", caveat)

    def test_empty_codes_give_empty_caveat(self):
        self.assertEqual(managers.blind_spot_caveat([]), "")
        self.assertEqual(managers.blind_spot_caveat(None), "")

    def test_unknown_codes_ignored(self):
        self.assertEqual(managers.blind_spot_caveat(["nope"]), "")


def _manager_row(cik, name, role, order, *, is_active=True):
    return {
        "manager_cik": cik,
        "name": name,
        "name_ko": name,
        "fund_name": f"{name} Fund",
        "signal_role": role,
        "strategy_group": "value",
        "copyability": "high",
        "thesis_ko": "...",
        "display_order": order,
        "is_active": is_active,
    }


class ManagerGroupsSnapshotTest(unittest.TestCase):
    def _snapshot(self):
        source = {
            "managers": [
                _manager_row("2", "Bill Ackman", "copyable_core", 2),
                _manager_row("1", "Warren Buffett", "copyable_core", 1),
                _manager_row("5", "Stanley Druckenmiller", "market_signal", 5),
                _manager_row("7", "Seth Klarman", "contrarian_value", 7),
                _manager_row("99", "Mohnish Pabrai", "copyable_core", None, is_active=False),
            ],
            "filings": [],
            "positions": [],
            "cusip_map": [],
            "tickers": [],
        }
        return build_snapshot(source)

    def test_snapshot_includes_manager_groups(self):
        snapshot = self._snapshot()
        self.assertIn("manager_groups", snapshot)
        roles = [group["signal_role"] for group in snapshot["manager_groups"]]
        # 그룹은 항상 copyable_core → market_signal → contrarian_value 순서로 노출된다.
        self.assertEqual(roles, ["copyable_core", "market_signal", "contrarian_value"])

    def test_core_group_ordered_by_display_order(self):
        groups = {g["signal_role"]: g for g in self._snapshot()["manager_groups"]}
        core_names = [m["name"] for m in groups["copyable_core"]["managers"]]
        self.assertEqual(core_names, ["Warren Buffett", "Bill Ackman"])

    def test_inactive_manager_excluded_from_groups(self):
        snapshot = self._snapshot()
        all_names = [
            m["name"]
            for group in snapshot["manager_groups"]
            for m in group["managers"]
        ]
        self.assertNotIn("Mohnish Pabrai", all_names)


class InstrumentBreakdownTest(unittest.TestCase):
    """13F의 옵션·전환사채(PRN)를 주식과 분리해 보존하는지 검증한다."""

    def _snapshot(self):
        source = {
            "managers": [
                {"manager_cik": "1", "name": "Klarman", "is_active": True,
                 "signal_role": "contrarian_value", "display_order": 1},
            ],
            "filings": [
                {"accession_no": "A1", "manager_cik": "1",
                 "period_end": "2024-03-31", "form_type": "13F-HR",
                 "report_type": "13F HOLDINGS REPORT", "filing_date": "2024-05-15",
                 "accepted_at": "2024-05-15T16:00:00", "amendment_type": None,
                 "source_url": "https://sec.gov"},
            ],
            "positions": [
                {"accession_no": "A1", "cusip": "037833100", "issuer_name": "Apple",
                 "value_usd": 1000, "quantity": 10, "quantity_type": "SH",
                 "position_kind": "SHARES"},
                {"accession_no": "A1", "cusip": "594918104", "issuer_name": "Nvidia",
                 "value_usd": 500, "quantity": 5, "quantity_type": "SH",
                 "position_kind": "PUT"},
                {"accession_no": "A1", "cusip": "11111111A", "issuer_name": "Conv Note",
                 "value_usd": 200, "quantity": 100, "quantity_type": "PRN",
                 "position_kind": "SHARES"},
            ],
            "cusip_map": [],
            "tickers": [],
        }
        return build_snapshot(source)

    def test_breakdown_separates_instrument_types(self):
        summary = self._snapshot()["filings"][0]
        breakdown = summary["instrument_breakdown"]
        self.assertEqual(breakdown["equity"]["count"], 1)
        self.assertEqual(breakdown["put"]["count"], 1)
        self.assertEqual(breakdown["principal"]["count"], 1)
        self.assertEqual(breakdown["call"]["count"], 0)
        self.assertEqual(int(breakdown["put"]["value_usd"]), 500)

    def test_instruments_surfaces_non_equity_only(self):
        instruments = self._snapshot()["instruments"]
        kinds = sorted(row["instrument"] for row in instruments)
        self.assertEqual(kinds, ["principal", "put"])
        # 주식은 instruments에 포함되지 않는다(기존 holdings/changes 경로 유지).
        self.assertNotIn("equity", kinds)

    def test_holdings_contain_only_long_equity(self):
        # CALL/PUT/PRN은 holdings에 섞이지 않는다 — long equity(SHARES·SH)만.
        holdings = self._snapshot()["holdings"]
        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0]["cusip"], "037833100")
        self.assertEqual(holdings[0]["put_call"], "SH")

    def test_pct_of_13f_long_equity_uses_long_equity_denominator(self):
        # 분모 = long equity 합(=1000). 옵션/PRN(700)은 분모에 포함되지 않는다.
        holding = self._snapshot()["holdings"][0]
        self.assertEqual(holding["pct_denominator"], "13f_long_equity")
        self.assertEqual(holding["visibility_scope"], "visible_13f_only")
        self.assertAlmostEqual(holding["pct_of_13f_long_equity"], 1.0)

    def test_summary_exposure_fields(self):
        s = self._snapshot()["filings"][0]
        self.assertEqual(int(s["reported_13f_value_usd"]), 1700)
        self.assertEqual(int(s["long_equity_value_usd"]), 1000)
        self.assertEqual(int(s["put_value_usd"]), 500)
        self.assertEqual(int(s["principal_value_usd"]), 200)
        self.assertEqual(s["long_equity_count"], 1)
        self.assertEqual(s["put_count"], 1)
        self.assertEqual(s["principal_count"], 1)
        self.assertEqual(s["call_count"], 0)
        self.assertEqual(s["pct_denominator"], "13f_long_equity")


class AnalysisGuardrailTest(unittest.TestCase):
    def test_first_filing_is_baseline_not_new_buys(self):
        source = {
            "managers": [_manager_row("1", "Active", "copyable_core", 1)],
            "filings": [
                {
                    "accession_no": "A1",
                    "manager_cik": "1",
                    "period_end": "2026-03-31",
                    "form_type": "13F-HR",
                    "report_type": "13F HOLDINGS REPORT",
                    "filing_date": "2026-05-15",
                    "accepted_at": "2026-05-15T16:00:00",
                    "amendment_type": None,
                }
            ],
            "positions": [
                {
                    "accession_no": "A1",
                    "cusip": "037833100",
                    "issuer_name": "Apple",
                    "value_usd": 1000,
                    "quantity": 10,
                    "quantity_type": "SH",
                    "position_kind": "SHARES",
                }
            ],
            "cusip_map": [{"cusip": "037833100", "ticker": "AAPL"}],
            "tickers": [],
        }

        snapshot = build_snapshot(source)

        self.assertEqual(snapshot["changes"], [])
        self.assertEqual(snapshot["buys"], [])

    def test_inactive_manager_filings_are_excluded(self):
        active = _manager_row("1", "Active", "copyable_core", 1)
        inactive = _manager_row(
            "2", "Inactive", "copyable_core", 2, is_active=False
        )
        source = {
            "managers": [active, inactive],
            "filings": [
                {
                    "accession_no": "A1",
                    "manager_cik": "1",
                    "period_end": "2026-03-31",
                    "form_type": "13F-HR",
                    "report_type": "13F HOLDINGS REPORT",
                    "filing_date": "2026-05-15",
                    "accepted_at": "2026-05-15T16:00:00",
                    "amendment_type": None,
                },
                {
                    "accession_no": "I1",
                    "manager_cik": "2",
                    "period_end": "2026-06-30",
                    "form_type": "13F-HR",
                    "report_type": "13F HOLDINGS REPORT",
                    "filing_date": "2026-08-01",
                    "accepted_at": "2026-08-01T16:00:00",
                    "amendment_type": None,
                },
            ],
            "positions": [],
            "cusip_map": [],
            "tickers": [],
        }

        snapshot = build_snapshot(source)

        self.assertEqual(len(snapshot["filings"]), 1)
        self.assertEqual(snapshot["filings"][0]["manager_cik"], "1")


class ActiveManagerQueryTest(unittest.TestCase):
    def test_active_managers_filter_and_order(self):
        """manager_cik/name/fund_name/is_active의 SSOT는 코드 설정이다 — DB는
        전혀 관여하지 않으므로 configure() 없이도 답할 수 있다."""
        catalog = {
            "0001067983": {"name": "A", "fund_name": "A", "display_order": 1, "is_active": True},
            "0000000002": {"name": "B", "fund_name": "B", "display_order": 2, "is_active": False},
        }
        self.assertEqual(["0001067983"], [row["manager_cik"] for row in managers.active_managers(catalog)])

    def test_get_active_manager_ciks_reads_the_real_catalog(self):
        db.configure(FakeDatabase())
        ciks = db.get_active_manager_ciks()

        self.assertEqual(sorted(managers.MANAGER_CATALOG), sorted(ciks))


if __name__ == "__main__":
    unittest.main()
