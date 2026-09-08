"""전략·모드·자산의 표시 이름 계약.

화면과 알림은 전략을 **부를 이름**만 필요로 하지, 전략이 어떻게 계산되는지도
DB에 어떤 이름으로 저장되는지도 알 필요가 없다. 그래서 `StrategyMeta`를 통째로
넘기지 않고 표시에 쓰는 값만 골라 낸다 — `db_name`처럼 저장 계층에 속한 것은
이 계약에 없다.

사실의 owner는 `investment_agent.research.strategies.catalog`다. 여기서는 그것을 읽어
표시용으로 좁힐 뿐이고, 방향은 domain → reporting → dashboard 하나뿐이다.
"""
from __future__ import annotations

from dataclasses import dataclass

from investment_agent.research.strategies.catalog import (
    MODE_LABELS as _MODE_LABELS,
    STRATEGY_CATALOG as _STRATEGY_CATALOG,
    TICKER_LABELS as _TICKER_LABELS,
)


@dataclass(frozen=True)
class StrategyLabel:
    """전략 하나를 화면에 적을 때 쓰는 값."""

    strategy_id: str
    name: str
    description: str


def strategy_label(strategy_id: str | None) -> StrategyLabel | None:
    """등록된 전략이면 표시 이름을, 아니면 None. 없는 전략을 지어내지 않는다."""
    meta = _STRATEGY_CATALOG.get(str(strategy_id or ""))
    if meta is None:
        return None
    return StrategyLabel(
        strategy_id=str(strategy_id),
        name=meta.notify_name,
        description=meta.notify_description,
    )


def strategy_ids() -> tuple[str, ...]:
    """계산 함수가 등록된 전략 id — `ensure_registered_strategies()`가 카탈로그와
    compute 등록을 같은 집합으로 강제하므로 카탈로그 키가 곧 그 목록이다.

    화면이 이 순서를 그대로 나열하므로 정렬하지 않고 카탈로그 선언 순서를 지킨다.
    """
    return tuple(_STRATEGY_CATALOG)


def mode_label(value: object) -> str:
    """판단 모드의 한글 라벨. 모르는 값은 원문 그대로 두고 비면 대시."""
    text = str(value or "").strip()
    return _MODE_LABELS.get(text, text or "—")


def ticker_label(symbol: str | None) -> str | None:
    """자산 티커의 한글 이름. 모르는 티커는 None — 티커만 그대로 쓰라는 뜻이다."""
    return _TICKER_LABELS.get(str(symbol or ""))


def strategy_tickers() -> tuple[str, ...]:
    """전략 재현에 필요한 자산 코드를 선언 순서대로 반환한다."""
    return tuple(_TICKER_LABELS)


__all__ = [
    "StrategyLabel",
    "mode_label",
    "strategy_ids",
    "strategy_label",
    "strategy_tickers",
    "ticker_label",
]
