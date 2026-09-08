"""공용 카탈로그(`investment_agent.research.strategies.catalog`)에서 파생한 알림용 전략 라벨 모음."""
from __future__ import annotations

from investment_agent.research.strategies.catalog import MODE_LABELS, STRATEGY_CATALOG, TICKER_LABELS


# formatting.py가 이 이름들을 import한다. 라벨 SSOT는 catalog이고 여기선 알림용 표현만 추린다.
TICKERS = dict(TICKER_LABELS)
MODE_KO = dict(MODE_LABELS)
STRATEGY_DESC = {
    strategy_id: meta.notify_description
    for strategy_id, meta in STRATEGY_CATALOG.items()
}
NAMES = {
    strategy_id: meta.notify_name
    for strategy_id, meta in STRATEGY_CATALOG.items()
}
