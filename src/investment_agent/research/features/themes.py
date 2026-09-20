"""원문 사건에 부여하는 글로벌 테마 분류. 시장 proxy 선택은 Trading이 소유한다."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GlobalTheme:
    name: str
    keywords: tuple[str, ...]


GLOBAL_THEMES: tuple[GlobalTheme, ...] = (
    GlobalTheme("energy_oil", ("oil", "opec", "crude", "brent", "wti", "gasoline", "pipeline")),
    GlobalTheme("rates_fed", ("fed", "fomc", "powell", "rate hike", "rate cut", "treasury yield",
                              "inflation", "cpi", "interest rate")),
    GlobalTheme("trade_tariff", ("tariff", "trade war", "export control", "sanction", "import ban")),
    GlobalTheme("semiconductors_ai", ("semiconductor", "chip", "chips", "gpu", "foundry", "ai model")),
    GlobalTheme("banking_credit", ("bank run", "credit crunch", "default", "bank failure", "liquidity crisis")),
    GlobalTheme("geopolitical", ("war", "missile", "invasion", "military", "ceasefire", "nuclear")),
    GlobalTheme("commodities", ("commodity", "commodities", "copper", "wheat", "supply shock")),
)
_WORD = re.compile(r"[a-z0-9]+")


def tag_themes(text: str) -> tuple[str, ...]:
    """원문에서 테마 이름만 뽑는다. 원문 자체는 저장하지 않는다."""
    lowered = " ".join(_WORD.findall(str(text or "").lower()))
    padded = f" {lowered} "
    return tuple(
        theme.name for theme in GLOBAL_THEMES
        if any(f" {keyword} " in padded for keyword in theme.keywords)
    )
