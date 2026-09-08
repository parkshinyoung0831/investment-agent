"""Native와 LumiBot이 같은 manifest를 소비했는지 검증하고 차이를 숨기지 않는다."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Type

import pandas as pd

from investment_agent.research.backtest.contracts import BacktestRequest, BacktestResult
from investment_agent.research.backtest.contracts import stable_hash
from investment_agent.research.evaluation.costs import TransactionCostModel

_METRICS = (
    "total_return", "cagr", "sharpe_ratio", "sortino_ratio", "max_drawdown",
    "annualized_volatility", "turnover", "win_rate", "average_gross_exposure",
    "transaction_cost", "trade_count",
)


@dataclass(frozen=True)
class MetricDifference:
    metric: str
    native: float
    lumibot: float
    absolute_difference: float
    tolerance: float
    is_within_tolerance: bool


@dataclass(frozen=True)
class BacktestComparison:
    input_hash: str
    differences: tuple[MetricDifference, ...]
    is_compatible: bool
    native_engine: str
    validation_engine: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_hash": self.input_hash,
            "is_compatible": self.is_compatible,
            "native_engine": self.native_engine,
            "validation_engine": self.validation_engine,
            "differences": [item.__dict__ for item in self.differences],
        }


def compare_results(
    native: BacktestResult,
    lumibot_metrics: Mapping[str, Any],
    *,
    tolerance_by_metric: Mapping[str, float] | None = None,
    validation_input_hash: str | None = None,
) -> BacktestComparison:
    if validation_input_hash is not None and validation_input_hash != native.input_hash:
        raise ValueError("LumiBot did not consume the exact Native input manifest")
    tolerances = {
        "total_return": 0.002, "cagr": 0.003, "sharpe_ratio": 0.05,
        "sortino_ratio": 0.08, "max_drawdown": 0.003,
        "annualized_volatility": 0.003, "turnover": 0.01, "win_rate": 0.02,
        "average_gross_exposure": 0.01, "transaction_cost": 1.0, "trade_count": 0.0,
        **dict(tolerance_by_metric or {}),
    }
    differences: list[MetricDifference] = []
    for metric in _METRICS:
        if metric not in native.metrics or metric not in lumibot_metrics:
            raise ValueError(f"backtest comparison metric is missing: {metric}")
        left = float(native.metrics[metric])
        right = float(lumibot_metrics[metric])
        difference = abs(left - right)
        tolerance = float(tolerances[metric])
        differences.append(MetricDifference(
            metric=metric, native=left, lumibot=right,
            absolute_difference=difference, tolerance=tolerance,
            is_within_tolerance=difference <= tolerance,
        ))
    return BacktestComparison(
        input_hash=native.input_hash, differences=tuple(differences),
        is_compatible=all(item.is_within_tolerance for item in differences),
        native_engine=native.engine_version, validation_engine="lumibot",
    )


class LumiBotValidationEngine:
    """Supabase를 읽지 않고 완전한 BacktestRequest에서만 PandasData를 만든다."""

    def __init__(
        self,
        request: BacktestRequest,
        *,
        costs: TransactionCostModel | None = None,
    ):
        self.request = request
        self.costs = costs or TransactionCostModel()

    @property
    def input_hash(self) -> str:
        return stable_hash({
            "request": self.request.to_dict(),
            "cost_model": self.costs.to_dict(),
        })

    def pandas_data(self) -> dict[Any, Any]:
        try:
            from lumibot.entities import Asset, Data
        except ImportError as exc:  # pragma: no cover - 선택 의존성
            raise RuntimeError("LumiBot이 필요하다: uv sync --group research") from exc
        by_symbol: dict[str, list[dict[str, Any]]] = {}
        dividend_by_key = {
            (action.symbol, action.effective_date): action.value
            for action in self.request.corporate_actions if action.kind == "dividend"
        }
        split_by_key = {
            (action.symbol, action.effective_date): action.value
            for action in self.request.corporate_actions if action.kind == "split"
        }
        for bar in self.request.bars:
            by_symbol.setdefault(bar.symbol, []).append({
                "datetime": pd.Timestamp(bar.session_date, tz="UTC"),
                "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close,
                "volume": bar.volume,
                "dividend": dividend_by_key.get((bar.symbol, bar.session_date), 0.0),
                "stock_splits": split_by_key.get((bar.symbol, bar.session_date), 0.0),
            })
        data: dict[Any, Any] = {}
        for symbol, rows in sorted(by_symbol.items()):
            asset = Asset(symbol=symbol, asset_type="stock")
            frame = pd.DataFrame(rows).set_index("datetime").sort_index()
            data[asset] = Data(asset=asset, df=frame, timestep="day")
        return data

    def run(self, strategy_class: Type[Any], *, parameters: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        """사용자가 제공한 thin Strategy에 동일 weight/order manifest를 parameters로 넘긴다."""
        try:
            from lumibot.backtesting import PandasDataBacktesting
        except ImportError as exc:  # pragma: no cover - 선택 의존성
            raise RuntimeError("LumiBot이 필요하다: uv sync --group research") from exc
        start = datetime.fromisoformat(self.request.sessions[0])
        end = datetime.fromisoformat(self.request.sessions[-1])
        common = {
            "investment_agent_input_hash": self.input_hash,
            "weight_points": [item.to_dict() for item in self.request.weight_points],
            "backtest_config": self.request.config.to_dict(),
            "transaction_cost_model": self.costs.to_dict(),
            **dict(parameters or {}),
        }
        result = strategy_class.backtest(
            PandasDataBacktesting, start, end,
            pandas_data=self.pandas_data(),
            budget=self.request.config.initial_cash,
            parameters=common,
            show_plot=False, show_tearsheet=False, save_tearsheet=False,
        )
        normalized = dict(result) if isinstance(result, Mapping) else {"raw_result": result}
        normalized["investment_agent_input_hash"] = self.input_hash
        return normalized


__all__ = [
    "BacktestComparison", "LumiBotValidationEngine", "MetricDifference", "compare_results",
]
