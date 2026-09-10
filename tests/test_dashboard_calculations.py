"""대시보드 읽기 전용 계산의 결측 보존과 핵심 수식을 검증한다."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from investment_agent.dashboard.calculations import (
    add_technical_indicators,
    build_strategy_returns,
    covariance_to_correlation,
    diagnose_macro,
    finite_number,
    fear_greed_scale,
    free_cash_flow,
    guru_position_changes,
    historical_surprise_series,
    inspect_harness_state,
    macro_latest,
    macro_regime,
    monthly_close_from_daily,
    monte_carlo_fan,
    monthly_returns_matrix,
    normalize_role_analyses,
    parse_date_safe,
    parse_datetime_safe,
    performance_metrics,
    rebalance_portfolio,
    sec_gaap_diluted_eps,
)


class SafeParsingTests(unittest.TestCase):
    """숫자·날짜 입력이 추측 없이 정규화되는지 확인한다."""

    def test_finite_number_rejects_missing_nonfinite_and_boolean(self) -> None:
        """결측·무한대·불리언은 숫자 0으로 바뀌지 않아야 한다."""
        for value in (None, True, False, np.nan, np.inf, -np.inf, "not-a-number"):
            with self.subTest(value=value):
                self.assertIsNone(finite_number(value))
        self.assertEqual(finite_number("0"), 0.0)

    def test_covariance_to_correlation_validates_shape_and_variance(self) -> None:
        correlation = covariance_to_correlation([[4.0, 1.0], [1.0, 9.0]])
        self.assertIsNotNone(correlation)
        self.assertAlmostEqual((correlation or [])[0][1], 1.0 / 6.0)
        self.assertIsNone(covariance_to_correlation([[1.0], [1.0, 1.0]]))
        self.assertIsNone(covariance_to_correlation([[0.0, 0.0], [0.0, 1.0]]))

    def test_date_parsers_reject_invalid_values(self) -> None:
        """잘못된 날짜는 현재 시각 같은 대체값 없이 None이어야 한다."""
        self.assertIsNone(parse_datetime_safe(None))
        self.assertIsNone(parse_datetime_safe(0))
        self.assertIsNone(parse_datetime_safe(pd.NaT))
        self.assertIsNone(parse_datetime_safe("2026-99-99"))
        parsed = parse_datetime_safe("2026-08-22T12:30:00+09:00")
        self.assertEqual(parsed, datetime(2026, 8, 22, 3, 30, tzinfo=timezone.utc))
        self.assertEqual(parse_date_safe("2026-08-22"), parsed.date())


class TechnicalAndMacroTests(unittest.TestCase):
    """기술지표와 매크로 진단의 실제 관측치 의존성을 검증한다."""

    def test_technical_indicators_use_existing_wilder_calculation(self) -> None:
        """충분한 상승 가격에서는 이동평균과 Wilder RSI가 계산되어야 한다."""
        frame = pd.DataFrame({"Close": np.arange(1.0, 71.0)})
        result = add_technical_indicators(frame)
        self.assertAlmostEqual(result["SMA20"].iloc[-1], 60.5)
        self.assertAlmostEqual(result["SMA60"].iloc[-1], 40.5)
        self.assertAlmostEqual(result["RSI14"].iloc[-1], 100.0)
        self.assertNotIn("SMA20", frame.columns)

    def test_missing_close_remains_nan(self) -> None:
        """종가 컬럼이 없으면 기술지표를 0이나 임의 숫자로 채우지 않아야 한다."""
        result = add_technical_indicators(pd.DataFrame({"Open": [10.0, 11.0]}))
        self.assertTrue(result[["SMA20", "SMA60", "RSI14"]].isna().all().all())

    def test_monthly_close_from_daily_excludes_incomplete_month(self) -> None:
        """저장 일봉을 월말 종가로 만들 때 진행 중인 달을 미래값처럼 쓰지 않는다."""
        prices = pd.DataFrame(
            {
                ("Close", "SPY"): [100.0, 101.0, 102.0],
                ("Close", "QQQ"): [200.0, 201.0, 202.0],
            },
            index=pd.to_datetime(["2026-07-31", "2026-08-31", "2026-09-05"]),
        )
        result = monthly_close_from_daily(prices, as_of=datetime(2026, 9, 6))
        self.assertEqual([value.strftime("%Y-%m") for value in result.index], ["2026-07", "2026-08"])
        self.assertEqual(result.loc["2026-08-31", "SPY"], 101.0)

    def test_macro_latest_and_diagnosis_include_counter_signal(self) -> None:
        """매크로 진단은 우세 근거와 실제 반대 신호를 동시에 보존해야 한다."""
        rows = [
            {"series_id": "VIX", "obs_date": "2026-08-20", "value": 20},
            {"series_id": "VIX", "obs_date": "2026-08-21", "value": 30},
            {"series_id": "FEAR_GREED", "obs_date": "2026-08-21", "value": 30},
            {"series_id": "DXY", "obs_date": "2026-08-20", "value": 99},
            {"series_id": "DXY", "obs_date": "2026-08-21", "value": 101},
            {"series_id": "TNX", "obs_date": "2026-08-20", "value": 4.3},
            {"series_id": "TNX", "obs_date": "2026-08-21", "value": 4.1},
            {"series_id": "BROKEN", "obs_date": None, "value": None},
        ]
        latest = macro_latest(rows)
        self.assertEqual(latest["VIX"]["current_value"], 30.0)
        self.assertEqual(latest["VIX"]["previous_value"], 20.0)
        self.assertEqual(latest["VIX"]["change_pct"], 0.5)
        self.assertNotIn("BROKEN", latest)

        diagnosis = diagnose_macro(latest)
        self.assertEqual(diagnosis["status"], "risk_off")
        self.assertEqual({row["series_id"] for row in diagnosis["evidence"]}, {"VIX", "FEAR_GREED", "DXY"})
        self.assertEqual({row["series_id"] for row in diagnosis["counter_signals"]}, {"TNX"})

    def test_macro_diagnosis_is_unknown_when_evidence_is_insufficient(self) -> None:
        """필수 관측치가 부족할 때 진단을 중립이나 risk-on으로 꾸미지 않아야 한다."""
        result = diagnose_macro({"VIX": {"current_value": 18.0, "previous_value": None}})
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["score"])
        self.assertEqual(result["evidence"], ())

    def test_macro_regime_always_returns_a_renderable_summary(self) -> None:
        """지표가 없거나 신호가 비등해도 화면 계약을 빠뜨리지 않아야 한다."""
        empty = macro_regime([])
        self.assertEqual(empty["verdict"], "판단 불가")
        self.assertEqual(empty["tone"], "flat")
        self.assertEqual(empty["evaluated"], 0)
        self.assertEqual(empty["supporting"], ())
        self.assertEqual(empty["opposing"], ())

        tied = macro_regime([
            {"series_id": "VIX", "curr": 10.0},
            {"series_id": "SPREAD_10Y2Y", "curr": -1.0},
        ])
        self.assertEqual(tied["verdict"], "중립")
        self.assertEqual(tied["tone"], "flat")
        self.assertEqual(tied["evaluated"], 2)

    def test_fear_greed_scale_explains_value_and_range(self) -> None:
        """공포·탐욕 값은 진행률뿐 아니라 사용자가 읽을 구간을 제공해야 한다."""
        result = fear_greed_scale(40.5)

        self.assertEqual(result["label"], "공포")
        self.assertEqual(result["range_label"], "25–44")
        self.assertAlmostEqual(result["normalized"], 0.405)
        self.assertEqual(result["tone"], "orange")

    def test_fear_greed_scale_clamps_out_of_range_values(self) -> None:
        """외부 값이 범위를 벗어나도 막대가 깨지지 않고 끝점에 고정되어야 한다."""
        low = fear_greed_scale(-5)
        high = fear_greed_scale(120)

        self.assertEqual(low["normalized"], 0.0)
        self.assertEqual(low["label"], "극단적 공포")
        self.assertEqual(high["normalized"], 1.0)
        self.assertEqual(high["label"], "극단적 탐욕")

    def test_fear_greed_scale_preserves_missing_value(self) -> None:
        """결측 심리 지표는 가짜 중립값으로 바꾸지 않아야 한다."""
        self.assertIsNone(fear_greed_scale(None))


class EarningsAndGuruTests(unittest.TestCase):
    """어닝 수식과 13F 비교가 완전한 입력에서만 작동하는지 검증한다."""

    def test_earnings_calculations_require_all_components(self) -> None:
        """FCF·SEC EPS·surprise는 필요한 구성요소 누락 시 None이어야 한다."""
        self.assertEqual(
            free_cash_flow({"net_cash_from_operating_activities": 100, "capital_expenses": 25}),
            75.0,
        )
        self.assertIsNone(free_cash_flow({"net_cash_from_operating_activities": 100}))
        self.assertEqual(
            sec_gaap_diluted_eps({"net_income_to_common_shareholders": 100, "shares_fully_diluted_average": 50}),
            2.0,
        )
        self.assertIsNone(sec_gaap_diluted_eps({"net_income_to_common_shareholders": 100}))
        self.assertIsNone(sec_gaap_diluted_eps({
            "net_income_to_common_shareholders": 100,
            "shares_fully_diluted_average": 0,
        }))

    def test_historical_surprise_series_computes_streaks_and_surprises(self) -> None:
        """과거 분기별 실적과 사전 컨센서스를 매칭하여 서프라이즈 % 및 연속 비트 streak을 계산해야 한다."""
        core_rows = [
            {
                "ticker": "AAPL",
                "fiscal_year": 2024,
                "fiscal_period": "Q1",
                "period_end": "2023-12-31",
                "filed_at": "2024-02-01",
                "revenue": 120.0,
                "eps_diluted_gaap": 2.2,
            },
            {
                "ticker": "AAPL",
                "fiscal_year": 2024,
                "fiscal_period": "Q2",
                "period_end": "2024-03-31",
                "filed_at": "2024-05-02",
                "revenue": 95.0,
                "eps_diluted_gaap": 1.5,
            },
        ]
        consensus_rows = [
            {
                "ticker": "AAPL",
                "target_fiscal_year": "2024",
                "target_fiscal_period": "Q1",
                "snapshot_date": "2024-01-25",
                "revenue_avg": 100.0,
                "eps_avg": 2.0,
            },
            {
                "ticker": "AAPL",
                "target_fiscal_year": "2024",
                "target_fiscal_period": "Q2",
                "snapshot_date": "2024-04-25",
                "revenue_avg": 100.0,
                "eps_avg": 1.6,
            },
        ]
        result = historical_surprise_series(core_rows, consensus_rows)
        self.assertEqual(len(result), 2)
        # 내림차순 정렬이므로 Q2가 첫 번째
        q2 = result[0]
        self.assertEqual(q2["fiscal_period"], "Q2")
        self.assertEqual(q2["revenue_status"], "miss")
        self.assertEqual(q2["eps_status"], "miss")
        self.assertEqual(q2["consecutive_revenue_beats"], 0)
        self.assertEqual(q2["consecutive_eps_beats"], 0)
        self.assertAlmostEqual(q2["revenue_surprise_pct"], -0.05)

        q1 = result[1]
        self.assertEqual(q1["fiscal_period"], "Q1")
        self.assertEqual(q1["revenue_status"], "beat")
        self.assertEqual(q1["eps_status"], "beat")
        self.assertEqual(q1["consecutive_revenue_beats"], 1)
        self.assertEqual(q1["consecutive_eps_beats"], 1)
        self.assertAlmostEqual(q1["revenue_surprise_pct"], 0.2)

    @staticmethod
    def _position(cusip: str, quantity: float, accession_no: str) -> dict[str, object]:
        """비교 테스트용 실제 long-equity 형태의 최소 행을 만든다."""
        return {
            "accession_no": accession_no,
            "cusip": cusip,
            "issuer_name": f"Issuer {cusip}",
            "position_kind": "SHARES",
            "quantity_type": "SH",
            "quantity": quantity,
        }

    def test_guru_changes_apply_ten_percent_threshold(self) -> None:
        """신규·10% 이상 증감·청산만 표시하고 미세 변화는 제외해야 한다."""
        previous = [
            self._position("A", 100, "old"),
            self._position("B", 100, "old"),
            self._position("D", 50, "old"),
            self._position("E", 100, "old"),
        ]
        current = [
            self._position("A", 111, "new"),
            self._position("B", 89, "new"),
            self._position("C", 50, "new"),
            self._position("E", 105, "new"),
        ]
        result = guru_position_changes(current, previous, {key: key for key in "ABCDE"})
        by_ticker = {row["ticker"]: row for row in result}
        self.assertEqual({ticker: row["change"] for ticker, row in by_ticker.items()}, {
            "A": "increase",
            "B": "decrease",
            "C": "new",
            "D": "exit",
        })
        self.assertIsNone(by_ticker["C"]["previous_quantity"])
        self.assertIsNone(by_ticker["D"]["current_quantity"])
        self.assertNotIn("E", by_ticker)

    def test_guru_changes_require_both_comparable_filings(self) -> None:
        """직전 공시가 없을 때 현재 보유 전체를 신규 편입으로 위조하지 않아야 한다."""
        current = [self._position("A", 100, "new")]
        self.assertEqual(guru_position_changes(current, [], {"A": "A"}), [])


class StrategyTests(unittest.TestCase):
    """전략 수익률·성과·시뮬레이션이 실제 가격에만 의존하는지 검증한다."""

    @staticmethod
    def _strategy_inputs() -> tuple[list[dict[str, object]], pd.DataFrame]:
        """두 적용 구간과 각각 10% 수익인 가격 이력을 반환한다."""
        allocations = [
            {"strategy_id": "GEM", "apply_date": "2026-01-01", "weights": {"A": 1.0}},
            {"strategy_id": "GEM", "apply_date": "2026-02-01", "weights": {"B": 1.0}},
        ]
        prices = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-31", "2026-02-01", "2026-02-28"],
            "A": [100.0, 110.0, 110.0, 110.0],
            "B": [100.0, 100.0, 100.0, 110.0],
        })
        return allocations, prices

    def test_strategy_returns_use_each_actual_allocation_period(self) -> None:
        """적용일별 실제 배분과 실제 가격으로 구간 수익률을 계산해야 한다."""
        allocations, prices = self._strategy_inputs()
        result = build_strategy_returns(allocations, prices)
        self.assertEqual(list(result.columns), ["GEM"])
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result["GEM"].iloc[0], 0.1)
        self.assertAlmostEqual(result["GEM"].iloc[1], 0.1)

    def test_strategy_returns_skip_missing_price_period(self) -> None:
        """가격이 없는 자산 구간은 0% 수익으로 대체하지 않고 제외해야 한다."""
        allocations, prices = self._strategy_inputs()
        result = build_strategy_returns(allocations, prices.drop(columns=["B"]))
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result["GEM"].iloc[0], 0.1)

    def test_strategy_returns_accept_external_ticker_frame_mapping(self) -> None:
        """yfinance 조회 계약인 종목별 OHLC DataFrame 매핑을 직접 사용할 수 있어야 한다."""
        allocations, prices = self._strategy_inputs()
        dates = pd.to_datetime(prices["date"])
        payload = {
            "A": pd.DataFrame({"Close": prices["A"].to_numpy()}, index=dates),
            "B": pd.DataFrame({"Close": prices["B"].to_numpy()}, index=dates),
        }
        result = build_strategy_returns(allocations, payload)
        self.assertEqual(len(result), 2)
        self.assertIsNone(result.index.tz)
        self.assertAlmostEqual(result["GEM"].iloc[0], 0.1)
        self.assertAlmostEqual(result["GEM"].iloc[1], 0.1)

    def test_performance_metrics_preserve_no_data(self) -> None:
        """수익률이 없으면 모든 성과 숫자는 None이고 누적 시계열은 비어야 한다."""
        result = performance_metrics([None, np.nan, np.inf])
        self.assertEqual(result["observations"], 0)
        self.assertTrue(result["cumulative_returns"].empty)
        for key in ("total_return", "cagr", "max_drawdown", "annualized_volatility"):
            self.assertIsNone(result[key])

    def test_performance_metrics_calculate_drawdown(self) -> None:
        """유효 수익률에서는 누적수익과 최대낙폭을 메모리에서 계산해야 한다."""
        result = performance_metrics([0.1, -0.1], periods_per_year=2)
        self.assertEqual(result["observations"], 2)
        self.assertAlmostEqual(result["total_return"], -0.01)
        self.assertAlmostEqual(result["max_drawdown"], -0.1)

    def test_monte_carlo_requires_history_and_is_deterministic(self) -> None:
        """관측치 부족 시 fan을 만들지 않고 같은 seed는 같은 결과를 내야 한다."""
        self.assertTrue(monte_carlo_fan([0.01] * 11).empty)
        first = monte_carlo_fan([0.01, -0.01] * 6, horizon_periods=4, simulations=100, seed=7)
        second = monte_carlo_fan([0.01, -0.01] * 6, horizon_periods=4, simulations=100, seed=7)
        pd.testing.assert_frame_equal(first, second)
        self.assertEqual(list(first.columns), ["p10", "p25", "p50", "p75", "p90"])
        self.assertTrue((first.iloc[0] == 1.0).all())

    def test_monthly_returns_matrix_builds_year_month_pivot_and_ytd(self) -> None:
        """월별 수익률 Series/DataFrame을 연도 x 월 매트릭스 및 YTD 복리로 변환해야 한다."""
        dates = pd.date_range("2024-01-31", periods=3, freq="ME")
        series = pd.Series([0.05, -0.02, 0.03], index=dates)
        matrix = monthly_returns_matrix(series)
        self.assertFalse(matrix.empty)
        self.assertIn(2024, matrix.index)
        self.assertEqual(list(matrix.columns), [f"{m}월" for m in range(1, 13)] + ["YTD"])
        self.assertAlmostEqual(matrix.loc[2024, "1월"], 0.05)
        self.assertAlmostEqual(matrix.loc[2024, "2월"], -0.02)
        self.assertAlmostEqual(matrix.loc[2024, "3월"], 0.03)
        self.assertTrue(pd.isna(matrix.loc[2024, "4월"]))
        expected_ytd = (1.05 * 0.98 * 1.03) - 1.0
        self.assertAlmostEqual(matrix.loc[2024, "YTD"], expected_ytd)

        # 빈 데이터 전달 시 빈 DataFrame 반환
        self.assertTrue(monthly_returns_matrix(None).empty)
        self.assertTrue(monthly_returns_matrix(pd.Series(dtype="float64")).empty)


class PortfolioAndRoleTests(unittest.TestCase):
    """리밸런싱과 역할 분석이 주문·가짜 역할을 만들지 않는지 검증한다."""

    def test_rebalance_returns_guidance_without_order_artifacts(self) -> None:
        """완전한 조회 데이터에서는 금액·수량 가이드만 계산해야 한다."""
        result = rebalance_portfolio(
            holdings=[{"ticker": "AAPL", "quantity": 10}],
            cash=100,
            target_weights={"AAPL": 0.75, "CASH": 0.25},
            prices={"AAPL": 10},
        )
        self.assertTrue(result["available"])
        self.assertTrue(result["complete"])
        self.assertEqual(result["total_value"], 200.0)
        aapl = next(row for row in result["rows"] if row["ticker"] == "AAPL")
        self.assertEqual(aapl["adjustment_value"], 50.0)
        self.assertEqual(aapl["guide_quantity_delta"], 5.0)
        self.assertEqual(aapl["price"], 10.0)
        self.assertEqual(aapl["quantity"], 10.0)
        self.assertEqual(aapl["guide_quantity"], 5.0)
        forbidden_fragments = ("order", "side", "approval", "execution")
        self.assertFalse(any(
            fragment in key.lower()
            for row in result["rows"]
            for key in row
            for fragment in forbidden_fragments
        ))

    def test_rebalance_missing_values_are_not_zero_filled(self) -> None:
        """현금·가격이 없으면 0원 계좌나 0주 가이드를 만들어서는 안 된다."""
        missing_cash = rebalance_portfolio(
            holdings=[{"ticker": "AAPL", "quantity": 10}],
            cash=None,
            target_weights={"AAPL": 0.75, "CASH": 0.25},
            prices={"AAPL": 10},
        )
        self.assertFalse(missing_cash["available"])
        self.assertIsNone(missing_cash["total_value"])
        self.assertEqual(missing_cash["rows"], [])

        missing_target_price = rebalance_portfolio(
            holdings=[],
            cash=100,
            target_weights={"MSFT": 0.5, "CASH": 0.5},
            prices={},
        )
        self.assertTrue(missing_target_price["available"])
        self.assertFalse(missing_target_price["complete"])
        self.assertEqual(missing_target_price["missing_prices"], ("MSFT",))
        msft = next(row for row in missing_target_price["rows"] if row["ticker"] == "MSFT")
        self.assertIsNone(msft["guide_quantity_delta"])

    def test_normalize_roles_never_invents_missing_roles(self) -> None:
        """저장된 분석에 없는 Bear·Risk 역할을 placeholder로 추가하지 않아야 한다."""
        listed = normalize_role_analyses([{"role": "bull", "summary": "실제 저장 분석"}])
        self.assertEqual([row["role"] for row in listed], ["bull"])
        state = normalize_role_analyses({
            "market_report": "실제 시장 보고서",
            "investment_debate_state": {"bull_history": "실제 bull", "bear_history": ""},
            "risk_debate_state": {},
        })
        self.assertEqual({row["role"] for row in state}, {"market_analyst", "bull"})
        self.assertEqual(normalize_role_analyses({}), [])


class HarnessTests(unittest.TestCase):
    """하네스 상태 파일의 읽기 전용 건강 판정을 검증한다."""

    def setUp(self) -> None:
        """시간 의존성을 없애기 위해 고정된 UTC 현재 시각을 사용한다."""
        self.now = datetime(2026, 8, 22, 3, 0, tzinfo=timezone.utc)
        self.state = {
            "process_id": 1234,
            "process_started_at": "2026-08-22T02:00:00Z",
            "process_heartbeat_at": "2026-08-22T02:59:30Z",
            "stopped_cleanly": False,
            "recovery_count": 1,
            "jobs": {
                "macro": {
                    "job_id": "macro",
                    "status": "running",
                    "stage": "load",
                    "heartbeat_at": "2026-08-22T02:59:00Z",
                    "stages": {"load": {"status": "running"}},
                },
            },
        }

    def test_live_pid_and_fresh_heartbeats_are_healthy(self) -> None:
        """살아 있는 PID와 최신 heartbeat는 정상 상태로 요약되어야 한다."""
        result = inspect_harness_state(self.state, pid_exists=lambda pid: pid == 1234, now=self.now)
        self.assertEqual(result["process_status"], "running")
        self.assertTrue(result["healthy"])
        self.assertEqual(result["heartbeat_age_seconds"], 30.0)
        self.assertEqual(result["jobs"][0]["current_stage_state"], {"status": "running"})

    def test_dead_pid_and_stale_job_are_reported(self) -> None:
        """죽은 PID나 오래된 잡을 정상으로 간주하지 않아야 한다."""
        dead = inspect_harness_state(self.state, pid_exists=lambda _pid: False, now=self.now)
        self.assertEqual(dead["process_status"], "pid_not_alive")
        self.assertFalse(dead["healthy"])

        stale_state = dict(self.state)
        stale_state["jobs"] = {
            "macro": {
                **self.state["jobs"]["macro"],
                "heartbeat_at": "2026-08-22T02:00:00Z",
            },
        }
        stale = inspect_harness_state(stale_state, pid_exists=lambda _pid: True, now=self.now)
        self.assertEqual(stale["stale_jobs"], ("macro",))
        self.assertFalse(stale["healthy"])

    def test_missing_state_has_no_synthetic_process_values(self) -> None:
        """상태 파일이 없으면 PID·시각·kill switch를 임의 생성하지 않아야 한다."""
        result = inspect_harness_state(None, now=self.now)
        self.assertFalse(result["available"])
        self.assertEqual(result["process_status"], "state_missing")
        self.assertIsNone(result["process_id"])
        self.assertIsNone(result["heartbeat_age_seconds"])
        self.assertIsNone(result["kill_switch_active"])

        incomplete = inspect_harness_state({}, now=self.now)
        self.assertIsNone(incomplete["stopped_cleanly"])
        self.assertIsNone(incomplete["recovery_count"])


if __name__ == "__main__":
    unittest.main()
