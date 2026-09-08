"""대시보드 데이터 계층의 읽기 전용 경계를 오프라인으로 검증한다."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pandas as pd

from investment_agent.dashboard import db, ops
from investment_agent.execution import db as execution_db
from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.platform.db.sqlite import runtime_connection
from investment_agent.reporting.models import DataResult
from investment_agent.reporting.readers import news as reporting_news


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_ROOT = ROOT / "src" / "investment_agent" / "dashboard"


class _FakeBuilder:
    def __init__(
        self,
        client: "_FakeClient",
        schema: str,
        table: str,
    ) -> None:
        self.client = client
        self.schema_name = schema
        self.table_name = table
        self.equal_filters: list[tuple[str, Any]] = []
        self.membership_filters: list[tuple[str, tuple[Any, ...]]] = []
        self.limit_value: int | None = None
        self.range_value: tuple[int, int] | None = None

    def select(self, columns: str) -> "_FakeBuilder":
        self.client.calls.append(("select", columns))
        return self

    def eq(self, column: str, value: Any) -> "_FakeBuilder":
        self.client.calls.append(("eq", column, value))
        self.equal_filters.append((column, value))
        return self

    def in_(self, column: str, values: list[Any]) -> "_FakeBuilder":
        self.client.calls.append(("in", column, tuple(values)))
        self.membership_filters.append((column, tuple(values)))
        return self

    def order(self, column: str, *, desc: bool = False) -> "_FakeBuilder":
        self.client.calls.append(("order", column, desc))
        return self

    def limit(self, value: int) -> "_FakeBuilder":
        self.client.calls.append(("limit", value))
        self.limit_value = value
        return self

    def range(self, start: int, end: int) -> "_FakeBuilder":
        self.client.calls.append(("range", start, end))
        self.range_value = (start, end)
        return self

    def execute(self) -> SimpleNamespace:
        self.client.calls.append(("execute",))
        rows = [dict(row) for row in self.client.data.get((self.schema_name, self.table_name), [])]
        for column, value in self.equal_filters:
            rows = [row for row in rows if row.get(column) == value]
        for column, values in self.membership_filters:
            rows = [row for row in rows if row.get(column) in values]
        if self.range_value is not None:
            start, end = self.range_value
            rows = rows[start:end + 1]
        elif self.limit_value is not None:
            rows = rows[:self.limit_value]
        return SimpleNamespace(data=rows)


class _FakeFunction:
    """RPC 응답을 흉내내되 필터·정렬은 제공하지 않는다(읽기 함수는 그대로 반환)."""

    def __init__(self, client: "_FakeClient", schema: str, function: str) -> None:
        self.client = client
        self.schema_name = schema
        self.function_name = function

    def execute(self) -> SimpleNamespace:
        self.client.calls.append(("execute",))
        rows = self.client.functions.get((self.schema_name, self.function_name), [])
        return SimpleNamespace(data=[dict(row) for row in rows])


class _FakeSchema:
    def __init__(self, client: "_FakeClient", schema: str) -> None:
        self.client = client
        self.schema_name = schema

    def table(self, table: str) -> _FakeBuilder:
        self.client.calls.append(("table", table))
        return _FakeBuilder(self.client, self.schema_name, table)

    def rpc(self, function: str, params: dict[str, Any]) -> _FakeFunction:
        self.client.calls.append(("rpc", function, tuple(sorted(params.items()))))
        return _FakeFunction(self.client, self.schema_name, function)


class _FakeClient:
    def __init__(
        self,
        data: dict[tuple[str, str], list[dict[str, Any]]] | None = None,
        functions: dict[tuple[str, str], list[dict[str, Any]]] | None = None,
    ) -> None:
        self.data = data or {}
        self.functions = functions or {}
        self.calls: list[tuple[Any, ...]] = []

    def schema(self, schema: str) -> _FakeSchema:
        self.calls.append(("schema", schema))
        return _FakeSchema(self, schema)


def _uncached(function: Any) -> Any:
    return getattr(function, "__wrapped__", function)


class DataResultTests(unittest.TestCase):
    def test_status_and_sanitized_message_are_preserved(self) -> None:
        result = DataResult.ok(
            rows=[{"value": 1}],
            source="DB 저장 데이터",
            observed_at="2026-08-22T10:00:00Z",
            message="token=very-secret-value https://example.test/private",
        )

        self.assertTrue(result.available)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.rows, [{"value": 1}])
        self.assertNotIn("very-secret-value", result.message or "")
        self.assertNotIn("example.test", result.message or "")
        self.assertFalse(DataResult.empty(source="DB").available)

    def test_all_public_status_factories(self) -> None:
        results = (
            DataResult.empty(source="x"),
            DataResult.unconfigured(source="x"),
            DataResult.offline(source="x"),
            DataResult.blocked(source="x", message="blocked"),
            DataResult.error(source="x", message="error"),
        )
        self.assertEqual(
            [result.status for result in results],
            ["empty", "unconfigured", "offline", "blocked", "error"],
        )
        error = DataResult.error(
            source="x",
            message="failed",
            rows=[{"partial": True}],
            value={"dataset": []},
            observed_at="2026-08-22T00:00:00Z",
        )
        self.assertEqual(error.rows, [{"partial": True}])
        self.assertEqual(error.value, {"dataset": []})
        self.assertEqual(error.observed_at, "2026-08-22T00:00:00Z")


class SelectOnlyGatewayTests(unittest.TestCase):
    def test_gateway_uses_only_select_operations(self) -> None:
        client = _FakeClient(
            {("sample", "facts"): [{"id": 1, "kind": "a"}, {"id": 2, "kind": "b"}]}
        )
        gateway = db.SelectOnlyGateway(client)

        rows = gateway.select_rows(
            schema="sample",
            table="facts",
            columns="id,kind",
            equal={"kind": "a"},
            in_values={"id": [1, 2]},
            order=(("id", True),),
            limit=10,
        )

        self.assertEqual(rows, [{"id": 1, "kind": "a"}])
        operations = {call[0] for call in client.calls}
        self.assertLessEqual(
            operations,
            {"schema", "table", "select", "eq", "in", "order", "limit", "range", "execute"},
        )
        selected = next(call[1] for call in client.calls if call[0] == "select")
        self.assertNotIn("*", selected)

    def test_paged_gateway_uses_range_and_stable_order(self) -> None:
        client = _FakeClient({("sample", "facts"): [{"id": value} for value in range(5)]})
        rows = db.SelectOnlyGateway(client).select_rows(
            schema="sample",
            table="facts",
            columns="id",
            order=(("id", False),),
            page_size=2,
            max_rows=5,
        )

        self.assertEqual([row["id"] for row in rows], [0, 1, 2, 3, 4])
        self.assertEqual(sum(call[0] == "range" for call in client.calls), 3)
        self.assertGreaterEqual(sum(call[0] == "order" for call in client.calls), 3)

    def test_macro_loader_keeps_requested_payload_shape(self) -> None:
        client = _FakeClient(
            {
                ("reporting", "macro_series"): [
                    {
                        "series_id": "VIX",
                        "name_ko": "변동성",
                        "description": None,
                        "country": None,
                        "category": "sentiment",
                        "base_unit": "pts",
                        "timezone": None,
                        "domain": "market_indicator",
                        "series_kind": "oscillator",
                        "source": "yfinance",
                        "frequency": "daily",
                    }
                ],
                ("reporting", "macro_observations"): [
                    {
                        "series_id": "VIX",
                        "obs_date": "2026-08-21",
                        "value": 18.0,
                        "effective_at": "2026-08-21T00:00:00Z",
                        "collected_at": "2026-08-21T00:00:00Z",
                    }
                ],
            }
        )
        with (
            patch.dict(
                "os.environ",
                {"DASHBOARD_OFFLINE": "0", "SUPABASE_URL": "https://db.test", "SUPABASE_SERVICE_KEY": "x"},
                clear=False,
            ),
            patch("investment_agent.platform.db.postgres.service_client", return_value=client),
        ):
            result = _uncached(db.load_macro_data)()

        self.assertEqual(result.status, "ok")
        self.assertEqual(set(result.value), {"indicators", "observations"})
        self.assertEqual(result.value["observations"][0]["value"], 18.0)

    def test_multi_dataset_loaders_keep_public_payload_keys(self) -> None:
        empty_gateway = db.SelectOnlyGateway(_FakeClient())
        with tempfile.TemporaryDirectory() as directory:
            runtime_path = Path(directory) / "runtime.sqlite3"
            research_root = Path(directory) / "research"
            environment = {
                "DASHBOARD_OFFLINE": "0",
                "SUPABASE_URL": "https://db.test",
                "SUPABASE_SERVICE_KEY": "x",
                "AI_INVESTOR_RUNTIME_DB_PATH": str(runtime_path),
                "INVESTMENT_AGENT_RESEARCH_ROOT": str(research_root),
            }
            with (
                patch.dict("os.environ", environment, clear=False),
                patch.object(db, "_gateway", return_value=empty_gateway),
            ):
                from investment_agent.research.storage.repository import ResearchStore

                ResearchStore().allocations()  # 로컬 research DB 스키마를 미리 만든다.
                with runtime_connection():  # 로컬 runtime DB 스키마를 미리 만든다.
                    pass
                results = {
                    "ai": _uncached(db.load_ai_data)("AAPL"),
                    "earnings": _uncached(db.load_earnings_data)(),
                    "guru": _uncached(db.load_guru_data)(),
                    "strategy": _uncached(db.load_strategy_data)(),
                    "target": _uncached(db.load_latest_target)(),
                }

        self.assertEqual(
            set(results["ai"].value),
            {"cases", "signals", "proposals", "risk_decisions", "approvals"},
        )
        self.assertEqual(
            set(results["earnings"].value),
            {
                "core",
                "filings",
                "consensus",
                "watchlist",
                "ticker_profiles",
                "earnings_flash",
            },
        )
        self.assertEqual(
            set(results["guru"].value),
            {"managers", "filings", "positions", "cusip_map", "smart_changes"},
        )
        self.assertEqual(set(results["strategy"].value), {"strategies", "allocations"})
        self.assertEqual(set(results["target"].value), {"risk_decision", "proposal"})

    def test_guru_loader_reads_v1_institutional_rows_and_maps_identifiers(self) -> None:
        """manager_cik/name/fund_name/is_active는 코드 설정이 SSOT이므로
        `institutional.managers`를 흉내 낼 필요가 없다 — 실제 추적 대상 중
        하나(Warren Buffett)의 CIK로 filings/positions만 흉내 낸다."""
        manager_cik = "0001067983"
        client = _FakeClient(
            {
                ("institutional", "filings"): [
                    {
                        "accession_no": f"{manager_cik}-26-000001", "manager_cik": manager_cik,
                        "period_end": "2026-03-31", "form_type": "13F-HR", "report_type": "13F HOLDINGS REPORT",
                        "filing_date": "2026-05-15", "accepted_at": "2026-05-15T12:00:00Z",
                        "amendment_type": None, "amendment_no": None, "reported_value_usd": 100,
                        "reported_line_count": 1, "confidential_omitted": False, "source_url": "https://sec.test/1",
                        "content_sha256": "a" * 64, "ingested_at": "2026-05-15T12:00:00Z",
                    },
                    {
                        "accession_no": f"{manager_cik}-26-000002", "manager_cik": manager_cik,
                        "period_end": "2026-06-30", "form_type": "13F-HR", "report_type": "13F HOLDINGS REPORT",
                        "filing_date": "2026-08-15", "accepted_at": "2026-08-15T12:00:00Z",
                        "amendment_type": None, "amendment_no": None, "reported_value_usd": 120,
                        "reported_line_count": 1, "confidential_omitted": False, "source_url": "https://sec.test/2",
                        "content_sha256": "b" * 64, "ingested_at": "2026-08-15T12:00:00Z",
                    },
                ],
                ("institutional", "positions"): [
                    {
                        "accession_no": f"{manager_cik}-26-000001", "source_row_no": 1, "issuer_name": "Apple",
                        "identifier": "037833100", "identifier_type": "CUSIP", "title_of_class": "COM",
                        "value_usd": 100, "quantity": 10, "quantity_type": "SH", "position_kind": "SHARES",
                        "investment_discretion": None, "other_manager": None, "voting_sole": 10,
                        "voting_shared": 0, "voting_none": 0,
                    },
                    {
                        "accession_no": f"{manager_cik}-26-000002", "source_row_no": 1, "issuer_name": "Apple",
                        "identifier": "037833100", "identifier_type": "CUSIP", "title_of_class": "COM",
                        "value_usd": 120, "quantity": 20, "quantity_type": "SH", "position_kind": "SHARES",
                        "investment_discretion": None, "other_manager": None, "voting_sole": 20,
                        "voting_shared": 0, "voting_none": 0,
                    },
                ],
                ("universe", "security_identifiers"): [{
                    "identifier": "037833100", "identifier_type": "CUSIP", "security_id": 7,
                    "mapping_status": "mapped", "updated_at": "2026-08-15T12:00:00Z",
                }],
                ("universe", "securities"): [{"security_id": 7, "ticker": "AAPL"}],
            },
        )
        with (
            patch.dict("os.environ", {"DASHBOARD_OFFLINE": "0", "SUPABASE_URL": "https://db.test", "SUPABASE_SERVICE_KEY": "x"}, clear=False),
            patch.object(db, "_gateway", return_value=db.SelectOnlyGateway(client)),
        ):
            result = _uncached(db.load_guru_data)()

        self.assertEqual(result.status, "ok")
        self.assertIn(manager_cik, [row["manager_cik"] for row in result.value["managers"]])
        self.assertEqual(result.value["cusip_map"][0]["ticker"], "AAPL")
        self.assertEqual(result.value["positions"][0]["cusip"], "037833100")
        self.assertEqual(result.value["positions"][0]["ticker"], "AAPL")
        self.assertEqual(result.value["smart_changes"], [])
        schemas = [call[1] for call in client.calls if call[0] == "schema"]
        self.assertIn("institutional", schemas)
        self.assertIn("universe", schemas)
        self.assertNotIn("gurus", schemas)

    def test_earnings_view_queries_only_required_base_tables(self) -> None:
        client = _FakeClient(
            {
                ("fundamentals", db.T_FINANCIALS): [
                    {"cik": "0000320193", "source_accession_no": "0000320193-26-000001",
                     "fiscal_year": 2026, "fiscal_period": "Q2", "period_end": "2026-06-30"}
                ],
                ("fundamentals", db.T_FILINGS): [{
                    "accession_no": "0000320193-26-000001", "filing_date": "2026-07-30",
                    "form_type": "10-Q", "available_at": "2026-07-30T20:00:00Z"
                }],
                ("universe", "entities"): [
                    {"cik": "0000320193", "watchlist_sources": ["manual"],
                     "watch_from": "2026-01-01", "is_watchlisted": True,
                     "watchlist_removed_at": None, "updated_at": None}
                ],
                ("universe", "securities"): [
                    {"security_id": 1, "ticker": "AAPL", "cik": "0000320193", "is_tracked": True}
                ],
            },
        )
        with (
            patch.dict(
                "os.environ",
                {"DASHBOARD_OFFLINE": "0", "SUPABASE_URL": "https://db.test", "SUPABASE_SERVICE_KEY": "x"},
                clear=False,
            ),
            patch.object(db, "_gateway", return_value=db.SelectOnlyGateway(client)),
        ):
            result = _uncached(db.load_earnings_data)(section="재무 추이")

        self.assertEqual(result.status, "ok")
        selected_tables = [call[1] for call in client.calls if call[0] == "table"]
        self.assertIn(db.T_FINANCIALS, selected_tables)
        self.assertIn("entities", selected_tables)
        self.assertIn("securities", selected_tables)
        self.assertFalse([call for call in client.calls if call[0] == "rpc"])
        self.assertEqual(result.value["watchlist"][0]["ticker"], "AAPL")
        # v1 행을 화면 계약으로 맞추되 없는 값은 지어내지 않는다.
        self.assertEqual(result.value["watchlist"][0]["id"], 1)
        self.assertEqual(result.value["watchlist"][0]["security_id"], 1)
        self.assertIsNone(result.value["watchlist"][0]["updated_at"])
        self.assertEqual(result.value["filings"], [])
        self.assertEqual(result.value["consensus"], [])

    def test_read_only_function_allowlist_rejects_anything_else(self) -> None:
        gateway = db.SelectOnlyGateway(_FakeClient())
        with self.assertRaises(db.DashboardDataError):
            gateway.select_function_rows(schema="universe", function="watchlist_add")
        with self.assertRaises(db.DashboardDataError):
            gateway.select_function_rows(schema="universe", function="watchlist_sync_toss")
        with self.assertRaises(db.DashboardDataError):
            gateway.select_function_rows(
                schema="universe",
                function="watchlist_members_list",
                arguments={"_tickers": ["AAPL"]},
            )
        self.assertEqual(
            set(db.SelectOnlyGateway.READ_ONLY_FUNCTIONS),
            set(),
        )

    def test_econ_mutations_are_not_allowlisted(self) -> None:
        gateway = db.SelectOnlyGateway(_FakeClient())
        for function in ("append_observations", "append_forecast_versions", "append_schedule_versions"):
            with self.subTest(function=function), self.assertRaises(db.DashboardDataError):
                gateway.select_function_rows(schema="macro", function=function, arguments={"p_rows": []})

    def test_every_function_the_loaders_call_is_allowlisted(self) -> None:
        """loader가 부르는 RPC 이름과 인자가 allowlist에 실제로 있는지 정적으로 확인한다.

        오프라인 테스트는 preflight에서 먼저 끊기므로 이 경로를 밟지 않는다.
        allowlist에 빠진 이름은 운영에서만 터지므로 소스에서 직접 대조한다.
        """

        source = (DASHBOARD_ROOT / "db.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        allowlist = db.SelectOnlyGateway.READ_ONLY_FUNCTIONS
        checked = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not isinstance(function, ast.Attribute) or function.attr != "select_function_rows":
                continue
            keywords = {item.arg: item.value for item in node.keywords}
            name_node = keywords.get("function")
            if not isinstance(name_node, ast.Constant):
                continue
            name = str(name_node.value)
            self.assertIn(name, allowlist, f"allowlist에 없는 함수 호출: {name}")
            argument_node = keywords.get("arguments")
            if isinstance(argument_node, ast.Dict):
                names = {
                    str(key.value)
                    for key in argument_node.keys
                    if isinstance(key, ast.Constant)
                }
                self.assertTrue(
                    names.issubset(allowlist[name]),
                    f"{name} 호출이 allowlist에 없는 인자를 씁니다: {names - allowlist[name]}",
                )
            checked += 1
        self.assertEqual(checked, 0, "v1 dashboard는 watchlist RPC를 호출하지 않습니다")

    def test_unfiltered_earnings_reads_are_scoped_and_paged(self) -> None:
        """관심종목 밖 행을 읽지 않고, PostgREST 상한에서 잘리지 않아야 한다."""

        core_rows = [
            {"ticker": ticker, "period_end": f"2026-{month:02d}-30", "fiscal_period": "Q2"}
            for ticker in ("AAPL", "MSFT", "NOTWATCHED")
            for month in range(1, 13)
        ]
        canonical_rows = [
            {
                **row,
                "cik": "0000320193" if row["ticker"] == "AAPL" else "0000789019",
                "source_accession_no": ("0000320193" if row["ticker"] == "AAPL" else "0000789019")
                    + f"-26-{index:06d}",
                "fiscal_year": 2026,
                "fiscal_period": "Q2",
            }
            for index, row in enumerate(core_rows, start=1)
            if row["ticker"] != "NOTWATCHED"
        ]
        client = _FakeClient(
            {
            ("fundamentals", db.T_FINANCIALS): canonical_rows,
            ("fundamentals", db.T_FILINGS): [
                {"accession_no": row["source_accession_no"], "filing_date": row["period_end"],
                 "form_type": "10-Q", "available_at": "2026-08-01T00:00:00Z"}
                for row in canonical_rows
            ],
                ("universe", "entities"): [
                    {"cik": cik, "watchlist_sources": ["manual"], "watch_from": "2026-01-01",
                     "is_watchlisted": True, "watchlist_removed_at": None, "updated_at": None}
                    for cik in ("0000320193", "0000789019")
                ],
                ("universe", "securities"): [
                    {"security_id": index, "ticker": ticker, "is_tracked": True,
                     "cik": "0000320193" if ticker == "AAPL" else "0000789019"}
                    for index, ticker in enumerate(("AAPL", "MSFT"), start=1)
                ],
            },
        )
        with (
            patch.dict(
                "os.environ",
                {"DASHBOARD_OFFLINE": "0", "SUPABASE_URL": "https://db.test", "SUPABASE_SERVICE_KEY": "x"},
                clear=False,
            ),
            patch.object(db, "_gateway", return_value=db.SelectOnlyGateway(client)),
        ):
            result = _uncached(db.load_earnings_data)(section="재무 추이")

        self.assertEqual(result.status, "ok")
        membership = [call for call in client.calls if call[0] == "in"]
        self.assertTrue(membership, "종목 필터 없는 조회는 관심종목 목록으로 좁혀야 한다")
        # 관심 기업(CIK)을 대표 종목으로 편 뒤 그 security_id로 좁힌다. 둘 중 하나라도
        # 빠지면 관심종목 밖 행이 화면에 들어온다.
        scoped = [call[2] for call in membership]
        self.assertIn(("0000320193", "0000789019"), scoped)
        self.assertIn(("AAPL", "MSFT"), scoped)
        # limit 대신 range를 써야 db-max-rows(기본 1000)에서 조용히 잘리지 않는다.
        self.assertTrue(any(call[0] == "range" for call in client.calls))
        self.assertFalse(any(call[0] == "limit" for call in client.calls))
        self.assertEqual(
            {str(row["ticker"]) for row in result.value["core"]},
            {"AAPL", "MSFT"},
        )

    def test_ticker_loader_keeps_tracked_and_active_watchlist_members(self) -> None:
        client = _FakeClient(
            {
                ("universe", "securities"): [
                    {"security_id": 1, "ticker": "AAPL", "name": "Apple",
                     "cik": "0000000001", "is_tracked": True},
                    {"security_id": 2, "ticker": "PRIVATE", "name": "Private",
                     "cik": "0000000002", "is_tracked": True},
                    {"security_id": 3, "ticker": "REMOVED", "name": "Removed",
                     "cik": "0000000003", "is_tracked": True},
                ],
                ("universe", "entities"): [
                    {"cik": "0000000002", "watchlist_sources": ["manual"],
                     "watch_from": "2026-01-01", "is_watchlisted": True,
                     "watchlist_removed_at": None, "updated_at": None},
                    {"cik": "0000000003", "watchlist_sources": [],
                     "watch_from": "2026-01-01", "is_watchlisted": False,
                     "watchlist_removed_at": "2026-08-20T00:00:00Z", "updated_at": None},
                ],
            },
        )
        with (
            patch.dict(
                "os.environ",
                {
                    "DASHBOARD_OFFLINE": "0",
                    "SUPABASE_URL": "https://db.test",
                    "SUPABASE_SERVICE_KEY": "x",
                },
                clear=False,
            ),
            patch.object(db, "_gateway", return_value=db.SelectOnlyGateway(client)),
        ):
            result = _uncached(db.load_tickers)()

        by_ticker = {row["ticker"]: row for row in result.rows}
        self.assertEqual(set(by_ticker), {"AAPL", "PRIVATE", "REMOVED"})
        self.assertFalse(by_ticker["AAPL"]["watchlist_active"])
        self.assertTrue(by_ticker["PRIVATE"]["watchlist_active"])
        # 관심에서 빠진 회사는 S&P 게이트에는 남아 있어도 관심은 아니다.
        self.assertFalse(by_ticker["REMOVED"]["watchlist_active"])

    def test_execution_loader_keeps_observability_fields_read_only(self) -> None:
        """execution 관측은 이제 Supabase가 아니라 로컬 runtime.sqlite3
        (reporting.local_runtime)가 소유한다 — 실제 SQLite로 검증한다."""
        with tempfile.TemporaryDirectory() as directory:
            runtime_path = Path(directory) / "runtime.sqlite3"
            universe = _FakeClient({("universe", "securities"): [{"security_id": 1, "ticker": "AAPL"}]})
            with (
                patch.dict("os.environ", {"AI_INVESTOR_RUNTIME_DB_PATH": str(runtime_path)}, clear=False),
                patch.object(execution_db, "sb", universe),
            ):
                now = datetime.now(timezone.utc)
                intent = ExecutionIntent(
                    intent_id="intent-1", proposal_id="proposal-1", risk_decision_id="risk-1",
                    execution_mode="live", target_weights={"AAPL": .1, "CASH": .9}, input_hash="a" * 64,
                    not_before=now - timedelta(minutes=1), expires_at=now + timedelta(hours=1),
                )
                repo = execution_db.ExecutionRepository()
                repo.save_intent(intent.as_row())
                repo.create_planned_order({
                    "client_order_id": "order-1", "intent_id": "intent-1", "account_seq": 7,
                    "ticker": "AAPL", "status": "planned",
                })
                repo.update_order_execution("order-1", status="submitted", broker_order_id="broker-1")
                repo.update_order_execution("order-1", status="filled", broker_order_id="broker-1")

                result = _uncached(db.load_execution_data)()

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.value["orders"][0]["ticker"], "AAPL")
        self.assertNotIn("raw_broker_response", result.value["orders"][0])

    def test_account_snapshot_loader_reports_the_safe_daily_rollup_only(self) -> None:
        """account_daily_snapshots는 안전한 롤업 필드만 갖는 표라 raw_snapshot이
        구조적으로 들어갈 자리가 없다 — holdings 상세 join도 더 이상 하지 않는다."""
        with tempfile.TemporaryDirectory() as directory:
            runtime_path = Path(directory) / "runtime.sqlite3"
            with patch.dict("os.environ", {"AI_INVESTOR_RUNTIME_DB_PATH": str(runtime_path)}, clear=False):
                execution_db.ExecutionRepository().save_account_snapshot({
                    "execution_mode": "paper", "broker_account_hash": "acct-1",
                    "equity": 1_250.0, "cash": 250.0, "buying_power": 250.0,
                    "captured_at": "2026-09-05T00:00:00+00:00",
                    "raw_snapshot": {"must_not_be_read": True},
                })

                result = _uncached(db.load_latest_account_snapshot)()

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.value["equity"], 1_250.0)
        self.assertEqual(result.value["holdings"], [])
        self.assertNotIn("raw_snapshot", result.value)

    def test_price_loader_reads_persisted_market_rows_with_yfinance_shape(self) -> None:
        client = _FakeClient(
            {
                ("universe", db.T_SECURITIES): [
                    {"security_id": 1, "ticker": "AAPL", "cik": None},
                    {"security_id": 2, "ticker": "SPY", "cik": None},
                ],
                ("market", db.T_PRICES_DAILY): [
                    {
                        "security_id": 1,
                        "trade_date": "2026-09-01",
                        "open": 10.0,
                        "high": 12.0,
                        "low": 9.0,
                        "close": 11.0,
                        "volume": 100.0,
                        "source": "test",
                        "ingested_at": "2026-09-01T00:00:00Z",
                    },
                    {
                        "security_id": 2,
                        "trade_date": "2026-09-01",
                        "open": 20.0,
                        "high": 22.0,
                        "low": 19.0,
                        "close": 21.0,
                        "volume": 200.0,
                        "source": "test",
                        "ingested_at": "2026-09-01T00:00:00Z",
                    },
                ],
            }
        )
        with (
            patch.dict(
                "os.environ",
                {
                    "DASHBOARD_OFFLINE": "0",
                    "SUPABASE_URL": "https://db.test",
                    "SUPABASE_SERVICE_KEY": "x",
                },
                clear=False,
            ),
            patch.object(db, "_gateway", return_value=db.SelectOnlyGateway(client)),
        ):
            result = _uncached(db.load_price_history)(["AAPL", "SPY"], period="1mo")
            single_result = _uncached(db.load_price_history)("AAPL", period="1mo")

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.observed_at, "2026-09-01T00:00:00+00:00")
        self.assertEqual(result.value.columns.names, ["Price", "Ticker"])
        self.assertEqual(result.value.loc[result.value.index[0], ("Close", "SPY")], 21.0)
        self.assertEqual(single_result.status, "ok")
        self.assertNotIsInstance(single_result.value.columns, pd.MultiIndex)
        self.assertEqual(single_result.value.loc[single_result.value.index[0], "Close"], 11.0)
        selected_columns = [call[1] for call in client.calls if call[0] == "select"]
        self.assertFalse(any("*" in columns for columns in selected_columns))


class OfflineBoundaryTests(unittest.TestCase):
    def test_offline_db_loader_never_builds_client(self) -> None:
        with (
            patch.dict("os.environ", {"DASHBOARD_OFFLINE": "1"}, clear=False),
            patch.object(db, "_gateway", side_effect=AssertionError("network boundary crossed")),
        ):
            result = _uncached(db.load_macro_data)()
        self.assertEqual(result.status, "offline")

    def test_offline_external_loaders_do_not_import_network_clients(self) -> None:
        with patch.dict("os.environ", {"DASHBOARD_OFFLINE": "1"}, clear=False):
            price = _uncached(db.load_price_history)(["SPY"])
            news = _uncached(reporting_news.load_live_news)("market", ticker="SPY")
        self.assertEqual({price.status, news.status}, {"offline"})

    def test_harness_reader_does_not_change_file(self) -> None:
        state = {
            "version": 1,
            "process_id": 123,
            "process_started_at": "2026-08-22T10:00:00+00:00",
            "process_heartbeat_at": "2026-08-22T10:01:00+00:00",
            "stopped_at": None,
            "stopped_cleanly": False,
            "recovery_count": 0,
            "jobs": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            original = json.dumps(state, ensure_ascii=False)
            path.write_text(original, encoding="utf-8")

            with patch.object(ops, "_pid_exists_readonly", return_value=False):
                result = _uncached(ops.read_harness_state)(path)

            self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertEqual(result.status, "ok")
        self.assertIn("health", result.value)
        self.assertEqual(result.value["health"]["process_status"], "pid_not_alive")
        self.assertEqual(result.value["health"]["status"], "pid_not_alive")
        self.assertEqual(result.value["health"]["label"], "프로세스 종료")
        self.assertFalse(result.value["health"]["pid_alive"])
        self.assertIn("heartbeat_age_seconds", result.value["health"])

    def test_harness_pid_check_failure_remains_unknown(self) -> None:
        state = {
            "process_id": 456,
            "process_heartbeat_at": "2026-08-22T10:01:00+00:00",
            "stopped_cleanly": False,
            "jobs": {},
        }
        with patch.object(
            ops,
            "_pid_exists_readonly",
            side_effect=PermissionError("denied"),
        ):
            health = ops._harness_health(state)
        self.assertIsNone(health["pid_alive"])
        self.assertTrue(health["pid_check_error"])

class DashboardStaticBoundaryTests(unittest.TestCase):
    @staticmethod
    def _read_only_rpc_line_range() -> tuple[int, int]:
        """`.rpc()` 예외를 허용할 유일한 메서드의 줄 범위를 소스에서 직접 찾는다."""

        module = ast.parse((DASHBOARD_ROOT / "db.py").read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if isinstance(node, ast.ClassDef) and node.name == "SelectOnlyGateway":
                for member in node.body:
                    if (
                        isinstance(member, ast.FunctionDef)
                        and member.name == "select_function_rows"
                    ):
                        return member.lineno, (member.end_lineno or member.lineno)
        raise AssertionError("SelectOnlyGateway.select_function_rows를 찾지 못했습니다.")

    def test_dashboard_python_has_no_mutating_or_execution_boundary(self) -> None:
        violations: list[str] = []
        forbidden_modules = {
            "subprocess",
            "investment_agent.trading.decision.portfolio_shadow",
            "investment_agent.execution.brokers.toss.orders",
            "investment_agent.notifications.channels.discord",
            # 룰 재현 백테스트는 순수 계산 함수만 쓴다. 전략 적재 경로는 닿지 않는다.
            "investment_agent.research.strategies.etl",
            "investment_agent.research.strategies.db",
        }
        forbidden_calls = {
            "upsert",
            "delete",
            "rpc",
            "post",
            "post_message",
            "send_webhook",
            "create_forum_thread",
        }
        db_receiver_names = {"sb", "client", "query", "builder", "gateway", "repository"}
        # `.rpc()`는 원칙적으로 금지다. 유일한 예외는 비공개 alerts 스키마를 읽기 위한
        # SelectOnlyGateway.select_function_rows 하나이며, 그 안에서도 allowlist에
        # 있는 STABLE 함수만 부를 수 있다(위 allowlist 회귀 테스트가 범위를 고정한다).
        rpc_exemption = self._read_only_rpc_line_range()

        for path in sorted(DASHBOARD_ROOT.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            relative = path.relative_to(ROOT).as_posix()
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in forbidden_modules:
                            violations.append(f"{relative}:{node.lineno} import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module in forbidden_modules or module.startswith("investment_agent.execution.brokers.toss.orders"):
                        violations.append(f"{relative}:{node.lineno} from {module}")
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    lowered = node.value.lower()
                    if "portfolio_shadow" in lowered or "toss_orders" in lowered:
                        violations.append(f"{relative}:{node.lineno} forbidden target string")
                elif isinstance(node, ast.Call):
                    for keyword in node.keywords:
                        if keyword.arg == "use_container_width":
                            violations.append(f"{relative}:{node.lineno} deprecated width keyword")
                    function = node.func
                    if not isinstance(function, ast.Attribute):
                        continue
                    attribute = function.attr
                    receiver = ast.get_source_segment(source, function.value) or ""
                    exempt = (
                        attribute == "rpc"
                        and relative == "src/investment_agent/dashboard/db.py"
                        and rpc_exemption[0] <= node.lineno <= rpc_exemption[1]
                    )
                    if attribute in forbidden_calls and not exempt:
                        violations.append(f"{relative}:{node.lineno} call .{attribute}()")
                    if attribute == "insert" and receiver != "sys.path":
                        violations.append(f"{relative}:{node.lineno} call .insert()")
                    if attribute == "update" and any(
                        name in receiver.lower() for name in db_receiver_names
                    ):
                        violations.append(f"{relative}:{node.lineno} DB-like .update()")

        self.assertEqual(violations, [], "\n".join(violations))

    #: 두 모듈이 같은 이름으로 같은 조회를 각자 구현하는 잔여 구간.
    #: 화면은 `reporting.readers.dashboard` 쪽만 import한다 — `dashboard.db` 쪽은
    #: 이 테스트 파일이 게이트웨이 동작을 확인하려고 붙잡고 있는 마지막 소비자다.
    #: **줄어들기만 해야 한다.** 늘어나면 같은 숫자를 두 곳이 각자 말하기 시작하고,
    #: 실제로 그렇게 해서 `reporting.macro_measures` 결함이 양쪽에 동시에 있었다.
    _KNOWN_OVERLAP = frozenset({
        "load_execution_data", "load_guru_data", "load_price_history",
        "load_strategy_data", "load_tickers",
    })

    def test_required_public_loader_names_exist(self) -> None:
        expected_db = {
            "load_macro_data",
            "load_execution_data",
            "load_tickers",
            "load_ai_data",
            "load_alpha_lab_data",
            "load_earnings_data",
            "load_earnings_discord_support",
            "load_earnings_extended",
            "load_guru_data",
            "load_strategy_data",
            "load_latest_target",
            "load_latest_account_snapshot",
            "load_price_history",
            "load_reporting_view",
        }
        expected_reporting = {
            "load_econ_upcoming",
            "load_econ_recent_results",
            "load_econ_calendar_window",
            "load_econ_series",
            "load_econ_series_history",
            "load_econ_detail",
            "load_macro_window",
        }
        from investment_agent.reporting.readers import dashboard as reporting_dashboard

        expected_ops = {"read_harness_state"}
        expected_news = {"load_live_news", "provider_statuses"}
        self.assertTrue(all(callable(getattr(db, name, None)) for name in expected_db))
        self.assertTrue(all(callable(getattr(reporting_dashboard, name, None))
                            for name in expected_reporting))
        self.assertTrue(all(callable(getattr(ops, name, None)) for name in expected_ops))
        self.assertTrue(all(callable(getattr(reporting_news, name, None)) for name in expected_news))

    def test_the_two_reader_modules_do_not_grow_new_duplicates(self) -> None:
        """같은 조회가 두 모듈에 각자 있으면 한쪽만 고치는 사고가 난다."""
        from investment_agent.reporting.readers import dashboard as reporting_dashboard

        both = {
            name for name in dir(db)
            if name.startswith("load_") and callable(getattr(db, name, None))
            and callable(getattr(reporting_dashboard, name, None))
        }
        self.assertEqual(self._KNOWN_OVERLAP, both)

    def test_load_reporting_view_delegates_to_queries(self) -> None:
        from investment_agent.reporting.readers.financial import VIEWS
        row = dict.fromkeys(VIEWS["securities"].columns.split(","), "x") | {"ticker": "NVDA", "company_name": "NVIDIA"}
        client = _FakeClient({("reporting", "securities"): [row]})
        with (
            patch.dict(
                "os.environ",
                {"DASHBOARD_OFFLINE": "0", "SUPABASE_URL": "https://db.test", "SUPABASE_SERVICE_KEY": "x"},
                clear=False,
            ),
            patch("investment_agent.platform.db.postgres.service_client", return_value=client),
        ):
            result = db.load_reporting_view("securities", equals={"ticker": "NVDA"})
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.rows, [row])


if __name__ == "__main__":
    unittest.main()
