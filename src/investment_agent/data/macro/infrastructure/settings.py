"""매크로 기능에서 공통으로 쓰는 설정값을 모아둔 곳."""
from __future__ import annotations

DAILY_LOOKBACK_DAYS = 14
BACKFILL_WARMUP_DAYS = 400

# 소스별 갱신 지연을 흡수하도록 주기별 재조회 구간을 둔다.
INCREMENTAL_LOOKBACK_DAYS = {
    "daily": DAILY_LOOKBACK_DAYS,
    "weekly": 45,
    "monthly": 120,
    "quarterly": 500,
}
