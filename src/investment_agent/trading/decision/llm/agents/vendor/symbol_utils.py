"""브로커/사용자 심볼을 Yahoo Finance 심볼로 정규화한다.

TradingAgents(Apache-2.0) `dataflows/symbol_utils.py`에서 이식(그래프·LLM 의존
없는 순수 함수만). `NoMarketDataError` 재수출과 `is_yahoo_safe`는 이 저장소가
쓰지 않아 옮기지 않았다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_FOREX_CURRENCIES = frozenset({
    "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD",
    "CNY", "CNH", "HKD", "SGD", "SEK", "NOK", "DKK", "PLN",
    "MXN", "ZAR", "TRY", "INR", "KRW", "BRL", "RUB", "THB",
})

_CRYPTO_BASES = frozenset(
    {"BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LTC", "BCH", "DOT", "AVAX", "LINK"}
)

_ALIASES = {
    "XAUUSD": "GC=F", "XAU": "GC=F", "GOLD": "GC=F",
    "XAGUSD": "SI=F", "XAG": "SI=F", "SILVER": "SI=F",
    "XPTUSD": "PL=F", "XPDUSD": "PA=F",
    "WTICOUSD": "CL=F", "USOIL": "CL=F", "WTI": "CL=F",
    "BCOUSD": "BZ=F", "UKOIL": "BZ=F", "BRENT": "BZ=F",
    "NATGAS": "NG=F", "XNGUSD": "NG=F",
    "COPPER": "HG=F", "XCUUSD": "HG=F",
    "SPX500": "^GSPC", "US500": "^GSPC", "SPX": "^GSPC",
    "NAS100": "^NDX", "US100": "^NDX", "USTEC": "^NDX",
    "US30": "^DJI", "DJI30": "^DJI", "WS30": "^DJI",
    "GER40": "^GDAXI", "GER30": "^GDAXI", "DE40": "^GDAXI",
    "UK100": "^FTSE", "JP225": "^N225", "JPN225": "^N225",
    "FRA40": "^FCHI", "EU50": "^STOXX50E", "HK50": "^HSI",
}

_CRYPTO_QUOTES = ("USDT", "USDC", "USD")


def crypto_base(raw: str) -> str | None:
    """USD/USDT/USDC로 표시된 크립토 심볼(대시 유무 무관)의 base를 돌려준다."""
    if not isinstance(raw, str):
        return None
    compact = raw.strip().upper().rstrip("+").replace("-", "")
    for quote in _CRYPTO_QUOTES:
        if compact.endswith(quote):
            base = compact[: -len(quote)]
            return base if base in _CRYPTO_BASES else None
    return None


def _normalize_crypto(value: str) -> str | None:
    base = crypto_base(value)
    return f"{base}-USD" if base else None


def normalize_symbol(raw: str) -> str:
    """브로커/사용자 심볼을 Yahoo Finance 심볼로 정규화한다(우선순위: 별칭→크립토→FX→그대로)."""
    if not isinstance(raw, str) or not raw.strip():
        return raw
    value = raw.strip().upper().rstrip("+")
    crypto = _normalize_crypto(value)
    if value in _ALIASES:
        canonical = _ALIASES[value]
    elif crypto is not None:
        canonical = crypto
    elif len(value) == 6 and value[:3] in _FOREX_CURRENCIES and value[3:] in _FOREX_CURRENCIES:
        canonical = f"{value}=X"
    else:
        canonical = value
    if canonical != raw.strip().upper():
        logger.info("Resolved symbol %r to Yahoo symbol %r", raw, canonical)
    return canonical
