"""대시보드 전략 배분·수익률·성과 지표·몬테카를로 계산."""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from investment_agent.dashboard.calculations._common import (
    _records,
    finite_number,
    parse_date_safe,
    parse_datetime_safe,
)

def _dated_price_series(value: Any) -> pd.Series:
    """단일 종목 응답에서 날짜가 붙은 실제 Close 시계열만 추출한다."""
    if isinstance(value, pd.Series):
        raw_values = value.copy(deep=True)
        raw_index = value.index
    else:
        if isinstance(value, pd.DataFrame):
            frame = value.copy(deep=True)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            frame = pd.DataFrame([dict(row) for row in value if isinstance(row, Mapping)])
        else:
            return pd.Series(dtype="float64")
        if frame.empty:
            return pd.Series(dtype="float64")
        flat_columns = [column for column in frame.columns if not isinstance(column, tuple)]
        lower = {str(column).lower(): column for column in flat_columns}
        close_column = lower.get("close")
        if close_column is None and isinstance(frame.columns, pd.MultiIndex):
            close_columns = [column for column in frame.columns if "close" in {str(part).lower() for part in column}]
            close_column = close_columns[0] if len(close_columns) == 1 else None
        if close_column is None:
            return pd.Series(dtype="float64")
        date_column = lower.get("date") or lower.get("trade_date")
        raw_index = frame[date_column] if date_column is not None else frame.index
        raw_values = frame[close_column]

    try:
        index = pd.DatetimeIndex(pd.to_datetime(raw_index, errors="coerce", utc=True)).tz_localize(None)
    except (AttributeError, TypeError, ValueError):
        return pd.Series(dtype="float64")
    values = pd.to_numeric(raw_values, errors="coerce").to_numpy(dtype="float64")
    series = pd.Series(values, index=index, dtype="float64")
    series = series.loc[~series.index.isna()].replace([np.inf, -np.inf], np.nan)
    return series.loc[~series.index.duplicated(keep="last")].sort_index()


def _price_frame(prices: Any) -> pd.DataFrame:
    """wide/long DataFrame 또는 종목별 외부 조회 매핑을 날짜×종목 Close로 바꾼다."""
    if isinstance(prices, Mapping):
        by_symbol: dict[str, pd.Series] = {}
        for raw_symbol, value in prices.items():
            symbol = str(raw_symbol).upper().strip()
            series = _dated_price_series(value)
            if symbol and not series.empty:
                by_symbol[symbol] = series
        if not by_symbol:
            return pd.DataFrame()
        return pd.concat(by_symbol, axis=1).sort_index()
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        return pd.DataFrame()
    frame = prices.copy(deep=True)
    lower = {str(column).lower(): column for column in frame.columns if not isinstance(column, tuple)}
    if {"ticker", "trade_date", "close"}.issubset(lower):
        frame = frame.pivot_table(
            index=lower["trade_date"],
            columns=lower["ticker"],
            values=lower["close"],
            aggfunc="last",
        )
    elif isinstance(frame.columns, pd.MultiIndex):
        level_zero = {str(value).lower(): value for value in frame.columns.get_level_values(0)}
        if "close" not in level_zero:
            return pd.DataFrame()
        frame = frame.xs(level_zero["close"], axis=1, level=0)
    elif "date" in lower:
        frame = frame.set_index(lower["date"])
    elif "trade_date" in lower:
        frame = frame.set_index(lower["trade_date"])
    try:
        index = pd.to_datetime(frame.index, errors="coerce", utc=True).tz_localize(None)
    except (AttributeError, TypeError, ValueError):
        return pd.DataFrame()
    frame.index = index
    frame = frame.loc[~frame.index.isna()]
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    frame.columns = [str(column).upper() for column in frame.columns]
    return frame.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)


def _valid_weights(value: Any) -> dict[str, float] | None:
    """합계가 1인 유한 비음수 비중만 대문자 종목 사전으로 반환한다."""
    if not isinstance(value, Mapping) or not value:
        return None
    weights: dict[str, float] = {}
    for symbol, raw_weight in value.items():
        normalized = str(symbol).upper().strip()
        weight = finite_number(raw_weight)
        if not normalized or weight is None or weight < 0.0 or weight > 1.0:
            return None
        weights[normalized] = weight
    if not math.isclose(math.fsum(weights.values()), 1.0, abs_tol=1e-6):
        return None
    return weights


def build_strategy_returns(
    allocations: Iterable[Mapping[str, Any]] | pd.DataFrame,
    prices: Any,
) -> pd.DataFrame:
    """실제 배분 적용 구간별 수익률을 전략 컬럼별 DataFrame으로 반환한다.

    각 ``apply_date``부터 다음 적용일 직전까지 첫·마지막 실제 가격으로 buy-and-hold
    수익률을 계산한다. 가격은 wide/long DataFrame과 ``ticker → OHLC DataFrame`` 외부
    조회 응답을 받는다. 양의 비중 자산 중 하나라도 가격이 없거나 배분 합계가 1이 아니면
    해당 구간을 0으로 만들지 않고 제외한다. ``CASH`` 수익률은 명시적으로 0이다.
    """
    price_frame = _price_frame(prices)
    records = _records(allocations)
    if price_frame.empty or not records:
        return pd.DataFrame()
    grouped: dict[str, list[tuple[date, int, dict[str, Any]]]] = {}
    for position, row in enumerate(records):
        strategy_id = str(row.get("strategy_id") or "strategy").strip()
        apply_date = parse_date_safe(row.get("apply_date"))
        if not strategy_id or apply_date is None or _valid_weights(row.get("weights")) is None:
            continue
        grouped.setdefault(strategy_id, []).append((apply_date, position, row))

    series_by_strategy: dict[str, pd.Series] = {}
    for strategy_id, entries in grouped.items():
        entries.sort(key=lambda item: (item[0], item[1]))
        deduplicated: dict[date, dict[str, Any]] = {item[0]: item[2] for item in entries}
        ordered = sorted(deduplicated.items())
        period_returns: dict[pd.Timestamp, float] = {}
        for offset, (apply_date, row) in enumerate(ordered):
            next_date = ordered[offset + 1][0] if offset + 1 < len(ordered) else None
            start = pd.Timestamp(apply_date)
            period = price_frame.loc[price_frame.index >= start]
            if next_date is not None:
                period = period.loc[period.index < pd.Timestamp(next_date)]
            if len(period.index) < 2:
                continue
            weights = _valid_weights(row.get("weights"))
            if weights is None:
                continue
            required_symbols = [symbol for symbol, weight in weights.items() if weight > 0.0 and symbol != "CASH"]
            if any(symbol not in period.columns for symbol in required_symbols):
                continue
            common_period = period[required_symbols].dropna(how="any") if required_symbols else period
            if len(common_period.index) < 2:
                continue
            period_return = 0.0
            valid = True
            for symbol, weight in weights.items():
                if weight == 0.0 or symbol == "CASH":
                    continue
                first = finite_number(common_period[symbol].iloc[0])
                last = finite_number(common_period[symbol].iloc[-1])
                if first is None or last is None or first <= 0.0 or last <= 0.0:
                    valid = False
                    break
                period_return += weight * (last / first - 1.0)
            if valid and math.isfinite(period_return) and period_return > -1.0:
                # 월말 라벨은 외부 SPY 월간 수익률과 같은 축에서 비교하기 위한 표시 기준이다.
                period_end = pd.Timestamp(common_period.index[-1]).to_period("M").to_timestamp("M")
                period_returns[period_end] = period_return
        if period_returns:
            series_by_strategy[strategy_id] = pd.Series(period_returns, dtype="float64")
    if not series_by_strategy:
        return pd.DataFrame()
    output = pd.concat(series_by_strategy, axis=1).sort_index()
    output.index.name = "period_end"
    return output


def _return_series(returns: Sequence[Any] | pd.Series) -> pd.Series:
    """유한하고 -100%보다 큰 실제 기간 수익률만 복사해 Series로 만든다."""
    if isinstance(returns, pd.Series):
        series = pd.to_numeric(returns.copy(deep=True), errors="coerce")
    else:
        if returns is None or isinstance(returns, (str, bytes)):
            return pd.Series(dtype="float64")
        try:
            series = pd.Series(list(returns), dtype="float64")
        except (TypeError, ValueError):
            return pd.Series(dtype="float64")
    series = series.replace([np.inf, -np.inf], np.nan).dropna().astype("float64")
    if (series <= -1.0).any():
        return pd.Series(dtype="float64")
    return series


def performance_metrics(
    returns: Sequence[Any] | pd.Series,
    *,
    periods_per_year: int = 12,
) -> dict[str, Any]:
    """기간 수익률에서 누적수익률·CAGR·MDD·연환산 변동성을 계산한다.

    반환 키는 ``observations``, ``cumulative_returns``(Series), ``total_return``,
    ``cagr``, ``max_drawdown``, ``annualized_volatility``이다. 유효 관측치가 없으면
    수치 필드는 0이 아닌 ``None``이며, CAGR/MDD/변동성은 최소 2개 관측치가 필요하다.
    """
    series = _return_series(returns)
    empty = pd.Series(dtype="float64", name="cumulative_returns")
    if periods_per_year < 1 or series.empty:
        return {
            "observations": 0,
            "cumulative_returns": empty,
            "total_return": None,
            "cagr": None,
            "max_drawdown": None,
            "annualized_volatility": None,
        }
    wealth = (1.0 + series).cumprod()
    cumulative = (wealth - 1.0).rename("cumulative_returns")
    total_return = float(wealth.iloc[-1] - 1.0)
    if len(series) < 2:
        cagr = max_drawdown = annualized_volatility = None
    else:
        cagr = float(wealth.iloc[-1] ** (periods_per_year / len(series)) - 1.0)
        wealth_with_initial = pd.concat([
            pd.Series([1.0], index=["initial"]),
            wealth.reset_index(drop=True),
        ], ignore_index=True)
        drawdown = wealth_with_initial / wealth_with_initial.cummax() - 1.0
        max_drawdown = float(drawdown.min())
        annualized_volatility = float(series.std(ddof=1) * math.sqrt(periods_per_year))
    return {
        "observations": len(series),
        "cumulative_returns": cumulative,
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": max_drawdown,
        "annualized_volatility": annualized_volatility,
    }


def monthly_returns_matrix(
    returns_data: Any,
) -> pd.DataFrame:
    """월별 수익률 시계열을 연도(행) × 월(1~12열) + 연간(YTD열) 매트릭스 DataFrame으로 변환한다.

    인덱스는 연도(정수, 내림차순 정렬), 컬럼은 ``['1월', '2월', ..., '12월', 'YTD']``이다.
    값이 없는 월은 ``NaN``으로 남기며, ``YTD``는 해당 연도에 관측된 월별 수익률들의 기하 복리 합산(cumprod)이다.
    유효 데이터가 없으면 빈 DataFrame을 반환한다.
    """
    if returns_data is None:
        return pd.DataFrame()

    if isinstance(returns_data, pd.DataFrame):
        if returns_data.empty:
            return pd.DataFrame()
        col = returns_data.columns[0]
        s = returns_data[col].dropna()
        dates = pd.to_datetime(s.index, errors="coerce")
        valid_mask = ~dates.isna()
        if not valid_mask.any():
            return pd.DataFrame()
        df = pd.DataFrame({"date": dates[valid_mask], "return": s.values[valid_mask]})
    elif isinstance(returns_data, pd.Series):
        s = returns_data.dropna()
        if s.empty:
            return pd.DataFrame()
        dates = pd.to_datetime(s.index, errors="coerce")
        valid_mask = ~dates.isna()
        if not valid_mask.any():
            return pd.DataFrame()
        df = pd.DataFrame({"date": dates[valid_mask], "return": s.values[valid_mask]})
    elif isinstance(returns_data, Mapping):
        rows: list[dict[str, Any]] = []
        for k, v in returns_data.items():
            val = finite_number(v)
            if val is not None:
                dt = parse_datetime_safe(k) or parse_date_safe(k)
                if dt:
                    rows.append({"date": pd.to_datetime(dt), "return": val})
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
    elif isinstance(returns_data, (list, tuple, Sequence)):
        rows = []
        for item in returns_data:
            if isinstance(item, Mapping):
                dt_val = (
                    item.get("apply_date")
                    or item.get("decision_date")
                    or item.get("date")
                    or item.get("period_end")
                    or item.get("month")
                )
                ret_val = finite_number(
                    item.get("return") if "return" in item else item.get("monthly_return")
                )
                if dt_val and ret_val is not None:
                    dt = parse_datetime_safe(dt_val) or parse_date_safe(dt_val)
                    if dt:
                        rows.append({"date": pd.to_datetime(dt), "return": ret_val})
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
    else:
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    df["return"] = pd.to_numeric(df["return"], errors="coerce")
    df = df.dropna(subset=["date", "return"])
    if df.empty:
        return pd.DataFrame()

    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month

    month_cols = [f"{m}월" for m in range(1, 13)]
    pivot = df.pivot_table(index="year", columns="month", values="return", aggfunc="last")
    pivot = pivot.reindex(columns=range(1, 13))
    pivot.columns = month_cols

    ytd_list: list[float | None] = []
    for yr in pivot.index:
        row_vals = [finite_number(v) for v in pivot.loc[yr] if finite_number(v) is not None]
        if not row_vals:
            ytd_list.append(None)
        else:
            comp = 1.0
            for r in row_vals:
                comp *= (1.0 + r)
            ytd_list.append(comp - 1.0)
    pivot["YTD"] = ytd_list
    pivot.sort_index(ascending=False, inplace=True)
    return pivot


def monte_carlo_fan(
    returns: Sequence[Any] | pd.Series,
    *,
    horizon_periods: int = 60,
    simulations: int = 1_000,
    seed: int = 42,
    min_observations: int = 12,
    quantiles: Sequence[float] = (0.10, 0.25, 0.50, 0.75, 0.90),
) -> pd.DataFrame:
    """실제 기간 수익률을 bootstrap해 결정론적 미래 가치 fan을 만든다.

    ``min_observations`` 미만이거나 파라미터가 유효하지 않으면 빈 DataFrame을
    반환한다. 각 경로는 1.0에서 시작하며 기본 열은 ``p10``~``p90`` 분위수다.
    """
    series = _return_series(returns)
    parsed_quantiles = [finite_number(value) for value in quantiles]
    if (
        len(series) < min_observations
        or min_observations < 2
        or horizon_periods < 1
        or simulations < 2
        or any(value is None or value <= 0.0 or value >= 1.0 for value in parsed_quantiles)
        or parsed_quantiles != sorted(set(parsed_quantiles))
    ):
        return pd.DataFrame()
    rng = np.random.default_rng(seed)
    sampled = rng.choice(series.to_numpy(dtype="float64"), size=(simulations, horizon_periods), replace=True)
    paths = np.concatenate([
        np.ones((simulations, 1), dtype="float64"),
        np.cumprod(1.0 + sampled, axis=1),
    ], axis=1)
    values = np.quantile(paths, parsed_quantiles, axis=0).T
    columns = [f"p{int(round(value * 100)):02d}" for value in parsed_quantiles]
    output = pd.DataFrame(values, columns=columns)
    output.index.name = "period"
    return output



def _monthly_close_frame(prices: Any) -> pd.DataFrame:
    """월말 종가 프레임을 정렬된 숫자 wide 표로 정규화한다."""
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        return pd.DataFrame()
    if isinstance(prices.columns, pd.MultiIndex):
        return pd.DataFrame()
    frame = prices.copy(deep=True)
    parsed_index = pd.to_datetime(pd.Index(frame.index), errors="coerce")
    frame = frame.loc[~pd.isna(parsed_index)]
    if frame.empty:
        return pd.DataFrame()
    frame.index = pd.DatetimeIndex(pd.to_datetime(pd.Index(frame.index), errors="coerce"))
    frame = frame.loc[~frame.index.duplicated(keep="last")].sort_index()
    frame.columns = [str(column).upper().strip() for column in frame.columns]
    frame = frame.apply(pd.to_numeric, errors="coerce")
    return frame.replace([np.inf, -np.inf], np.nan)


def monthly_close_from_daily(
    prices: Any,
    *,
    as_of: date | datetime | None = None,
) -> pd.DataFrame:
    """저장 일봉의 완료된 월말 종가만 전략 재현용 wide 표로 만든다.

    현재 달의 마지막 봉은 아직 확정되지 않았으므로 포함하지 않는다. 입력은
    ``dashboard.db.load_price_history``가 반환하는 단일·복수 종목 가격 계약만
    허용하고, 원자료가 없거나 Close 열을 찾지 못하면 빈 표를 반환한다.
    """
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        return pd.DataFrame()
    if isinstance(prices.columns, pd.MultiIndex):
        if "Close" in prices.columns.get_level_values(0):
            frame = prices.xs("Close", axis=1, level=0)
        elif "Close" in prices.columns.get_level_values(1):
            frame = prices.xs("Close", axis=1, level=1)
        else:
            return pd.DataFrame()
    elif "Close" in prices.columns:
        frame = prices[["Close"]].rename(columns={"Close": "SPY"})
    else:
        return pd.DataFrame()
    frame = frame.copy(deep=True)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, errors="coerce"))
    frame = frame.loc[~frame.index.isna()]
    if frame.empty:
        return pd.DataFrame()
    frame.columns = [str(column).upper().strip() for column in frame.columns]
    frame = frame.apply(pd.to_numeric, errors="coerce")
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(how="all").sort_index()
    if as_of is None:
        as_of_date = datetime.now(ZoneInfo("Asia/Seoul")).date()
    elif isinstance(as_of, datetime):
        as_of_date = as_of.date()
    else:
        as_of_date = as_of
    current_month = pd.Timestamp(as_of_date).to_period("M")
    frame = frame.loc[frame.index.to_period("M") < current_month]
    if frame.empty:
        return pd.DataFrame()
    periods = frame.index.to_period("M")
    monthly = frame.groupby(periods).last()
    monthly.index = monthly.index.to_timestamp("M")
    monthly.index.name = "Date"
    return _monthly_close_frame(monthly)


def _apply_month_start(decision_month_end: pd.Timestamp) -> date:
    """운영 ``decision_and_apply_dates``와 같은 규칙으로 적용월 1일을 만든다."""
    return (decision_month_end.date() + timedelta(days=1)).replace(day=1)


def _weighted_month_return(
    weights: Mapping[str, float],
    month_returns: pd.Series,
) -> tuple[float | None, str | None]:
    """가중 월 수익률. 필요한 자산 수익률이 하나라도 없으면 0으로 채우지 않는다."""
    total = 0.0
    for symbol, raw_weight in weights.items():
        weight = finite_number(raw_weight)
        if weight is None or weight <= 0.0 or symbol == "CASH":
            continue
        if symbol not in month_returns.index:
            return None, f"{symbol} 월 수익률 없음"
        value = finite_number(month_returns.get(symbol))
        if value is None:
            return None, f"{symbol} 월 수익률 결측"
        if value <= -1.0:
            return None, f"{symbol} 월 수익률 비정상"
        total += weight * value
    if not math.isfinite(total) or total <= -1.0:
        return None, "가중 수익률 비정상"
    return total, None


def replay_strategy_rules(
    strategy_id: str,
    monthly_closes: Any,
    *,
    benchmark: str = "SPY",
    min_history_months: int = 13,
) -> dict[str, Any]:
    """운영과 같은 전략 함수로 월말마다 배분을 다시 계산해 이어 붙인다.

    각 월말 M까지의 가격만 보고 배분을 정하고, 실현 수익률은 **다음 달** M+1의
    월간 수익률로만 매긴다(look-ahead 없음). 데이터가 모자란 달은 0으로 채우지 않고
    ``skipped``에 이유와 함께 남긴다. 결과는 호출자의 세션 메모리에만 존재한다.

    반환 키: ``strategy_id``, ``benchmark``, ``months``, ``returns``,
    ``benchmark_returns``, ``skipped``, ``latest``, ``decision_count``,
    ``universe_missing``.
    """
    from investment_agent.research.strategies.strategies import compute_one, monthly_returns

    benchmark_symbol = str(benchmark).upper().strip()
    blank: dict[str, Any] = {
        "strategy_id": str(strategy_id),
        "benchmark": benchmark_symbol,
        "months": [],
        "returns": pd.Series(dtype="float64"),
        "benchmark_returns": pd.Series(dtype="float64"),
        "skipped": [],
        "latest": None,
        "decision_count": 0,
        "universe_missing": [],
    }
    prices = _monthly_close_frame(monthly_closes)
    if prices.empty or int(min_history_months) < 2:
        return blank
    try:
        returns_frame = monthly_returns(prices)
    except (TypeError, ValueError):
        return blank
    if returns_frame.empty or len(returns_frame.index) < int(min_history_months):
        return blank

    months: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    realized: dict[pd.Timestamp, float] = {}
    benchmark_realized: dict[pd.Timestamp, float] = {}
    required_universe: set[str] = set()

    for position in range(int(min_history_months) - 1, len(returns_frame.index)):
        decision_month = pd.Timestamp(returns_frame.index[position])
        window = returns_frame.iloc[: position + 1]
        try:
            computed = compute_one(str(strategy_id), window)
        except KeyError:
            return blank
        except Exception:  # noqa: BLE001 - 한 달의 룰 실패가 전체 재현을 끊지 않게 한다.
            skipped.append({"decision_month": decision_month, "reason": "룰 계산 오류"})
            continue
        if computed is None:
            skipped.append(
                {"decision_month": decision_month, "reason": "월간 데이터 부족·불연속"}
            )
            continue
        weights: dict[str, float] = {}
        for symbol, raw_weight in dict(computed.get("weights") or {}).items():
            weight = finite_number(raw_weight)
            normalized = str(symbol).upper().strip()
            if normalized and weight is not None:
                weights[normalized] = weight
        required_universe.update(symbol for symbol in weights if symbol != "CASH")
        entry: dict[str, Any] = {
            "decision_month": decision_month,
            "apply_month": _apply_month_start(decision_month),
            "mode": computed.get("mode"),
            "weights": weights,
            "signals": computed.get("signals") or {},
            "realized_month": None,
            "realized_return": None,
            "benchmark_return": None,
            "skip_reason": None,
        }
        if position + 1 >= len(returns_frame.index):
            entry["skip_reason"] = "실현 월 미도래"
            months.append(entry)
            continue
        next_month = pd.Timestamp(returns_frame.index[position + 1])
        month_returns = returns_frame.iloc[position + 1]
        entry["realized_month"] = next_month
        value, reason = _weighted_month_return(weights, month_returns)
        if value is None:
            entry["skip_reason"] = reason
            skipped.append({"decision_month": decision_month, "reason": reason})
        else:
            entry["realized_return"] = value
            realized[next_month] = value
        benchmark_value = (
            finite_number(month_returns.get(benchmark_symbol))
            if benchmark_symbol in month_returns.index
            else None
        )
        if benchmark_value is not None and benchmark_value > -1.0:
            entry["benchmark_return"] = benchmark_value
            benchmark_realized[next_month] = benchmark_value
        months.append(entry)

    return {
        "strategy_id": str(strategy_id),
        "benchmark": benchmark_symbol,
        "months": months,
        "returns": pd.Series(realized, dtype="float64").sort_index(),
        "benchmark_returns": pd.Series(benchmark_realized, dtype="float64").sort_index(),
        "skipped": skipped,
        "latest": months[-1] if months else None,
        "decision_count": len(months),
        "universe_missing": sorted(
            symbol for symbol in required_universe if symbol not in prices.columns
        ),
    }


def compare_stored_and_replayed_allocations(
    stored_allocations: Iterable[Mapping[str, Any]],
    replay: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """같은 적용월의 저장 배분과 룰 재현 배분을 비교해 드리프트만 드러낸다.

    한쪽에만 있는 달은 값을 만들지 않고 ``상태``로 표시한다. 비중 비교는 1e-6
    절대오차까지 같은 값으로 본다.
    """
    stored_by_month: dict[str, dict[str, Any]] = {}
    for row in _records(stored_allocations):
        apply_date = parse_date_safe(row.get("apply_date"))
        if apply_date is None:
            continue
        stored_by_month[apply_date.replace(day=1).isoformat()] = dict(row)
    replayed_by_month: dict[str, dict[str, Any]] = {}
    for entry in list((replay or {}).get("months") or []):
        apply_month = entry.get("apply_month")
        if not isinstance(apply_month, date):
            continue
        replayed_by_month[apply_month.replace(day=1).isoformat()] = dict(entry)

    def _normalized(value: Any) -> dict[str, float] | None:
        if not isinstance(value, Mapping) or not value:
            return None
        output: dict[str, float] = {}
        for symbol, raw_weight in value.items():
            weight = finite_number(raw_weight)
            normalized = str(symbol).upper().strip()
            if weight is None or not normalized:
                return None
            output[normalized] = round(weight, 6)
        return {symbol: weight for symbol, weight in output.items() if weight != 0.0}

    rows: list[dict[str, Any]] = []
    for month in sorted(set(stored_by_month) | set(replayed_by_month)):
        stored = stored_by_month.get(month)
        replayed = replayed_by_month.get(month)
        stored_alloc = _normalized((stored or {}).get("weights"))
        replayed_alloc = _normalized((replayed or {}).get("weights"))
        if stored is None:
            status = "DB 미적재 · 화면 재현만"
        elif replayed is None:
            status = "재현 불가 · DB 저장만"
        elif stored_alloc is None or replayed_alloc is None:
            status = "비교 불가 · 비중 값 결측"
        elif set(stored_alloc) != set(replayed_alloc) or any(
            not math.isclose(stored_alloc[symbol], replayed_alloc[symbol], abs_tol=1e-6)
            for symbol in stored_alloc
        ):
            status = "불일치"
        else:
            status = "일치"
        rows.append(
            {
                "적용월": month,
                "상태": status,
                "DB 모드": (stored or {}).get("mode"),
                "재현 모드": (replayed or {}).get("mode"),
                "DB 배분": stored_alloc,
                "재현 배분": replayed_alloc,
            }
        )
    return rows
