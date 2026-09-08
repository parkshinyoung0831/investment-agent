"""대시보드 읽기 전용 계산 진입점.

이 모듈은 대시보드 화면(app_pages/*)과 외부 호출자가 단일 네임스페이스로
계산 함수를 참조하도록 도메인별 계산 모듈을 한 곳에서 공개한다.
"""
from __future__ import annotations

from investment_agent.dashboard.calculations._common import (
    _records,
    covariance_to_correlation,
    finite_number,
    parse_date_safe,
    parse_datetime_safe,
    today_kst,
)
from investment_agent.dashboard.calculations.earnings import (
    free_cash_flow,
    historical_surprise_series,
    latest_estimate_overview,
    pre_release_consensus,
    quarter_growth,
    sec_gaap_diluted_eps,
)
from investment_agent.dashboard.calculations.gurus import (
    _cusip_mapping,
    _long_equity_book,
    guru_portfolio,
    guru_position_changes,
)
from investment_agent.dashboard.calculations.macro import (
    _MACRO_SERIES,
    _macro_series_frame,
    _macro_signal,
    diagnose_macro,
    macro_alert_counts,
    macro_change,
    macro_indicator_rows,
    macro_latest,
    macro_regime,
    macro_sections,
    macro_value_text,
)
from investment_agent.dashboard.calculations.ops import _ACTIVE_JOB_STATES, inspect_harness_state
from investment_agent.dashboard.calculations.portfolio import (
    _holding_rows,
    _price_mapping,
    rebalance_portfolio,
)
from investment_agent.dashboard.calculations.schedule import (
    DEFAULT_SCHEDULE_HORIZON,
    SCHEDULE_HORIZONS,
    d_day_label,
    schedule_window,
)
from investment_agent.dashboard.calculations.strategy import (
    _apply_month_start,
    _dated_price_series,
    _monthly_close_frame,
    _price_frame,
    _return_series,
    _valid_weights,
    _weighted_month_return,
    build_strategy_returns,
    compare_stored_and_replayed_allocations,
    monte_carlo_fan,
    monthly_close_from_daily,
    monthly_returns_matrix,
    performance_metrics,
    replay_strategy_rules,
)
from investment_agent.dashboard.calculations.tech import (
    add_technical_indicators,
)
from investment_agent.reporting.services.investment import normalize_role_analyses

__all__ = [
    "_ACTIVE_JOB_STATES",
    "_MACRO_SERIES",
    "_apply_month_start",
    "_cusip_mapping",
    "_dated_price_series",
    "_holding_rows",
    "_long_equity_book",
    "_macro_series_frame",
    "_macro_signal",
    "_monthly_close_frame",
    "_price_frame",
    "_price_mapping",
    "_records",
    "_return_series",
    "_valid_weights",
    "_weighted_month_return",
    "add_technical_indicators",
    "build_strategy_returns",
    "compare_stored_and_replayed_allocations",
    "covariance_to_correlation",
    "d_day_label",
    "diagnose_macro",
    "finite_number",
    "free_cash_flow",
    "guru_portfolio",
    "guru_position_changes",
    "historical_surprise_series",
    "inspect_harness_state",
    "latest_estimate_overview",
    "macro_alert_counts",
    "macro_change",
    "macro_indicator_rows",
    "macro_latest",
    "macro_regime",
    "macro_sections",
    "macro_value_text",
    "monte_carlo_fan",
    "monthly_close_from_daily",
    "monthly_returns_matrix",
    "normalize_role_analyses",
    "parse_date_safe",
    "parse_datetime_safe",
    "performance_metrics",
    "pre_release_consensus",
    "quarter_growth",
    "rebalance_portfolio",
    "replay_strategy_rules",
    "schedule_window",
    "SCHEDULE_HORIZONS",
    "DEFAULT_SCHEDULE_HORIZON",
    "sec_gaap_diluted_eps",
    "today_kst",
]
