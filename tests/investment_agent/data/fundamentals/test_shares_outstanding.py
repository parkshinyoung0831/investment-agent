from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from investment_agent.data.fundamentals.domain.services.parse_shares import (
    _match_class_ticker,
    aggregate_company_share_history,
    parse_common_shares_from_companyfacts,
    validate_shares_outstanding,
)
from investment_agent.operations.runtime import EXIT_FAILED
from investment_agent.data.fundamentals.commands import common_shares
from investment_agent.data.universe.infrastructure.sources import nasdaq_trader
from investment_agent.data.universe.domain.normalization import classify_security_type


def _share_row(**overrides: object) -> dict:
    row = {
        "cik": "0000000001",
        "share_class_key": "common",
        "share_class_axis": None,
        "share_class_member": None,
        "share_class_title": "Common Stock",
        "mapped_ticker": "TEST",
        "as_of_date": "2026-06-30",
        "shares_outstanding": 100_000_000,
        "accession_no": "0000000001-26-000001",
        "form_type": "10-Q",
        "filed_at": "2026-07-30",
        "accepted_at": "2026-07-30T20:00:00Z",
        "source_concept": "dei:EntityCommonStockSharesOutstanding",
        "ticker_mapping_status": "single_class_default",
    }
    row.update(overrides)
    return row


class ShareSchemaContractTest(unittest.TestCase):
    def test_storage_contract_is_cik_and_class_grain(self) -> None:
        sql = Path("db/postgres/v1/30_fundamentals.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS fundamentals.share_class_snapshots", sql)
        self.assertIn("shares_outstanding", sql)
        self.assertIn(
            "PRIMARY KEY (cik, share_class_key, as_of_date, accession_no)", sql
        )
        self.assertIn("share_class_cik_as_of_idx", sql)
        self.assertNotIn("common_shares_outstanding_history", sql)
        self.assertNotIn("context_id text", sql)

    def test_companyfacts_parser_emits_integer_canonical_columns(self) -> None:
        document = {
            "cik": 1,
            "facts": {
                "dei": {
                    "EntityCommonStockSharesOutstanding": {
                        "units": {
                            "shares": [{
                                "end": "2026-06-30",
                                "val": 100_000_000,
                                "accn": "0000000001-26-000001",
                                "form": "10-Q",
                                "filed": "2026-07-30",
                            }]
                        }
                    }
                }
            },
        }

        rows = parse_common_shares_from_companyfacts(
            document, active_tickers=["TEST"]
        )

        self.assertEqual(rows[0]["shares_outstanding"], 100_000_000)
        self.assertIsInstance(rows[0]["shares_outstanding"], int)
        self.assertEqual(rows[0]["mapped_ticker"], "TEST")
        self.assertNotIn("context_id", rows[0])

    def test_scale_outlier_is_rejected_instead_of_entering_market_cap(self) -> None:
        rows = [
            _share_row(
                as_of_date="2025-06-30",
                accession_no="0000000001-25-000001",
                shares_outstanding=100_000_000,
            ),
            _share_row(shares_outstanding=100_000_000_000),
            _share_row(
                as_of_date="2026-09-30",
                accession_no="0000000001-26-000002",
                filed_at="2026-10-30",
                accepted_at="2026-10-30T20:00:00Z",
                shares_outstanding=101_000_000,
            ),
        ]

        with self.assertRaisesRegex(ValueError, "implausible SEC share scale"):
            validate_shares_outstanding(rows)

    def test_unlisted_class_must_not_carry_a_mapped_ticker(self) -> None:
        row = _share_row(
            mapped_ticker="TEST",
            ticker_mapping_status="unmapped_unlisted",
        )
        with self.assertRaisesRegex(ValueError, "unexpectedly has a ticker"):
            validate_shares_outstanding([row])

    def test_alphabet_classes_map_without_issuer_hardcoding(self) -> None:
        tickers = ["GOOG", "GOOGL"]

        self.assertEqual(
            _match_class_ticker("Common Class A", "CommonClassAMember", tickers),
            ("GOOGL", "mapped_by_symbol"),
        )
        self.assertEqual(
            _match_class_ticker("Capital Class C", "CapitalClassCMember", tickers),
            ("GOOG", "mapped_by_symbol"),
        )
        self.assertEqual(
            _match_class_ticker("Common Class B", "CommonClassBMember", tickers),
            (None, "unmapped_unlisted"),
        )

    def test_company_history_includes_unlisted_class_and_latest_vintage(self) -> None:
        rows = [
            {
                **_share_row(
                    share_class_key="class_a",
                    mapped_ticker="GOOGL",
                    ticker_mapping_status="mapped_by_symbol",
                    shares_outstanding=5_800_000_000,
                ),
                "ticker": "GOOGL",
            },
            {
                **_share_row(
                    share_class_key="class_b",
                    mapped_ticker=None,
                    ticker_mapping_status="unmapped_unlisted",
                    shares_outstanding=800_000_000,
                ),
                "ticker": "GOOGL",
            },
            {
                **_share_row(
                    share_class_key="class_a",
                    mapped_ticker="GOOGL",
                    ticker_mapping_status="mapped_by_symbol",
                    shares_outstanding=5_900_000_000,
                    accession_no="0000000001-26-000002",
                    filed_at="2026-08-01",
                    accepted_at="2026-08-01T20:00:00Z",
                ),
                "ticker": "GOOGL",
            },
        ]

        history = aggregate_company_share_history(rows)

        self.assertEqual(history[0]["shares"], 6_700_000_000)
        self.assertTrue(history[0]["uses_unlisted_class"])


class ShareEntrypointContractTest(unittest.TestCase):
    def test_any_cik_failure_makes_the_process_fail(self) -> None:
        with (
            mock.patch.object(
                common_shares.universe_db,
                "select_tracked_ciks",
                return_value=["0000000001"],
            ),
            mock.patch.object(
                common_shares.universe_db,
                "select_common_stock_tickers_by_cik",
                return_value={"0000000001": ["TEST"]},
            ),
            mock.patch.object(
                common_shares,
                "load_shares_outstanding_by_cik",
                return_value=[],
            ),
            mock.patch.object(
                common_shares,
                "fetch_cik_common_shares",
                side_effect=RuntimeError("provider unavailable"),
            ),
            mock.patch.object(common_shares, "notify_ops") as notify,
        ):
            # 한 CIK도 처리하지 못했으면 수집 자체가 깨진 것이다 — 일부만 실패한
            # 경우(EXIT_PARTIAL)와 구분한다.
            self.assertEqual(common_shares.main([]), EXIT_FAILED)
        notify.assert_called_once()
        embed = notify.call_args.kwargs["embeds"][0]
        self.assertTrue(
            any("0000000001" in str(field["value"]) for field in embed["fields"])
        )


class SecurityClassificationContractTest(unittest.TestCase):
    def test_symbol_directory_normalizes_preferred_series(self) -> None:
        parsed = nasdaq_trader._parse_file(
            "ACT Symbol|Security Name|Exchange|ETF|Test Issue\n"
            "WRB$E|Issuer Subordinated Notes due 2058|N|N|N\n",
            other_listed=True,
        )
        self.assertIn("WRB-PE", parsed)

    def test_common_issuer_names_do_not_trigger_short_keyword_matches(self) -> None:
        for title in (
            "United Airlines Holdings, Inc. Common Stock",
            "Broadridge Financial Solutions, Inc. Common Stock",
        ):
            self.assertEqual(
                classify_security_type(security_title=title), "common_stock"
            )

    def test_notes_and_etfs_are_not_common_stock(self) -> None:
        self.assertEqual(
            classify_security_type(
                security_title="Issuer 5.10% Subordinated Notes due 2059"
            ),
            "note",
        )
        self.assertEqual(classify_security_type(is_etf=True), "etf")


if __name__ == "__main__":
    unittest.main()
