"""주식분할 이벤트와 가격 보정을 정규화하는 공용 함수."""
from __future__ import annotations

import math

_PRICE_BASIS_WINDOW = 20
_PRICE_BASIS_MIN_IMPROVEMENT = 0.60
_MATERIAL_RATIO_LOG = math.log(1.25)


def is_split_ratio(value: object) -> bool:
    """0보다 크고 1이 아닌 유효한 주식분할 비율인지 반환한다."""
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(ratio) and ratio > 0 and not math.isclose(
        ratio, 1.0, rel_tol=1e-9, abs_tol=1e-12
    )


def _scale_adjusted_close_with_price(
    row: dict,
    next_row: dict,
    factor: float,
) -> bool:
    """Adj Close가 OHLC와 같은 잘못된 basis인지 연속성으로 판정한다."""
    try:
        close = float(row["close"])
        adj_close = float(row["adj_close"])
        next_close = float(next_row["close"])
        next_adj_close = float(next_row["adj_close"])
    except (KeyError, TypeError, ValueError):
        return True
    if min(close, adj_close, next_close, next_adj_close) <= 0:
        return True

    target_ratio = next_adj_close / next_close
    scaled_ratio = adj_close / close
    unscaled_ratio = adj_close / (close * factor)
    return abs(math.log(scaled_ratio / target_ratio)) <= abs(
        math.log(unscaled_ratio / target_ratio)
    )


def _scale_price_row(
    row: dict,
    factor: float,
    *,
    scale_adjusted_close: bool,
) -> dict:
    if math.isclose(factor, 1.0, rel_tol=1e-12, abs_tol=1e-12):
        return row
    scaled = dict(row)
    fields = ["open", "high", "low", "close"]
    if scale_adjusted_close:
        fields.append("adj_close")
    for field in fields:
        value = scaled.get(field)
        if value is not None:
            scaled[field] = float(value) * factor
    if scaled.get("volume") is not None:
        scaled["volume"] = round(float(scaled["volume"]) / factor)
    scaled["source"] = "yfinance_repaired"
    return scaled


def normalize_split_adjusted_prices(rows: list[dict]) -> list[dict]:
    """Normalize Yahoo's occasionally mixed pre/post-split price basis."""
    normalized = [dict(row) for row in sorted(rows, key=lambda row: str(row["trade_date"]))]
    actions = [
        (index, float(row["split_ratio"]))
        for index, row in enumerate(normalized)
        if is_split_ratio(row.get("split_ratio"))
    ]
    for event_index, ratio in reversed(actions):
        if event_index == 0:
            continue
        next_close = float(normalized[event_index]["close"])
        oldest_factor = 1.0
        window_start = max(0, event_index - _PRICE_BASIS_WINDOW)
        improvement_required = abs(math.log(ratio)) * _PRICE_BASIS_MIN_IMPROVEMENT
        for index in range(event_index - 1, window_start - 1, -1):
            raw_close = float(normalized[index]["close"])
            adjusted_factor = 1.0 / ratio
            raw_error = abs(math.log(raw_close / next_close))
            adjusted_error = abs(math.log((raw_close * adjusted_factor) / next_close))
            factor = (
                adjusted_factor
                if raw_error - adjusted_error >= improvement_required
                else 1.0
            )
            scale_adjusted_close = _scale_adjusted_close_with_price(
                normalized[index], normalized[index + 1], factor
            )
            normalized[index] = _scale_price_row(
                normalized[index],
                factor,
                scale_adjusted_close=scale_adjusted_close,
            )
            next_close = float(normalized[index]["close"])
            oldest_factor = factor
        if not math.isclose(oldest_factor, 1.0, rel_tol=1e-12, abs_tol=1e-12):
            for index in range(window_start - 1, -1, -1):
                scale_adjusted_close = _scale_adjusted_close_with_price(
                    normalized[index], normalized[index + 1], oldest_factor
                )
                normalized[index] = _scale_price_row(
                    normalized[index],
                    oldest_factor,
                    scale_adjusted_close=scale_adjusted_close,
                )
    return normalized


def validate_repaired_prices(
    prices: list[dict],
    actions: list[dict],
) -> None:
    """전체 재다운로드 가격이 액션일에서 다시 분할 점프하지 않는지 검증한다."""
    ordered = sorted(
        (
            str(row["trade_date"]),
            float(row["close"]),
        )
        for row in prices
        if row.get("trade_date") and row.get("close") is not None
    )
    index = {trade_date: i for i, (trade_date, _) in enumerate(ordered)}
    action_rows = {
        str(row.get("trade_date")): float(row["split_ratio"])
        for row in prices
        if row.get("trade_date") and is_split_ratio(row.get("split_ratio"))
    }
    for action in actions:
        action_date = str(action["action_date"])
        expected_ratio = float(action["split_ratio"])
        downloaded_ratio = action_rows.get(action_date)
        if downloaded_ratio is None or not math.isclose(
            downloaded_ratio, expected_ratio, rel_tol=1e-6, abs_tol=1e-9
        ):
            raise ValueError(
                f"split event missing after repair: {action_date} ratio={expected_ratio}"
            )
        event_index = index.get(action_date)
        if event_index is None or event_index == 0:
            continue
        previous_close = ordered[event_index - 1][1]
        event_close = ordered[event_index][1]
        if previous_close <= 0 or event_close <= 0:
            continue
        observed_jump = event_close / previous_close
        unrepaired_jump = 1.0 / expected_ratio
        normalized_error = abs(math.log(observed_jump))
        unrepaired_error = abs(math.log(observed_jump / unrepaired_jump))
        improvement_required = (
            abs(math.log(expected_ratio)) * _PRICE_BASIS_MIN_IMPROVEMENT
        )
        if (
            abs(math.log(expected_ratio)) >= _MATERIAL_RATIO_LOG
            and normalized_error - unrepaired_error >= improvement_required
        ):
            raise ValueError(
                "price history still has split discontinuity: "
                f"date={action_date} observed={observed_jump:.4f} "
                f"unrepaired={unrepaired_jump:.4f}"
            )
