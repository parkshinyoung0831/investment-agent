"""목표 비중 시간열을 다음 거래일 시가에 재생하는 엔진."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from investment_agent.research.backtest.contracts import (
    BacktestRequest,
    BacktestResult,
    BacktestSafetyError,
    MarketBar,
    WeightPoint,
    stable_hash,
)
from investment_agent.research.evaluation.costs import TransactionCostModel
from investment_agent.research.backtest.metrics import calculate_metrics
from investment_agent.research.backtest.simulator import SimulatedBroker
from investment_agent.trading.contracts import parse_datetime

ENGINE_VERSION = "weight-backtest-v1"


class WeightBacktestEngine:
    """시장 이벤트를 순서대로 적용해 동일 입력에 동일 장부를 만든다."""

    def __init__(self, costs: TransactionCostModel | None = None) -> None:
        self.costs = costs or TransactionCostModel()

    @staticmethod
    def _validate_timing(points: tuple[WeightPoint, ...], sessions: tuple[str, ...]) -> None:
        session_dates = [date.fromisoformat(item) for item in sessions]
        for point in points:
            decision_date = parse_datetime(point.decided_at).date()
            next_sessions = [item for item in session_dates if item > decision_date]
            if not next_sessions:
                raise BacktestSafetyError(
                    f"no t+1 session exists after decision {point.point_id}"
                )
            expected = next_sessions[0].isoformat()
            if point.effective_date != expected:
                raise BacktestSafetyError(
                    f"{point.point_id} must become effective on t+1 session {expected}, "
                    f"got {point.effective_date}"
                )

    @staticmethod
    def _eligible_symbols(
        request: BacktestRequest,
        session_date: str,
    ) -> set[str]:
        snapshots = request.universe_snapshots
        if request.config.cohort_mode == "current_cohort":
            return set(snapshots[0].symbols)
        eligible = [item for item in snapshots if item.effective_date <= session_date]
        if not eligible:
            raise BacktestSafetyError(
                f"missing point-in-time universe snapshot for {session_date}"
            )
        return set(eligible[-1].symbols)

    def run(self, request: BacktestRequest) -> BacktestResult:
        bars_by_session: dict[str, dict[str, MarketBar]] = {
            session: {} for session in request.sessions
        }
        for bar in request.bars:
            bars_by_session[bar.session_date][bar.symbol] = bar
        sessions = request.sessions
        self._validate_timing(request.weight_points, sessions)
        session_set = set(sessions)
        missing_action_sessions = sorted({
            action.effective_date
            for action in request.corporate_actions
            if action.effective_date not in session_set
        })
        if missing_action_sessions:
            raise BacktestSafetyError(
                f"corporate action dates are absent from the market calendar: {missing_action_sessions}"
            )

        # engine 이름을 빼야 외부 검증 엔진과 동일한 입력 manifest hash가 된다.
        input_payload = {
            "request": request.to_dict(),
            "cost_model": self.costs.to_dict(),
        }
        input_hash = stable_hash(input_payload)
        broker = SimulatedBroker(
            config=request.config,
            costs=self.costs,
            input_hash=input_hash,
            first_session=sessions[0],
        )
        points = {item.effective_date: item for item in request.weight_points}
        actions_by_session: dict[str, list] = defaultdict(list)
        for action in request.corporate_actions:
            actions_by_session[action.effective_date].append(action)

        for session_date in sessions:
            session_bars = bars_by_session[session_date]
            broker.apply_actions(session_date, actions_by_session.get(session_date, ()))
            point = points.get(session_date)
            if point is not None:
                broker.rebalance(
                    session_date=session_date,
                    point=point,
                    bars=session_bars,
                    eligible_buy_symbols=self._eligible_symbols(request, session_date),
                )
            broker.mark_close(session_date, session_bars)

        metrics = calculate_metrics(
            broker.nav_points,
            broker.fills,
            initial_cash=request.config.initial_cash,
            periods_per_year=request.config.periods_per_year,
            risk_free_rate=request.config.risk_free_rate,
        )
        research_only = request.config.cohort_mode == "current_cohort"
        reasons = (
            ("current_cohort universe is not point-in-time and cannot support promotion",)
            if research_only else ()
        )
        artifact_payload = {
            "input_hash": input_hash,
            "engine_version": ENGINE_VERSION,
            "research_only": research_only,
            "research_reasons": reasons,
            "orders": [item.to_dict() for item in broker.orders],
            "fills": [item.to_dict() for item in broker.fills],
            "cash_ledger": [item.to_dict() for item in broker.cash_ledger],
            "corporate_actions": [item.to_dict() for item in broker.action_applications],
            "positions": [item.to_dict() for item in broker.position_snapshots],
            "nav": [item.to_dict() for item in broker.nav_points],
            "metrics": metrics.to_dict(),
        }
        return BacktestResult(
            input_hash=input_hash,
            artifact_hash=stable_hash(artifact_payload),
            engine_version=ENGINE_VERSION,
            research_only=research_only,
            research_reasons=reasons,
            orders=tuple(broker.orders),
            fills=tuple(broker.fills),
            cash_ledger=tuple(broker.cash_ledger),
            corporate_actions=tuple(broker.action_applications),
            positions=tuple(broker.position_snapshots),
            nav=tuple(broker.nav_points),
            metrics=metrics.to_dict(),
        )


def run_backtest(
    request: BacktestRequest,
    *,
    costs: TransactionCostModel | None = None,
) -> BacktestResult:
    """작은 호출 경계를 제공해 향후 entry·FinRL adapter가 엔진 타입에 결합되지 않게 한다."""
    return WeightBacktestEngine(costs).run(request)
