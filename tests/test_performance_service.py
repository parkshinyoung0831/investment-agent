"""실행 owner 입력부터 지속 보고서·embed까지 네트워크 없는 검증."""
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from investment_agent.trading.performance.repository import PerformanceRepository
from investment_agent.trading.performance.service import update_performance
from investment_agent.notifications.investment.run_performance import notices, render
from tests.test_performance_ledger import fill


class Source:
    def performance_sources(self):
        return dict(fills=[dict(fill("b", "buy", 2, 100, 1), broker_account_hash="account", execution_mode="live"),
                           dict(fill("s", "sell", 1, 120, 2), broker_account_hash="account", execution_mode="live")],
                    orders=[], intents=[], position_snapshots=[],
                    account_snapshots=[dict(broker_account_hash="account", execution_mode="live", currency="USD",
                        captured_at="2026-09-02T20:00:00+00:00", equity=1040, positions=[dict(ticker="AAPL", quantity=1, market_price=120)])])


class PerformanceServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = PerformanceRepository(Path(self.temp.name) / "runtime.db")

    def test_source_report_is_durable_and_retry_idempotent(self):
        first = update_performance(source=Source(), repository=self.repo)
        second = update_performance(source=Source(), repository=self.repo)
        self.assertEqual(first["created"], 2)
        self.assertEqual(second["created"], 0)
        self.assertEqual(len(self.repo.reports()), 2)
        daily = self.repo.latest_performance()
        self.assertEqual(daily["accounting"]["realized_pnl"], 20)
        self.assertIsNone(daily["nav"]["cumulative_return"])
        self.assertIn("cashflow_history_incomplete", daily["quality_issues"])

    def test_unattributed_fill_is_reported_not_mixed_into_account(self):
        source = Source()
        data = source.performance_sources()
        data["fills"].append(fill("bad", "buy", 2, 99, 1))
        source.performance_sources = lambda: data
        result = update_performance(source=source, repository=self.repo)
        self.assertEqual(result["unattributed_fills"], 1)
        self.assertIn("unattributed_fills", self.repo.latest_performance()["quality_issues"])

    def test_event_identity_conflict_is_rejected(self):
        event = dict(event_id="e", kind="deposit", broker_account_hash="account", execution_mode="live",
                     occurred_at="2026-09-01T00:00:00+00:00", amount=10, currency="USD", source_ref="statement:1")
        self.assertTrue(self.repo.save_event(event))
        self.assertFalse(self.repo.save_event(event))
        with self.assertRaises(ValueError):
            self.repo.save_event(dict(event, amount=20))

    def test_unknown_fill_currency_keeps_report_with_missing_quality(self):
        source = Source()
        data = source.performance_sources()
        data["fills"][0].pop("currency")
        source.performance_sources = lambda: data
        update_performance(source=source, repository=self.repo)
        daily = self.repo.latest_performance()
        self.assertIsNone(daily["accounting"]["realized_pnl"])
        self.assertIn("fill_identity_or_currency_unknown", daily["quality_issues"])

    def test_daily_report_does_not_use_fill_after_snapshot_for_unrealized(self):
        source = Source()
        data = source.performance_sources()
        data["fills"].append(dict(fill("late", "buy", 1, 130, 3), broker_account_hash="account", execution_mode="live"))
        source.performance_sources = lambda: data
        update_performance(source=source, repository=self.repo)
        self.assertIsNone(self.repo.latest_performance()["accounting"]["unrealized_pnl"])

    def test_read_empty_report_store_does_not_create_database(self):
        self.assertIsNone(self.repo.latest_performance())
        self.assertFalse(Path(self.repo.path).exists())

    def test_cli_as_of_is_passed_to_source_and_service(self):
        from investment_agent.operations.commands.update_performance import main
        with patch("investment_agent.operations.commands.update_performance.ResearchStore") as research, patch(
            "investment_agent.operations.commands.update_performance.ExecutionRepository"), patch(
            "investment_agent.operations.commands.update_performance.update_performance", return_value={}) as service:
            self.assertEqual(main(["--as-of", "2026-09-02T20:00:00+00:00"]), 0)
            self.assertEqual(service.call_args.kwargs["as_of_at"].isoformat(), "2026-09-02T20:00:00+00:00")

    def test_cumulative_broker_snapshots_make_delta_lots_and_fee_correction(self):
        from investment_agent.trading.performance.service import observed_fills
        data = dict(fills=[], broker_order_snapshots=[
            dict(client_order_id="b", snapshot_hash="b1", filled_quantity=1, average_fill_price=100, commission=None, tax=None, observed_at="2026-09-01T00:00:00+00:00"),
            dict(client_order_id="b", snapshot_hash="b2", filled_quantity=2, average_fill_price=105, commission=2, tax=0, observed_at="2026-09-02T00:00:00+00:00"),
            dict(client_order_id="b", snapshot_hash="b3", filled_quantity=2, average_fill_price=105, commission=4, tax=0, observed_at="2026-09-03T00:00:00+00:00")])
        rows = observed_fills(data)
        self.assertEqual([r["price"] for r in rows], [100, 110])
        self.assertEqual(sum(r["commission"] for r in rows), 4)
        data["fills"] = [dict(fill("actual", "buy", 2, 105, 1), client_order_id="b")]
        merged = observed_fills(data)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['fill_id'], 'actual')
        self.assertEqual(merged[0]['commission'], 4)
        data['fills'][0]['quantity'] = 1
        data['fills'][0]['price'] = 100
        merged = observed_fills(data)
        self.assertEqual(sum(row['quantity'] for row in merged), 2)
        self.assertEqual(sum(row['commission'] for row in merged), 4)
        self.assertEqual(merged[1]['price'], 110)
        self.assertEqual(merged[0]['filled_at'], data['fills'][0]['filled_at'])

    def test_render_unknown_pnl_and_modes_have_explicit_labels(self):
        source = Source()
        data = source.performance_sources()
        data["fills"] = data["fills"][1:]
        source.performance_sources = lambda: data
        update_performance(source=source, repository=self.repo)
        rendered = render(notices([self.repo.latest_performance()]))
        self.assertIn("미확인", str(rendered))
        self.assertIn("실계좌", str(rendered))

    def test_original_decision_report_exists_without_any_account(self):
        from unittest.mock import patch
        from investment_agent.reporting.notifications.investment.performance import performance_reports
        with patch('investment_agent.reporting.notifications.investment.performance.PerformanceRepository') as owner, patch('investment_agent.research.storage.repository.ResearchStore') as research:
            owner.return_value.reports.return_value = []
            research.return_value.decision_experience_rows.return_value = [dict(available_at='2026-01-01T00:00:00+00:00', horizon_days=5, net_reward=.03)]
            reports = performance_reports()
        self.assertEqual(reports[0]['report_kind'], 'recommendation')
        self.assertFalse(reports[0]['recommendation']['is_account_return'])
        self.assertIn('실제 매수 여부와 무관', str(render(notices(reports))))


if __name__ == "__main__":
    unittest.main()
