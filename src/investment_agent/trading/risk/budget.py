"""시장·거시 입력을 오늘의 위험 한도로 바꾼다. 종목을 고르지 않고 한도만 조인다.

```
SPY 가격 → 시장 상태(RISK_ON·NORMAL·RISK_OFF·CRISIS) ┐
신용스프레드·VIX·시장 폭 → 주식 노출 상한             ├→ PortfolioRiskPolicy → optimizer·RiskGate
```

- 시장 상태 이름은 보고·화면용이다. 판단에 쓰이는 것은 그 결과인 종목·섹터 상한, 최소 현금, 비중 확대 허용뿐이다.
- SPY 이력이 없으면 `ContractError`다. 시장 상태를 모르는 날은 위기일 수도 있는 날이고, 그때 평상시 한도로
  목표를 만들면 조이기만 하는 위험 예산이 가장 필요한 순간에 꺼진다.
- 거시 재료는 없으면 조이지 않는다. 웹 수집 series 하루 장애로 목표 갱신을 세우면 위험을 줄여야 할 날에도
  줄이지 못한다. 그 사실은 metadata에 남는다.
- 경계·배율은 `MarketRiskPolicy`(버전 있음)가 갖는다. `use_market_risk=False`는 연구의 Ablation 전용이다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from investment_agent.platform.logging import get_logger
from investment_agent.trading.risk.gate import PortfolioRiskPolicy
from investment_agent.trading.risk.macro_exposure import MACRO_SERIES, assess_macro_exposure, tighten_for_macro
from investment_agent.trading.risk.regime_budget import (
    DEFAULT_MARKET_RISK_POLICY,
    MarketRiskPolicy,
    regime_from_benchmark_prices,
    tighten_for_regime,
)

log = get_logger(__name__)

BENCHMARK_SYMBOL = "SPY"


def _macro_exposure(repository: Any, *, as_of_at: datetime):
    try:
        histories = repository.macro_histories(MACRO_SERIES, as_of_at=as_of_at)
    except Exception as exc:  # noqa: BLE001 - 거시 재료 장애가 목표 갱신을 멈추게 두지 않는다
        log.warning("macro exposure inputs unavailable: %s", type(exc).__name__)
        return None
    return assess_macro_exposure(histories, as_of_at=as_of_at)


def risk_budget(
    repository: Any,
    *,
    as_of_at: datetime,
    base_policy: PortfolioRiskPolicy | None = None,
    market_policy: MarketRiskPolicy = DEFAULT_MARKET_RISK_POLICY,
    use_market_risk: bool = True,
) -> tuple[PortfolioRiskPolicy, dict[str, Any]]:
    """가격 시장 상태와 거시 노출 규칙을 모두 반영한 위험 정책과 그 근거 metadata."""
    base = base_policy or PortfolioRiskPolicy()
    if not use_market_risk:
        return base, {"market_regime": None, "market_risk_policy": None, "macro_exposure": None}
    regime = regime_from_benchmark_prices(
        repository.market_prices(BENCHMARK_SYMBOL, as_of_at, limit=max(260, market_policy.drawdown_window + 1)),
        as_of_at=as_of_at, policy=market_policy,
    )
    macro = _macro_exposure(repository, as_of_at=as_of_at)
    policy = tighten_for_macro(tighten_for_regime(base, regime, market_policy), macro)
    metadata = {
        "market_regime": {
            "risk_state": regime.risk_state,
            "regime_id": regime.regime_id,
            "trend": regime.trend,
            "volatility_state": regime.volatility_state,
            "inputs": dict(regime.metadata.get("inputs", {})),
            "source_ids": list(regime.source_ids),
        },
        "regime_budget_version": market_policy.version,
        "market_risk_policy": market_policy.to_dict(),
        "macro_exposure": macro.to_metadata() if macro is not None else None,
    }
    return policy, metadata


__all__ = ["BENCHMARK_SYMBOL", "risk_budget"]
