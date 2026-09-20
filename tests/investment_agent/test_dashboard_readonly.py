"""대시보드 데이터 계층의 읽기 전용 경계를 오프라인으로 검증한다."""

from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from investment_agent.dashboard import ops
from investment_agent.execution import db as execution_db
from investment_agent.platform.db.sqlite import runtime_connection
from investment_agent.reporting.models import DataResult
from investment_agent.reporting.readers import ai as reader_ai
from investment_agent.reporting.readers import dashboard as reporting_dashboard
from investment_agent.reporting.readers import earnings as reader_earnings
from investment_agent.reporting.readers import select_only
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
        gateway = select_only.SelectOnlyGateway(client)

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
        rows = select_only.SelectOnlyGateway(client).select_rows(
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


    def test_multi_dataset_loaders_keep_public_payload_keys(self) -> None:
        empty_gateway = select_only.SelectOnlyGateway(_FakeClient())
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
                patch.object(reader_ai, "open_gateway", return_value=empty_gateway),
                patch.object(reader_earnings, "open_gateway", return_value=empty_gateway),
            ):
                from investment_agent.research.storage.repository import ResearchStore

                ResearchStore().allocations()  # 로컬 research DB 스키마를 미리 만든다.
                with runtime_connection():  # 로컬 runtime DB 스키마를 미리 만든다.
                    pass
                results = {
                    "ai": _uncached(reader_ai.load_ai_data)("AAPL"),
                    "earnings": _uncached(reader_earnings.load_earnings_data)(),
                    "target": _uncached(reporting_dashboard.load_latest_target)(),
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
        self.assertEqual(set(results["target"].value), {"risk_decision", "proposal"})


    def test_earnings_view_queries_only_required_base_tables(self) -> None:
        client = _FakeClient(
            {
                ("fundamentals", reader_earnings.T_FINANCIALS): [
                    {"cik": "0000320193", "accession_no": "0000320193-26-000001",
                     "fiscal_year": 2026, "fiscal_period": "Q2", "period_end": "2026-06-30"}
                ],
                ("fundamentals", reader_earnings.T_FILINGS): [{
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
            patch.object(reader_earnings, "open_gateway", return_value=select_only.SelectOnlyGateway(client)),
        ):
            result = _uncached(reader_earnings.load_earnings_data)(section="재무 추이")

        self.assertEqual(result.status, "ok")
        selected_tables = [call[1] for call in client.calls if call[0] == "table"]
        self.assertIn(reader_earnings.T_FINANCIALS, selected_tables)
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

    def test_the_gateway_has_no_rpc_capability_at_all(self) -> None:
        """RPC는 allowlist로 걸러 내는 것이 아니라 코드에 존재하지 않는다."""
        gateway = select_only.SelectOnlyGateway(_FakeClient())
        self.assertFalse(hasattr(gateway, "select_function_rows"))
        self.assertFalse(hasattr(select_only.SelectOnlyGateway, "READ_ONLY_FUNCTIONS"))
        for name in ("watchlist_add", "watchlist_sync_toss", "append_observations", "append_forecast_versions"):
            with self.subTest(function=name), self.assertRaises(AttributeError):
                gateway.select_function_rows(schema="universe", function=name)

    def test_no_reader_or_screen_source_calls_rpc(self) -> None:
        roots = (ROOT / "src" / "investment_agent" / "reporting" / "readers", DASHBOARD_ROOT)
        offenders = []
        for root in roots:
            for path in sorted(root.rglob("*.py")):
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"rpc", "select_function_rows"}:
                        offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
        self.assertEqual([], offenders)

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
                "accession_no": ("0000320193" if row["ticker"] == "AAPL" else "0000789019")
                    + f"-26-{index:06d}",
                "fiscal_year": 2026,
                "fiscal_period": "Q2",
            }
            for index, row in enumerate(core_rows, start=1)
            if row["ticker"] != "NOTWATCHED"
        ]
        client = _FakeClient(
            {
            ("fundamentals", reader_earnings.T_FINANCIALS): canonical_rows,
            ("fundamentals", reader_earnings.T_FILINGS): [
                {"accession_no": row["accession_no"], "filing_date": row["period_end"],
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
            patch.object(reader_earnings, "open_gateway", return_value=select_only.SelectOnlyGateway(client)),
        ):
            result = _uncached(reader_earnings.load_earnings_data)(section="재무 추이")

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
        from investment_agent.reporting.readers.financial import VIEWS

        columns = VIEWS["securities"].columns.split(",")
        client = _FakeClient(
            {
                ("reporting", "securities"): [
                    dict.fromkeys(columns) | {"security_id": 1, "ticker": "AAPL", "is_tracked": True,
                                              "is_watchlisted": False, "watchlist_sources": []},
                    dict.fromkeys(columns) | {"security_id": 2, "ticker": "PRIVATE", "is_tracked": True,
                                              "is_watchlisted": True, "watchlist_sources": ["manual"]},
                    dict.fromkeys(columns) | {"security_id": 3, "ticker": "REMOVED", "is_tracked": True,
                                              "is_watchlisted": False, "watchlist_sources": []},
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
            patch("investment_agent.reporting.readers.dashboard.service_client", return_value=client),
        ):
            result = _uncached(reporting_dashboard.load_tickers)()

        by_ticker = {row["ticker"]: row for row in result.rows}
        self.assertEqual(set(by_ticker), {"AAPL", "PRIVATE", "REMOVED"})
        self.assertFalse(by_ticker["AAPL"]["watchlist_active"])
        self.assertTrue(by_ticker["PRIVATE"]["watchlist_active"])
        # 관심에서 빠진 회사는 S&P 게이트에는 남아 있어도 관심은 아니다.
        self.assertFalse(by_ticker["REMOVED"]["watchlist_active"])


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

                result = _uncached(reporting_dashboard.load_latest_account_snapshot)()

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.value["equity"], 1_250.0)
        self.assertEqual(result.value["holdings"], [])
        self.assertNotIn("raw_snapshot", result.value)



class OfflineBoundaryTests(unittest.TestCase):
    def test_offline_db_loader_never_builds_client(self) -> None:
        with (
            patch.dict("os.environ", {"DASHBOARD_OFFLINE": "1"}, clear=False),
            patch.object(reader_ai, "open_gateway", side_effect=AssertionError("network boundary crossed")),
            patch.object(reporting_dashboard, "service_client", side_effect=AssertionError("network boundary crossed")),
        ):
            gateway_result = _uncached(reader_ai.load_ai_data)("AAPL")
            reader_result = _uncached(reporting_dashboard.load_macro_window)()
        self.assertEqual({gateway_result.status, reader_result.status}, {"offline"})

    def test_offline_external_loaders_do_not_import_network_clients(self) -> None:
        with patch.dict("os.environ", {"DASHBOARD_OFFLINE": "1"}, clear=False):
            price = _uncached(reporting_dashboard.load_price_history)(["SPY"])
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
    def test_dashboard_python_has_no_mutating_or_execution_boundary(self) -> None:
        violations: list[str] = []
        forbidden_modules = {
            "subprocess",
            "investment_agent.trading.decision.analysis",
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
        # `.rpc()`는 예외 없이 금지다. dashboard에는 저장소를 여는 코드가 없고 gateway도 RPC를 갖지 않는다.

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
                    if "trading.decision.analysis" in lowered or "toss_orders" in lowered:
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
                    if attribute in forbidden_calls:
                        violations.append(f"{relative}:{node.lineno} call .{attribute}()")
                    if attribute == "insert" and receiver != "sys.path":
                        violations.append(f"{relative}:{node.lineno} call .insert()")
                    if attribute == "update" and any(
                        name in receiver.lower() for name in db_receiver_names
                    ):
                        violations.append(f"{relative}:{node.lineno} DB-like .update()")

        self.assertEqual(violations, [], "\n".join(violations))

    #: 두 모듈이 같은 이름의 조회를 각자 구현하는 자리는 없다.
    _KNOWN_OVERLAP: frozenset[str] = frozenset()

    def test_required_public_loader_names_exist(self) -> None:
        expected_db = {
            (reader_ai, "load_ai_data"),
            (reader_earnings, "load_earnings_data"),
            (reader_earnings, "load_earnings_discord_support"),
            (reader_earnings, "load_earnings_extended"),
            (reader_earnings, "load_ticker_data_quality"),
        }
        expected_reporting = {
            "load_econ_upcoming",
            "load_econ_recent_results",
            "load_econ_calendar_window",
            "load_econ_series",
            "load_econ_series_history",
            "load_econ_detail",
            "load_macro_window",
            "load_tickers",
            "load_alpha_lab_data",
            "load_latest_target",
            "load_system_portfolio_data",
            "load_latest_account_snapshot",
        }
        from investment_agent.reporting.readers import dashboard as reporting_dashboard

        expected_ops = {"read_harness_state"}
        expected_news = {"load_live_news", "provider_statuses"}
        self.assertTrue(all(callable(getattr(module, name, None)) for module, name in expected_db))
        self.assertTrue(all(callable(getattr(reporting_dashboard, name, None))
                            for name in expected_reporting))
        self.assertTrue(all(callable(getattr(ops, name, None)) for name in expected_ops))
        self.assertTrue(all(callable(getattr(reporting_news, name, None)) for name in expected_news))

    def test_the_two_reader_modules_do_not_grow_new_duplicates(self) -> None:
        """같은 조회가 두 모듈에 각자 있으면 한쪽만 고치는 사고가 난다."""
        from investment_agent.reporting.readers import dashboard as reporting_dashboard

        both = {
            name for module in (reader_ai, reader_earnings) for name in dir(module)
            if name.startswith("load_") and callable(getattr(module, name, None))
            and callable(getattr(reporting_dashboard, name, None))
        }
        self.assertEqual(self._KNOWN_OVERLAP, both)



if __name__ == "__main__":
    unittest.main()
