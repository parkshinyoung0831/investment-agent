"""화면이 실제로 쓰는 reporting reader(`readers/dashboard.py`)의 공개 계약을 검증한다.

execution 관측·가격·13F·전략·거시 로더가 화면에 내는 payload 모양과 상태를 고정한다.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd

from investment_agent.reporting.models import DataResult

from investment_agent.execution import db as execution_db
from investment_agent.execution.orders.intents import ExecutionIntent
from investment_agent.reporting.readers import dashboard as reader


def _uncached(function: Any) -> Any:
    return getattr(function, "__wrapped__", function)


class _EmptyClient:
    """local runtime view만 읽는 경로가 Supabase 연결을 만들지 않았는지 확인하는 대역."""

    def schema(self, name: str) -> "_EmptyClient":  # pragma: no cover - 호출되면 안 된다
        raise AssertionError(f"local runtime view must not query Supabase schema {name}")


class ExecutionReaderContractTest(unittest.TestCase):
    def _seed(self, runtime_path: Path) -> None:
        universe = _FakeUniverse()
        with patch.object(execution_db, "sb", universe):
            now = datetime.now(timezone.utc)
            intent = ExecutionIntent(
                intent_id="intent-1", proposal_id="proposal-1", risk_decision_id="risk-1",
                execution_mode="live", target_weights={"AAPL": .1, "CASH": .9}, input_hash="a" * 64,
                not_before=now - timedelta(minutes=1), expires_at=now + timedelta(hours=1),
            )
            repository = execution_db.ExecutionRepository()
            repository.save_intent(intent.as_row())
            repository.create_planned_order({
                "client_order_id": "order-1", "intent_id": "intent-1", "account_seq": 7,
                "ticker": "AAPL", "status": "planned",
            })
            repository.update_order_execution("order-1", status="submitted", broker_order_id="broker-1")
            repository.update_order_execution("order-1", status="filled", broker_order_id="broker-1")

    def test_execution_reader_exposes_observability_fields_without_raw_broker_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_path = Path(directory) / "runtime.sqlite3"
            env = {
                "AI_INVESTOR_RUNTIME_DB_PATH": str(runtime_path),
                "DASHBOARD_OFFLINE": "0",
                "SUPABASE_URL": "https://db.test",
                "SUPABASE_SERVICE_KEY": "x",
            }
            with patch.dict("os.environ", env, clear=False):
                self._seed(runtime_path)
                with patch.object(reader, "service_client", return_value=_EmptyClient()):
                    result = _uncached(reader.load_execution_data)()

        self.assertEqual("ok", result.status)
        self.assertEqual("AAPL", result.value["orders"][0]["ticker"])
        self.assertNotIn("raw_broker_response", result.value["orders"][0])
        self.assertEqual({"intent-1"}, {row["intent_id"] for row in result.value["intents"]})

    def test_execution_reader_is_offline_safe(self) -> None:
        with patch.dict("os.environ", {"DASHBOARD_OFFLINE": "1"}, clear=False), \
                patch.object(reader, "service_client", side_effect=AssertionError("no client offline")):
            result = _uncached(reader.load_execution_data)()
        self.assertEqual("offline", result.status)


class _ViewRecorder:
    """`_read`를 대신해 요청된 reporting view와 필터를 기록하고 준비한 행을 돌려준다."""

    def __init__(self, rows: dict[str, list[dict[str, Any]]]):
        self.rows = rows
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, view: str, **kwargs: Any) -> DataResult:
        self.calls.append((view, kwargs))
        rows = self.rows.get(view, [])
        tickers = (kwargs.get("in_values") or {}).get("ticker")
        if tickers:
            rows = [row for row in rows if row.get("ticker") in tickers]
        return DataResult.ok(rows=rows, source=f"reporting.{view}") if rows else DataResult.empty(source=f"reporting.{view}")


class PriceReaderContractTest(unittest.TestCase):
    ROWS = [
        {"ticker": "AAPL", "trade_date": "2026-09-01", "open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0, "volume": 100.0},
        {"ticker": "SPY", "trade_date": "2026-09-01", "open": 20.0, "high": 22.0, "low": 19.0, "close": 21.0, "volume": 200.0},
    ]

    def test_prices_keep_the_yfinance_shape_for_one_and_many_tickers(self) -> None:
        recorder = _ViewRecorder({"prices_daily": self.ROWS})
        with patch.object(reader, "_read", recorder):
            many = _uncached(reader.load_price_history)(["AAPL", "SPY"], period="1mo")
            single = _uncached(reader.load_price_history)("AAPL", period="1mo")
        self.assertEqual("ok", many.status)
        self.assertEqual(["Price", "Ticker"], many.value.columns.names)
        self.assertEqual(21.0, many.value.loc[many.value.index[0], ("Close", "SPY")])
        self.assertNotIsInstance(single.value.columns, pd.MultiIndex)
        self.assertEqual(11.0, single.value.loc[single.value.index[0], "Close"])
        self.assertEqual({"prices_daily"}, {view for view, _ in recorder.calls})

    def test_prices_reject_bad_symbols_and_periods_without_reading(self) -> None:
        recorder = _ViewRecorder({})
        with patch.object(reader, "_read", recorder):
            self.assertEqual("blocked", _uncached(reader.load_price_history)("AAPL; DROP", period="1mo").status)
            self.assertEqual("blocked", _uncached(reader.load_price_history)("AAPL", period="forever").status)
            self.assertEqual("blocked", _uncached(reader.load_price_history)([f"T{i}" for i in range(41)]).status)
        self.assertEqual([], recorder.calls)


class GuruReaderContractTest(unittest.TestCase):
    CIK = "0001067983"

    def test_guru_payload_keeps_public_keys_and_reads_only_reporting_views(self) -> None:
        recorder = _ViewRecorder({
            "institutional_filings": [{"accession_no": "acc-1", "manager_cik": self.CIK, "period_end": "2026-06-30"}],
            "institutional_positions": [{"accession_no": "acc-1", "cusip": "037833100", "ticker": "AAPL", "value_usd": 120}],
        })
        managers = [{"manager_cik": self.CIK, "name": "Warren Buffett", "is_active": True}]
        with patch.object(reader, "_read", recorder), patch.object(reader, "guru_managers", return_value=managers):
            result = _uncached(reader.load_guru_data)()
        self.assertEqual("ok", result.status)
        self.assertEqual({"managers", "filings", "positions", "cusip_map", "smart_changes"}, set(result.value))
        self.assertEqual("AAPL", result.value["cusip_map"][0]["ticker"])
        self.assertEqual([], result.value["smart_changes"])
        self.assertEqual({"institutional_filings", "institutional_positions"}, {view for view, _ in recorder.calls})
        self.assertEqual((self.CIK,), recorder.calls[0][1]["in_values"]["manager_cik"])

    def test_guru_without_managers_or_filings_is_empty_not_an_error(self) -> None:
        with patch.object(reader, "_read", _ViewRecorder({})), patch.object(reader, "guru_managers", return_value=[]):
            result = _uncached(reader.load_guru_data)()
        self.assertEqual("empty", result.status)


class StrategyReaderContractTest(unittest.TestCase):
    def _load(self, payload: dict[str, Any] | Exception) -> DataResult:
        target = "investment_agent.reporting.readers.research.load_local_strategy_data"
        with patch(target, side_effect=payload if isinstance(payload, Exception) else None,
                   return_value=None if isinstance(payload, Exception) else payload):
            return _uncached(reader.load_strategy_data)()

    def test_strategy_payload_keys_and_statuses(self) -> None:
        ok = self._load({"strategies": [{"strategy_id": "s1"}], "allocations": []})
        self.assertEqual("ok", ok.status)
        self.assertEqual({"strategies", "allocations"}, set(ok.value))
        self.assertEqual("empty", self._load({"strategies": [], "allocations": []}).status)

    def test_strategy_failure_is_an_error_card_not_an_exception(self) -> None:
        self.assertEqual("error", self._load(RuntimeError("duckdb busy")).status)


class MacroReaderContractTest(unittest.TestCase):
    def test_macro_window_requests_only_the_scoped_series_in_a_bounded_range(self) -> None:
        recorder = _ViewRecorder({"macro_observations": [{"series_id": "VIX", "obs_date": "2026-08-21", "value": 18.0}]})
        with patch.object(reader, "_read", recorder):
            result = _uncached(reader.load_macro_window)("core")
        self.assertEqual("ok", result.status)
        (view, kwargs), = recorder.calls
        self.assertEqual("macro_observations", view)
        self.assertTrue(kwargs["in_values"]["series_id"])
        self.assertLess(kwargs["start"], kwargs["end"])

    def test_macro_window_rejects_an_unknown_scope_without_reading(self) -> None:
        recorder = _ViewRecorder({})
        with patch.object(reader, "_read", recorder):
            result = _uncached(reader.load_macro_window)("everything")
        self.assertEqual("blocked", result.status)
        self.assertEqual([], recorder.calls)


class _FakeUniverse:
    """`ExecutionRepository`가 ticker→security_id를 찾는 universe 조회만 흉내낸다."""

    def schema(self, name: str) -> "_FakeUniverse":
        return self

    def table(self, name: str) -> "_FakeUniverse":
        return self

    def select(self, *_args: Any, **_kwargs: Any) -> "_FakeUniverse":
        return self

    def eq(self, *_args: Any, **_kwargs: Any) -> "_FakeUniverse":
        return self

    def in_(self, *_args: Any, **_kwargs: Any) -> "_FakeUniverse":
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> "_FakeUniverse":
        return self

    def range(self, *_args: Any, **_kwargs: Any) -> "_FakeUniverse":
        return self

    def order(self, *_args: Any, **_kwargs: Any) -> "_FakeUniverse":
        return self

    def execute(self) -> Any:
        return type("Response", (), {"data": [{"security_id": 1, "ticker": "AAPL", "is_active_listing": True}]})()


if __name__ == "__main__":
    unittest.main()
