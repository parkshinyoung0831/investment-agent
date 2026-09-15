"""ALPHA: 이 종목을 지금 얼마나 매력적으로 보는가.

출력은 종목마다 기대초과수익 하나와, 기대수익으로 표현할 수 없을 때만 강제 제약 하나다. 몇 %를
보유할지는 PORTFOLIO(optimizer·RiskGate)가 정한다. 실계좌·승인 결과는 입력이 아니다.

## 기대수익은 factor가 만든다

LLM이 종목마다 적어 내는 기대초과수익은 크기가 제각각이고 과대하다. 여기서는 Grinold의 규칙
`기대수익 = IC × 변동성 × z`를 쓴다. z는 종합 factor 점수의 유니버스 내 순위를 표준정규 점수로 바꾼
값이고, IC는 factor 점수가 실제로 앞으로의 수익률 순위를 맞힌 정도(`research.commands.factor_research`)다.
IC가 작으면 기대수익도 작게 나와 과신이 구조적으로 막힌다.

## TradingAgents 논지는 검증자다

논지는 채택된 ML 보정이 반영된 최신 신호 기록이다(`thesis_views`).

- **거부권**: 논지가 하락을 말하면 비중을 늘리지 못하고(논지가 깨졌으면 보유를 청산), 기대수익은
  factor와 논지 중 낮은 쪽이다.
- **소폭 조정**: 둘 다 상승을 말할 때만 논지 쪽으로 `llm_tilt_weight × 신뢰도`만큼 옮긴다. factor가 나쁘다고
  하는 종목을 논지가 좋다고 해서 사게 되지는 않는다.
- **신규 편입은 검증 뒤**: 보유하지 않은 종목은 유효한 논지가 있어야 새로 담는다.

TradingAgents가 적는 행동 단어(open·hold·exit 등)는 **여기서 한 번만** 논지 상태로 해석한다. 사고팔기는
목표비중 변화에서 파생될 뿐 판단 입력이 아니다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from statistics import NormalDist
from typing import Any, Mapping, Sequence

from investment_agent.platform.serialization import finite_float, parse_datetime
from investment_agent.research.features.factors import percentile_ranks
from investment_agent.trading.decision.constants import SIGNAL_HORIZON_DAYS
from investment_agent.trading.portfolio.optimizer import (
    CONSTRAINT_BLOCK_INCREASE,
    CONSTRAINT_FORCE_EXIT,
    ExpectedReturnSignal,
)

ALPHA_VERSION = "factor-thesis-alpha-v1"
# 순위 끝단의 z가 무한대로 가지 않게 백분위를 자른다(±2.05σ).
_PERCENTILE_CLIP = 0.02
# 논지가 비중 축소를 말하는 행동 단어. 수치가 하락을 말하지 않아도 늘리지는 않는다.
_NEGATIVE_SIGNALS = frozenset({"exit", "reduce", "avoid"})
_POSITIVE_SIGNALS = frozenset({"open", "increase", "hold"})

THESIS_POSITIVE = "positive"
THESIS_NEUTRAL = "neutral"
THESIS_NEGATIVE = "negative"
THESIS_BROKEN = "broken"


@dataclass(frozen=True)
class AlphaPolicy:
    """숫자는 초기값이고 IC 연구로 다시 정한다."""

    version: str = ALPHA_VERSION
    # 월간 횡단면 IC의 보수적 초기값. 문헌의 복합 factor IC는 0.03~0.06이다.
    information_coefficient: float = 0.04
    # 기대수익을 계산해 optimizer에 넘길 factor 상위 종목 수. 공분산·비용 조회 규모를 묶는 계산 한도다.
    candidate_count: int = 40
    view_valid_days: int = 28
    llm_tilt_weight: float = 0.25
    require_verified_entry: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.information_coefficient < 0.5:
            raise ValueError("information_coefficient must be in (0, 0.5)")
        if self.candidate_count < 1 or self.view_valid_days < 1:
            raise ValueError("alpha windows must be positive")
        if not 0 <= self.llm_tilt_weight <= 1:
            raise ValueError("llm_tilt_weight must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ThesisView:
    """TradingAgents 판단 한 건(ML 보정 반영). 판단 시점과 그 판단을 만든 모델 artifact를 함께 든다."""

    ticker: str
    as_of_at: datetime
    signal: str
    expected_excess_return: float
    probability_up: float
    confidence: float
    model_artifact_id: str | None = None

    @classmethod
    def from_proposal(cls, proposal: Mapping[str, Any], *, model_artifact_id: str | None = None) -> "ThesisView | None":
        """저장된 종목 의견 하나. 필요한 값이 하나라도 없으면 논지가 없는 것으로 본다."""
        values = [finite_float(proposal.get(name)) for name in ("expected_excess_return", "probability_up", "confidence")]
        if not proposal.get("ticker") or not proposal.get("as_of_at") or not proposal.get("signal"):
            return None
        if any(value is None for value in values):
            return None
        return cls(str(proposal["ticker"]).upper(), parse_datetime(str(proposal["as_of_at"])).astimezone(timezone.utc),
                   str(proposal["signal"]), float(values[0]), float(values[1]), float(values[2]), model_artifact_id)

    @property
    def thesis_state(self) -> str:
        """행동 단어와 수치가 엇갈리면 수치를 따른다 — `exit`라고 써도 하락을 말하지 않으면 청산하지 않는다."""
        bearish = self.expected_excess_return < 0.0 and self.probability_up < 0.5
        bullish = self.expected_excess_return > 0.0 and self.probability_up > 0.5
        if bearish and self.signal == "exit":
            return THESIS_BROKEN
        if bearish or self.signal in _NEGATIVE_SIGNALS:
            return THESIS_NEGATIVE
        if bullish and self.signal in _POSITIVE_SIGNALS:
            return THESIS_POSITIVE
        return THESIS_NEUTRAL


@dataclass(frozen=True)
class AlphaPlan:
    signals: tuple[ExpectedReturnSignal, ...]
    # 점수가 없어 판단 근거가 없는 보유 종목. optimizer가 움직이지 않게 고정한다.
    fixed_symbols: tuple[str, ...]
    reasons: Mapping[str, str]
    detail: Mapping[str, Mapping[str, Any]]

    @property
    def forced_exits(self) -> tuple[str, ...]:
        return tuple(signal.symbol for signal in self.signals if signal.constraint == CONSTRAINT_FORCE_EXIT)


def _z_scores(scores: Mapping[str, Any]) -> dict[str, float]:
    ranks = percentile_ranks({ticker: score.composite for ticker, score in scores.items()})
    normal = NormalDist()
    return {
        ticker: normal.inv_cdf(min(1 - _PERCENTILE_CLIP, max(_PERCENTILE_CLIP, rank)))
        for ticker, rank in ranks.items()
    }


def alpha_universe(scores: Mapping[str, Any], *, held_symbols: Sequence[str], policy: AlphaPolicy) -> tuple[str, ...]:
    """factor 상위 후보와 보유 종목. 보유는 명단 밖으로 밀려도 계속 판단한다."""
    eligible = sorted(
        (score for score in scores.values() if score.passes_quality_gate and score.composite is not None),
        key=lambda score: (-float(score.composite), score.ticker),
    )
    held = {str(symbol).upper() for symbol in held_symbols}
    return tuple(sorted({score.ticker for score in eligible[:policy.candidate_count]} | held))


def is_valid_view(view: ThesisView | None, *, as_of_at: datetime, policy: AlphaPolicy) -> bool:
    return view is not None and timedelta(0) <= as_of_at - view.as_of_at <= timedelta(days=policy.view_valid_days)


def expected_return_signals(
    scores: Mapping[str, Any],
    *,
    sigma_by_symbol: Mapping[str, float],
    held_symbols: Sequence[str],
    views: Mapping[str, ThesisView | None],
    as_of_at: datetime,
    policy: AlphaPolicy,
) -> AlphaPlan:
    """후보·보유 종목의 기대수익과 제약을 만든다. 변동성을 모르는 종목은 신호를 만들지 않는다."""
    held = {str(symbol).upper() for symbol in held_symbols}
    z_by_symbol = _z_scores(scores)
    signals: list[ExpectedReturnSignal] = []
    fixed: list[str] = []
    reasons: dict[str, str] = {}
    detail: dict[str, dict[str, Any]] = {}
    timestamp = as_of_at.isoformat()
    for symbol in alpha_universe(scores, held_symbols=sorted(held), policy=policy):
        score = scores.get(symbol)
        sigma = finite_float(sigma_by_symbol.get(symbol))
        if score is None or score.composite is None or symbol not in z_by_symbol or sigma is None or sigma <= 0:
            if symbol in held:
                fixed.append(symbol)
                reasons[symbol] = "NO_FACTOR_INPUT_HELD_FIXED"
            continue
        z = z_by_symbol[symbol]
        expected = policy.information_coefficient * sigma * z
        constraint: str | None = None
        reason = "FACTOR_BASE"
        if not score.passes_quality_gate:
            expected = min(0.0, expected)
            constraint = CONSTRAINT_BLOCK_INCREASE
            reason = "FACTOR_BREAKDOWN"
        view = views.get(symbol)
        valid = is_valid_view(view, as_of_at=as_of_at, policy=policy)
        state = view.thesis_state if valid else None
        if valid and state in {THESIS_BROKEN, THESIS_NEGATIVE}:
            view_return = max(-sigma, min(sigma, view.expected_excess_return))
            bearish = view.expected_excess_return < 0 and view.probability_up < 0.5
            expected = min(expected, view_return, 0.0) if bearish else min(expected, 0.0)
            constraint = CONSTRAINT_FORCE_EXIT if state == THESIS_BROKEN and symbol in held else CONSTRAINT_BLOCK_INCREASE
            reason = "THESIS_BROKEN" if constraint == CONSTRAINT_FORCE_EXIT else "THESIS_VETO"
        elif valid and state == THESIS_POSITIVE and expected > 0:
            view_return = max(-sigma, min(sigma, view.expected_excess_return))
            weight = policy.llm_tilt_weight * view.confidence
            expected = expected + weight * (view_return - expected)
            reason = "THESIS_CONFIRMED_TILT" if reason == "FACTOR_BASE" else reason
        elif not valid and symbol not in held and policy.require_verified_entry:
            constraint = CONSTRAINT_BLOCK_INCREASE
            expected = min(expected, 0.0)
            reason = "UNVERIFIED_ENTRY_BLOCKED"
        signals.append(ExpectedReturnSignal(
            symbol=symbol, expected_return=float(expected), confidence=1.0, risk_score=0.5,
            horizon_days=SIGNAL_HORIZON_DAYS, source="alpha", timestamp=timestamp,
            version=policy.version, constraint=constraint,
        ))
        reasons[symbol] = reason
        detail[symbol] = {
            "composite": round(float(score.composite), 6), "z": round(z, 4), "sigma": round(sigma, 6),
            "expected_return": round(float(expected), 6), "constraint": constraint, "reason": reason,
            "thesis_state": state, "thesis_at": view.as_of_at.isoformat() if valid else None,
        }
    return AlphaPlan(tuple(signals), tuple(fixed), reasons, detail)


__all__ = [
    "ALPHA_VERSION",
    "AlphaPlan",
    "AlphaPolicy",
    "THESIS_BROKEN",
    "THESIS_NEGATIVE",
    "THESIS_NEUTRAL",
    "THESIS_POSITIVE",
    "ThesisView",
    "alpha_universe",
    "expected_return_signals",
    "is_valid_view",
]
