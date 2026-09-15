"""System Portfolio: 비중 기반 NAV, 목표 적용 시점, 재조정 주기, 사람의 선택과의 독립."""
from __future__ import annotations

import ast
import json
import math
import random
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from investment_agent.platform.db.sqlite import runtime_connection
from investment_agent.research.features.factors import FactorScore
from investment_agent.trading.contracts import ContractError
from investment_agent.trading.decision.alpha import AlphaPlan, ThesisView
from investment_agent.trading.portfolio.contracts import PortfolioProposal, RiskDecision
from investment_agent.trading.risk.gate import PortfolioRiskPolicy
from investment_agent.trading.system.accounting import (
    INITIAL_NAV,
    SessionPrice,
    advance,
    first_session_after,
    performance_summary,
    session_price,
)
from investment_agent.trading.system.engine import run_system
from investment_agent.trading.system.store import SystemPortfolioStore

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[4]


class AccountingTest(unittest.TestCase):
    def test_first_session_starts_at_100_and_pays_the_cost_of_building_the_target(self):
        mark = advance(None, trade_date="2026-09-15", prices={"AAA": SessionPrice(50.0)},
                       benchmark=SessionPrice(400.0), target={"AAA": 0.5, "CASH": 0.5}, target_id="t1",
                       cost_rates={"AAA": 0.001})
        self.assertAlmostEqual(mark.nav, INITIAL_NAV * (1 - 0.5 * 0.001))
        self.assertEqual(mark.weights, {"AAA": 0.5, "CASH": 0.5})
        self.assertEqual(mark.benchmark_nav, INITIAL_NAV)
        self.assertAlmostEqual(mark.turnover, 0.5)
        self.assertEqual(mark.applied_target_id, "t1")

    def test_prices_move_nav_and_weights_drift(self):
        start = advance(None, trade_date="2026-09-15", prices={"AAA": SessionPrice(50.0)}, benchmark=SessionPrice(400.0),
                        target={"AAA": 0.5, "CASH": 0.5}, cost_rates={"AAA": 0.0})
        mark = advance(start, trade_date="2026-09-16", prices={"AAA": SessionPrice(55.0)}, benchmark=SessionPrice(404.0))
        self.assertAlmostEqual(mark.nav, 105.0)  # 절반이 10% 올랐다
        self.assertAlmostEqual(mark.weights["AAA"], 0.55 / 1.05)
        self.assertAlmostEqual(mark.benchmark_nav, 101.0)
        self.assertEqual(mark.turnover, 0.0)

    def test_split_rebase_keeps_value_and_dividend_is_total_return(self):
        start = advance(None, trade_date="2026-09-15", prices={"AAA": SessionPrice(200.0)}, benchmark=SessionPrice(400.0),
                        target={"AAA": 1.0, "CASH": 0.0}, cost_rates={"AAA": 0.0})
        split = advance(start, trade_date="2026-09-16", prices={"AAA": SessionPrice(50.0, split_ratio=4.0)},
                        benchmark=SessionPrice(400.0))
        self.assertAlmostEqual(split.nav, INITIAL_NAV)
        paid = advance(split, trade_date="2026-09-17", prices={"AAA": SessionPrice(49.5, dividend=0.5)},
                       benchmark=SessionPrice(400.0))
        self.assertAlmostEqual(paid.nav, INITIAL_NAV)  # 배당락만큼 빠진 가격을 배당이 채운다

    def test_stale_close_is_carried_and_flagged(self):
        start = advance(None, trade_date="2026-09-15", prices={"AAA": SessionPrice(50.0)}, benchmark=SessionPrice(400.0),
                        target={"AAA": 0.5, "CASH": 0.5}, cost_rates={"AAA": 0.0})
        halted = advance(start, trade_date="2026-09-16", prices={}, benchmark=SessionPrice(401.0))
        self.assertEqual(halted.stale_price_tickers, ("AAA",))
        self.assertAlmostEqual(halted.nav, start.nav)

    def test_target_without_a_close_on_the_apply_session_is_rejected(self):
        with self.assertRaises(ContractError):
            advance(None, trade_date="2026-09-15", prices={}, benchmark=SessionPrice(400.0),
                    target={"AAA": 0.5, "CASH": 0.5}, cost_rates={"AAA": 0.0})

    def test_session_price_collects_actions_since_the_previous_mark(self):
        rows = [
            {"trade_date": "2026-09-15", "close": 100.0, "div_amount": 1.0},
            {"trade_date": "2026-09-16", "close": 25.0, "split_ratio": 4.0},
            {"trade_date": "2026-09-17", "close": 26.0, "div_amount": 0.2},
        ]
        price = session_price(rows, after="2026-09-15", on="2026-09-17")
        self.assertEqual((price.close, price.dividend, price.split_ratio), (26.0, 0.2, 4.0))

    def test_a_target_applies_from_the_first_session_that_opens_after_the_decision(self):
        dates = ["2026-09-14", "2026-09-15"]
        self.assertEqual(first_session_after(datetime(2026, 9, 14, 20, tzinfo=UTC), dates), "2026-09-15")  # 16:00 ET
        self.assertEqual(first_session_after(datetime(2026, 9, 14, 13, tzinfo=UTC), dates), "2026-09-14")  # 09:00 ET

    def test_summary_reports_return_drawdown_and_excess(self):
        rows = [
            {"trade_date": "d1", "nav": 100.0, "benchmark_nav": 100.0, "daily_return": 0.0, "turnover": 0.5, "cost": 0.0,
             "weights": {"CASH": 0.5}},
            {"trade_date": "d2", "nav": 110.0, "benchmark_nav": 102.0, "daily_return": 0.1, "turnover": 0.0, "cost": 0.0,
             "weights": {"CASH": 0.4}},
            {"trade_date": "d3", "nav": 99.0, "benchmark_nav": 101.0, "daily_return": -0.1, "turnover": 0.0, "cost": 0.0,
             "weights": {"CASH": 0.45}},
        ]
        summary = performance_summary(rows)
        self.assertAlmostEqual(summary["total_return"], -0.01)
        self.assertAlmostEqual(summary["max_drawdown"], 0.1)
        self.assertAlmostEqual(summary["excess_return"], -0.02)
        self.assertEqual(summary["cash_weight"], 0.45)


# ---------------------------------------------------------------- engine
SESSIONS = ["2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16",
            "2026-09-17", "2026-09-18", "2026-09-21"]


def _after_close(trade_date: str) -> datetime:
    return datetime.fromisoformat(trade_date).replace(hour=23, tzinfo=UTC)


def _history(closes: dict[str, float], *, drift: float = 0.0) -> list[dict]:
    rows = []
    for offset in range(60, 0, -1):
        day = date(2026, 9, 8) - timedelta(days=offset)
        rows.append({"trade_date": day.isoformat(), "close": 100.0, "volume": 5_000_000})
    price = 100.0
    for trade_date in SESSIONS:
        price *= 1 + drift
        rows.append({"trade_date": trade_date, "close": closes.get(trade_date, price), "volume": 5_000_000})
    return rows


class _Repository:
    """System이 쓰는 읽기·기록 계약만 가진 저장소. 실계좌·승인 메서드가 없다."""

    def __init__(self):
        self.prices = {"SPY": _history({}, drift=0.001), "AAA": _history({}, drift=0.01)}
        self.section = ("2026-09-08T22:00:00+00:00", {"AAA": FactorScore("AAA", {"quality": 0.8}, 0.9, True, None)})
        self.views: dict = {}
        self.saved: list[tuple[str, dict]] = []

    def market_prices(self, ticker, as_of_at, limit=260):
        return [row for row in self.prices.get(ticker, []) if row["trade_date"] <= as_of_at.date().isoformat()][-limit:]

    def factor_cross_section(self, now):
        return self.section

    def thesis_views(self, tickers, *, as_of_at, valid_days):
        return dict(self.views)

    def __getattr__(self, name):
        if name.startswith("save_") or name == "finish_decision_run":
            return lambda *args, **kwargs: self.saved.append((name, dict(kwargs or (args[0] if args else {}))))
        raise AttributeError(name)


def _fake_target(weights: dict[str, float], *, forced_exits=()):
    def build(repository, *, current_weights, as_of_at, run_id, model_artifact_id, **_):
        proposal = PortfolioProposal.create(run_id=run_id, source_type="optimizer", source_version="test", stage="shadow",
                                            as_of_at=as_of_at.isoformat(), weights=weights, confidence=1.0,
                                            reasoning=("test",), model_artifact_id=model_artifact_id)
        risk = RiskDecision(risk_decision_id="risk_" + "a" * 24, proposal_id=proposal.proposal_id, policy_key="portfolio-risk",
                            policy_version=2, policy_hash="0" * 64, input_hash="1" * 64, is_approved=True,
                            approved_weights=weights, violations=(), adjustments=(), decided_at=as_of_at.isoformat())
        build.calls.append(dict(current_weights))
        return type("Target", (), {"proposal": proposal, "risk": risk, "risk_policy": PortfolioRiskPolicy(),
                                   "plan": AlphaPlan((), (), {}, {})})()
    build.calls = []
    return build


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "runtime.sqlite3"
        self.store = SystemPortfolioStore(self.path)
        self.repository = _Repository()
        self.build = _fake_target({"AAA": 0.5, "CASH": 0.5})

    def run_at(self, trade_date: str, *, store=None):
        return run_system(store or self.store, self.repository, now=_after_close(trade_date), build_target=self.build)

    def test_first_target_is_applied_at_the_next_session_close_not_the_decision_close(self):
        decided = self.run_at("2026-09-08")
        self.assertIsNotNone(decided.target_id)
        self.assertEqual(self.store.history(), [])  # 판단일 종가에는 적용하지 않는다
        applied = self.run_at("2026-09-09")
        self.assertEqual(applied.applied_target_id, decided.target_id)
        # 판단일(9/8) 종가가 아니라 다음 정규장(9/9) 종가부터 System에 들어간다.
        self.assertEqual([mark.trade_date for mark in self.store.history()], ["2026-09-09"])
        self.assertEqual(self.store.target(decided.target_id).applied_session, "2026-09-09")
        self.assertEqual(self.build.calls[0], {"CASH": 1.0})

    def test_nav_keeps_marking_between_targets_and_the_next_target_sees_system_weights(self):
        self.run_at("2026-09-08")
        self.run_at("2026-09-09")
        for trade_date in ("2026-09-10", "2026-09-11"):
            result = self.run_at(trade_date)
            self.assertIn(result.skipped_reason, {"factor_snapshot_already_decided", "rebalance_not_due"})
        self.assertEqual([mark.trade_date for mark in self.store.history()], ["2026-09-09", "2026-09-10", "2026-09-11"])
        self.assertGreater(self.store.latest_mark().nav, 99.0)
        self.repository.section = ("2026-09-15T22:00:00+00:00", self.repository.section[1])
        rebalance = self.run_at("2026-09-16")
        self.assertIsNotNone(rebalance.target_id)
        self.assertNotEqual(self.build.calls[-1], {"CASH": 1.0})  # 입력은 System 자신의 drift된 비중이다
        self.assertAlmostEqual(sum(self.build.calls[-1].values()), 1.0)

    def test_new_snapshot_inside_the_rebalance_interval_waits(self):
        self.run_at("2026-09-08")
        self.run_at("2026-09-09")
        self.repository.section = ("2026-09-10T22:00:00+00:00", self.repository.section[1])
        self.assertEqual(self.run_at("2026-09-10").skipped_reason, "rebalance_not_due")

    def test_a_newly_broken_thesis_on_a_holding_does_not_wait_for_the_interval(self):
        self.run_at("2026-09-08")
        self.run_at("2026-09-09")
        self.repository.views = {"AAA": ThesisView("AAA", _after_close("2026-09-10") - timedelta(hours=1), "exit",
                                                   -0.05, 0.2, 0.9)}
        result = self.run_at("2026-09-10")
        self.assertIsNotNone(result.target_id)

    def test_missing_inputs_keep_the_previous_target(self):
        def broken(*args, **kwargs):
            raise ContractError("covariance history is insufficient")
        result = run_system(self.store, self.repository, now=_after_close("2026-09-08"), build_target=broken)
        self.assertEqual(result.skipped_reason, "target_inputs_unavailable")
        self.assertIsNone(self.store.latest_target())
        self.assertIn(("finish_decision_run", {"status": "failed", "failure_reason": "inputs unavailable: covariance history is insufficient"}),
                      self.repository.saved)

    def test_rejections_account_changes_and_manual_orders_do_not_change_the_system(self):
        """사람이 무엇을 골랐든 System 비중·NAV는 같다 — 실행 원장을 채운 원장과 빈 원장을 비교한다."""
        clean = SystemPortfolioStore(Path(self.tmp.name) / "clean.sqlite3")
        noisy_path = Path(self.tmp.name) / "noisy.sqlite3"
        noisy = SystemPortfolioStore(noisy_path)
        now = datetime(2026, 9, 9, tzinfo=UTC).isoformat()
        with runtime_connection(noisy_path) as connection:
            connection.execute("INSERT INTO intents VALUES(?,?,?,?,?,?,?,?,?,?)",
                               ("intent", "proposal", "risk", "live", "failed", now, now, "{}", now, now))
            connection.execute("INSERT INTO approvals VALUES(?,?,?,?,?,?,?,?)",
                               ("approval", "intent", "rejected", "m" * 64, now, "{}", now, now))
            connection.execute("INSERT INTO runtime_records(record_type,record_key,payload_json,created_at,updated_at)"
                               " VALUES('position_snapshot','manual',?,?,?)",
                               (json.dumps({"execution_mode": "live", "ticker": "ZZZ", "quantity": 3, "captured_at": now}),
                                now, now))
        for trade_date in SESSIONS[:6]:
            self.run_at(trade_date, store=clean)
            self.run_at(trade_date, store=noisy)
        self.assertEqual([(m.trade_date, round(m.nav, 12), m.weights) for m in clean.history()],
                         [(m.trade_date, round(m.nav, 12), m.weights) for m in noisy.history()])


class BoundaryTest(unittest.TestCase):
    """System과 ALPHA는 실계좌·승인·주문 코드를 import하지 않는다."""

    GUARDED = (
        "src/investment_agent/trading/system",
        "src/investment_agent/trading/decision/alpha.py",
        "src/investment_agent/trading/decision/analysis.py",
        "src/investment_agent/trading/risk/budget.py",
    )
    FORBIDDEN = (
        "investment_agent.execution.brokers",
        "investment_agent.execution.approval",
        "investment_agent.execution.db",
        "investment_agent.execution.reconciliation",
        "investment_agent.execution.orders.toss_snapshot",
        "investment_agent.notifications",
        "investment_agent.trading.my_portfolio",
    )

    @staticmethod
    def _imports(path: Path) -> list[str]:
        names: list[str] = []
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        return names

    def _files(self) -> list[Path]:
        files: list[Path] = []
        for entry in self.GUARDED:
            target = ROOT / entry
            files.extend(sorted(target.rglob("*.py")) if target.is_dir() else [target])
        return files

    def test_guarded_modules_exist(self):
        """검사 대상이 사라지면 아래 검사는 공허하게 통과한다."""
        files = self._files()
        self.assertTrue(all(path.exists() for path in files))
        self.assertGreaterEqual(len(files), 7)

    def test_system_and_alpha_never_import_account_approval_or_order_code(self):
        offenders = [f"{path.relative_to(ROOT)} -> {name}" for path in self._files() for name in self._imports(path)
                     if name.startswith(self.FORBIDDEN)]
        self.assertEqual([], offenders)

    def test_candidate_and_event_priorities_read_system_holdings(self):
        source = (ROOT / "src/investment_agent/trading/supabase_repository.py").read_text(encoding="utf-8")
        self.assertNotIn("latest_live_position_tickers", source)
        self.assertIn("SystemPortfolioStore().held_tickers()", source)


class SchedulerTest(unittest.TestCase):
    def test_registry_has_one_system_world_and_no_legacy_books(self):
        """옛 가상계좌·진입 감시 runtime이 새 System과 함께 등록되지 않는다."""
        from types import SimpleNamespace
        from investment_agent.operations.commands.investment_harness import build_registry

        handler = lambda context: None  # noqa: E731
        names = ("analysis", "select_target", "follow", "execution_intent", "approval_request", "approval_worker",
                 "risk_snapshot", "reconcile", "watch", "build_valuations", "build_features", "build_labels",
                 "build_training_samples", "build_events", "evaluate_decisions", "notify_investment", "notify_trades",
                 "run_system_portfolio")
        registry = build_registry(adapters=SimpleNamespace(**{name: handler for name in names}))
        job_ids = {definition.job_id for definition in registry.definitions()}
        self.assertIn("system_portfolio", job_ids)
        self.assertIn("my_portfolio_follow", job_ids)
        self.assertFalse(job_ids & {"virtual_books", "entry_watch", "investment_pipeline"})
        stages = {stage.stage_id for definition in registry.definitions() for stage in definition.stages}
        self.assertFalse(stages & {"run_books", "select_signal", "portfolio"})


# ---------------------------------------------------------------- 실제 optimizer·RiskGate
class BuildSystemTargetTest(unittest.TestCase):
    """실제 optimizer·RiskGate로 끝까지: 검증된 상위 종목만 사고, 논지가 깨진 보유는 팔고, 한도를 지킨다."""

    def test_end_to_end_without_any_account_snapshot(self):
        from investment_agent.trading.system.target import SystemPortfolioPolicy, build_system_target

        rng = random.Random(7)
        from investment_agent.trading.risk.stress import STRESS_PROXIES

        names = sorted({"AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "SPY", *STRESS_PROXIES})
        history: dict[str, list[dict]] = {}
        market = [0.0005 + rng.gauss(0, 0.01) for _ in range(300)]
        for name in names:
            price, rows = 100.0, []
            for offset in range(300):
                price *= 1 + 0.9 * market[offset] + rng.gauss(0, 0.012)
                day = date(2025, 7, 1) + timedelta(days=offset)
                rows.append({"trade_date": day.isoformat(), "open": price, "close": price, "volume": 5_000_000})
            history[name] = rows
        now = datetime.combine(date(2025, 7, 1) + timedelta(days=299), datetime.min.time(), tzinfo=UTC) + timedelta(hours=23)

        class Repository:
            def market_prices(self, ticker, as_of_at, limit=260):
                return history.get(ticker, [])[-limit:]

            def sp500_sector_map(self, tickers):
                return {ticker: ("tech" if ticker in {"AAA", "BBB", "CCC"} else "energy") for ticker in tickers}

            def current_tracked_tickers(self):
                return ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]

            def macro_histories(self, series_ids, *, as_of_at, lookback_days=120):
                return {}

        views = {
            "AAA": ThesisView("AAA", now - timedelta(days=2), "open", 0.03, 0.65, 0.8),
            "BBB": ThesisView("BBB", now - timedelta(days=2), "open", 0.02, 0.6, 0.8),
            "FFF": ThesisView("FFF", now - timedelta(days=2), "exit", -0.05, 0.3, 0.8),
        }
        scores = {ticker: FactorScore(ticker, {"quality": 0.8}, value, True, None)
                  for ticker, value in dict(AAA=0.95, BBB=0.9, CCC=0.85, DDD=0.3, EEE=0.2, FFF=0.8).items()}
        target = build_system_target(
            Repository(), current_weights={"FFF": 0.1, "CASH": 0.9}, as_of_at=now, scores=scores,
            snapshot_as_of="S1", run_id="run_1", model_artifact_id=None, views=views,
            policy=SystemPortfolioPolicy(),
        )
        weights = target.risk.approved_weights
        self.assertTrue(target.risk.is_approved, target.risk.violations)
        self.assertEqual(target.plan.reasons["FFF"], "THESIS_BROKEN")
        self.assertAlmostEqual(weights.get("FFF", 0.0), 0.0)            # 논지가 깨진 보유는 청산
        self.assertAlmostEqual(weights.get("CCC", 0.0), 0.0)            # 검증 안 된 신규는 못 산다
        self.assertGreater(weights.get("AAA", 0.0), 0.0)                # 검증된 상위 종목은 산다
        self.assertTrue(all(weight <= 0.10 + 1e-6 for symbol, weight in weights.items() if symbol != "CASH"))
        self.assertTrue(math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9))
        self.assertEqual(target.proposal.metadata["forced_exits"], ["FFF"])
        self.assertEqual(target.proposal.metadata["trade_reasons"]["FFF"]["code"], "THESIS_EXIT")

    def test_target_signature_has_no_account_input(self):
        import inspect
        from investment_agent.trading.system.target import build_system_target

        parameters = set(inspect.signature(build_system_target).parameters)
        self.assertFalse(parameters & {"snapshot", "account", "account_snapshot", "expected_account_id"})


if __name__ == "__main__":
    unittest.main()
