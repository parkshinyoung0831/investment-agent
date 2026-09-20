"""종목 이름이 없는 글로벌 사건을 보유 종목의 재분석 우선순위로 옮긴다.

```text
글로벌 사건(유가·금리·관세·전쟁…) → 테마 → 대표 ETF → 보유 종목의 그 ETF 민감도 → 재분석 대상
```

## 사건 하나로 매매하지 않는다

여기서 나오는 것은 **재분석 우선순위**뿐이다. 비중은 재분석된 의견이 optimizer·RiskGate를 거쳐야
바뀐다. 그래서 검증 규칙은 "재분석할 가치가 있는가"를 묻는다.

- 신뢰성: 서로 다른 제공자 두 곳 이상이 같은 사건을 보도했는가(단일 출처 루머 배제).
- 중요도: 사건 중요도가 고영향 기준(`HIGH_IMPACT_EVENT_IMPORTANCE`) 이상인가.
- 시장 확인: 대표 ETF의 사건 이후 첫 거래일 수익률 크기가 그 ETF의 최근 20일 일간 변동성보다
  큰가. 가격이 반응하지 않은 뉴스는 이미 반영됐거나 중요하지 않다.
- 포트폴리오 관련성: 보유 종목 중 그 ETF 민감도 절대값이 `MIN_SENSITIVITY` 이상인 종목만.

테마 키워드와 민감도 기준은 초기 정의다. 재분석 결과가 실제로 판단을 바꿨는지는 원장에 남는다.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

from investment_agent.platform.serialization import parse_datetime
from investment_agent.trading.decision.candidate_ranker import HIGH_IMPACT_EVENT_IMPORTANCE, PriorityCandidate

MIN_PROVIDERS = 2
MIN_SENSITIVITY = 0.5


PROXY_BY_THEME = {
    "energy_oil": "XLE",
    "rates_fed": "TLT",
    "trade_tariff": "QQQ",
    "semiconductors_ai": "XLK",
    "banking_credit": "XLF",
    "geopolitical": "SPY",
    "commodities": "DBC",
}


def _daily_returns(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, float]]:
    ordered = sorted((str(row["trade_date"])[:10], float(row["close"])) for row in rows if row.get("close"))
    return [(day, close / previous - 1.0) for (_, previous), (day, close) in zip(ordered, ordered[1:]) if previous > 0]


def market_confirms(proxy_rows: Sequence[Mapping[str, Any]], *, available_at: datetime, window: int = 20) -> bool:
    """사건 공개 뒤 첫 거래일의 대표 ETF 수익률 크기가 직전 20일 일간 변동성보다 큰가."""
    returns = _daily_returns(proxy_rows)
    event_day = available_at.astimezone(timezone.utc).date()
    after = [(day, value) for day, value in returns if date.fromisoformat(day) > event_day]
    before = [value for day, value in returns if date.fromisoformat(day) <= event_day][-window:]
    if not after or len(before) < 2:
        return False
    mean = sum(before) / len(before)
    volatility = math.sqrt(sum((value - mean) ** 2 for value in before) / (len(before) - 1))
    return abs(after[0][1]) > volatility


def global_event_priorities(
    events: Sequence[Mapping[str, Any]],
    *,
    held_tickers: Sequence[str],
    last_analyzed_at: Mapping[str, datetime],
    sensitivities: Mapping[str, Mapping[str, float]],
    proxy_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    as_of_at: datetime,
) -> tuple[PriorityCandidate, ...]:
    """검증을 통과한 글로벌 사건마다, 민감한 보유 종목 중 그 뒤 아직 분석하지 않은 것을 고른다.

    `sensitivities`는 대표 ETF → 종목 → 민감도다.
    """
    held = {str(ticker).upper() for ticker in held_tickers}
    best: dict[str, PriorityCandidate] = {}
    for event in events:
        if event.get("ticker"):
            continue
        available = parse_datetime(str(event["available_at"]))
        if available > as_of_at:
            continue
        importance = float(event.get("importance") or 0.0)
        providers = set((event.get("metadata") or {}).get("providers") or ())
        if importance < HIGH_IMPACT_EVENT_IMPORTANCE or len(providers) < MIN_PROVIDERS:
            continue
        for theme_name in (event.get("metadata") or {}).get("themes") or ():
            proxy = PROXY_BY_THEME.get(theme_name)
            if proxy is None or not market_confirms(proxy_rows.get(proxy) or (), available_at=available):
                continue
            for ticker in sorted(held):
                sensitivity = float((sensitivities.get(proxy) or {}).get(ticker, 0.0))
                previous = last_analyzed_at.get(ticker)
                if abs(sensitivity) < MIN_SENSITIVITY or (previous is not None and previous >= available):
                    continue
                candidate = PriorityCandidate(ticker, 0, f"held_global_event:{theme_name}",
                                              min(1.0, importance * abs(sensitivity)))
                if ticker not in best or candidate.importance > best[ticker].importance:
                    best[ticker] = candidate
    return tuple(sorted(best.values(), key=lambda item: (-item.importance, item.ticker)))


__all__ = [
    "MIN_PROVIDERS",
    "MIN_SENSITIVITY",
    "PROXY_BY_THEME",
    "global_event_priorities",
    "market_confirms",
]
