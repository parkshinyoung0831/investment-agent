"""ALPHA ENGINE: 이 종목의 기대초과수익(Expected Excess Return)은 얼마인가.

출력은 종목마다 기대초과수익 하나, 그 값을 얼마나 믿을지(confidence), 기대수익으로 표현할 수 없을 때만
강제 제약 하나다. 몇 %를 보유할지는 PORTFOLIO(optimizer)가 정한다. 실계좌·승인 결과는 입력이 아니다.

```
factor 사전값(IC×σ×z) ─┐
champion ML 예측 ───────┼→ 기대초과수익 ─→ TradingAgents 거부권·소폭 조정 ─→ 신호(+제약)
                        │
Event ─ 재분석 트리거 ──┘ (Event는 값을 고치지 않고 논지를 새로 받게 할 뿐이다)
```

## factor는 투명한 사전값이다

Grinold의 규칙 `기대수익 = IC × 변동성 × z`. z는 종합 factor 점수의 유니버스 내 순위를 표준정규 점수로 바꾼
값이고, IC는 factor 점수가 실제로 앞으로의 수익률 순위를 맞힌 정도(`research.commands.factor_research`)다.
IC가 작으면 기대수익도 작게 나와 과신이 구조적으로 막힌다.

## champion ML은 통계적 추정기다

채택된 모델(`research.ml_serving`)이 있으면 그 예측을 **OOS IC로 잰 신뢰도만큼** 사전값과 섞는다. 모델이
없거나 IC가 유의하지 않으면 몫이 0이라 factor 사전값 그대로다. 예측은 ±1σ로 자른다.

## TradingAgents 논지는 검증자다

- **거부권**: 논지가 부정이면 비중을 늘리지 못하고 기대수익은 0 이하다. hard constraint(`force_exit`·`exclude`)면
  보유를 청산하고 새로 담지 않는다.
- **소폭 조정**: 숫자와 논지가 모두 긍정일 때만 논지 쪽으로 `llm_tilt_weight × 신뢰도`만큼 옮긴다.
- **신규 편입은 검증 뒤**: 보유하지 않은 종목은 유효한 논지가 있어야 새로 담는다.

명시 논지 필드(`thesis`·`hard_constraint`)가 없는 옛 기록만 행동 단어(open·exit 등)를 여기서 한 번 해석한다.

## confidence는 근거들의 일치도다

factor·ML·논지 중 방향을 말하는 근거가 최종 기대수익과 같은 방향인 비율이다. LLM이 스스로 적은 확신은
검증된 적이 없어 쓰지 않는다. optimizer는 기대수익에 이 값을 곱한다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from statistics import NormalDist
from typing import Any, Mapping, Sequence

from investment_agent.platform.serialization import finite_float, parse_datetime
from investment_agent.research.adapters.trading import percentile_ranks
from investment_agent.forecasting import SIGNAL_HORIZON_DAYS
from investment_agent.trading.portfolio.contracts import (
    HARD_CONSTRAINT_BLOCK_NEW_BUY,
    HARD_CONSTRAINT_EXCLUDE,
    HARD_CONSTRAINT_FORCE_EXIT,
    HARD_CONSTRAINT_NONE,
    HARD_CONSTRAINTS,
    THESES,
)
from investment_agent.trading.portfolio.optimizer import (
    CONSTRAINT_BLOCK_INCREASE,
    CONSTRAINT_FORCE_EXIT,
    ExpectedReturnSignal,
)

ALPHA_VERSION = "factor-ml-thesis-alpha-v2"
# 순위 끝단의 z가 무한대로 가지 않게 백분위를 자른다(±2.05σ).
_PERCENTILE_CLIP = 0.02
# 명시 논지 필드가 없는 옛 기록의 행동 단어 해석.
_NEGATIVE_SIGNALS = frozenset({"exit", "reduce", "avoid"})
_POSITIVE_SIGNALS = frozenset({"open", "increase", "hold"})

THESIS_POSITIVE = "positive"
THESIS_NEUTRAL = "neutral"
THESIS_NEGATIVE = "negative"
THESIS_BROKEN = "broken"


@dataclass(frozen=True)
class AlphaPolicy:
    """숫자는 초기값이고 IC 연구·Ablation으로 다시 정한다."""

    version: str = ALPHA_VERSION
    # 월간 횡단면 IC의 보수적 초기값. 문헌의 복합 factor IC는 0.03~0.06이다.
    information_coefficient: float = 0.04
    # 기대수익을 계산해 optimizer에 넘길 factor 상위 종목 수. 공분산·비용 조회 규모를 묶는 계산 한도다.
    candidate_count: int = 40
    view_valid_days: int = 28
    llm_tilt_weight: float = 0.25
    require_verified_entry: bool = True
    # Ablation 스위치. 운영 기본값은 둘 다 켜짐이다.
    use_ml: bool = True
    use_thesis: bool = True

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
    """TradingAgents 판단 한 건. 판단 시점과 그 판단을 만든 모델 artifact를 함께 든다."""

    ticker: str
    as_of_at: datetime
    signal: str
    expected_excess_return: float
    probability_up: float
    confidence: float
    model_artifact_id: str | None = None
    thesis: str | None = None
    hard_constraint: str = HARD_CONSTRAINT_NONE
    key_risks: tuple[str, ...] = ()

    @classmethod
    def from_proposal(cls, proposal: Mapping[str, Any], *, model_artifact_id: str | None = None) -> "ThesisView | None":
        """저장된 종목 의견 하나. 필요한 값이 하나라도 없거나 논지 필드가 계약 밖이면 논지가 없는 것으로 본다."""
        values = [finite_float(proposal.get(name)) for name in ("expected_excess_return", "probability_up", "confidence")]
        if not proposal.get("ticker") or not proposal.get("as_of_at") or not proposal.get("signal"):
            return None
        if any(value is None for value in values):
            return None
        thesis = proposal.get("thesis")
        hard_constraint = str(proposal.get("hard_constraint") or HARD_CONSTRAINT_NONE)
        if (thesis is not None and thesis not in THESES) or hard_constraint not in HARD_CONSTRAINTS:
            return None
        return cls(str(proposal["ticker"]).upper(), parse_datetime(str(proposal["as_of_at"])).astimezone(timezone.utc),
                   str(proposal["signal"]), float(values[0]), float(values[1]), float(values[2]), model_artifact_id,
                   thesis, hard_constraint, tuple(str(item) for item in proposal.get("key_risks") or ()))

    @property
    def thesis_state(self) -> str:
        """hard constraint가 가장 강하고, 명시 논지가 다음이다. 긍정 논지도 수치가 상승을 말해야 긍정이다."""
        if self.hard_constraint in {HARD_CONSTRAINT_FORCE_EXIT, HARD_CONSTRAINT_EXCLUDE}:
            return THESIS_BROKEN
        if self.hard_constraint == HARD_CONSTRAINT_BLOCK_NEW_BUY:
            return THESIS_NEGATIVE
        bearish = self.expected_excess_return < 0.0 and self.probability_up < 0.5
        bullish = self.expected_excess_return > 0.0 and self.probability_up > 0.5
        if self.thesis is not None:
            if self.thesis == THESIS_NEGATIVE:
                return THESIS_NEGATIVE
            return THESIS_POSITIVE if self.thesis == THESIS_POSITIVE and bullish else THESIS_NEUTRAL
        # 옛 기록: 행동 단어와 수치가 엇갈리면 수치를 따른다 — `exit`라고 써도 하락을 말하지 않으면 청산하지 않는다.
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


def _direction(value: float | None) -> int:
    if value is None or abs(value) <= 1e-12:
        return 0
    return 1 if value > 0 else -1


def source_agreement(expected: float, *, directions: Sequence[int]) -> float:
    """방향을 말한 근거 중 최종 기대수익과 같은 방향인 비율. 방향을 말한 근거가 없으면 1이다."""
    stated = [direction for direction in directions if direction != 0]
    final = _direction(expected)
    if not stated or final == 0:
        return 1.0
    return sum(1 for direction in stated if direction == final) / len(stated)


def expected_return_signals(
    scores: Mapping[str, Any],
    *,
    sigma_by_symbol: Mapping[str, float],
    held_symbols: Sequence[str],
    views: Mapping[str, ThesisView | None],
    as_of_at: datetime,
    policy: AlphaPolicy,
    ml_expected_returns: Mapping[str, float] | None = None,
    ml_confidence: float = 0.0,
) -> AlphaPlan:
    """후보·보유 종목의 기대초과수익·confidence·제약을 만든다. 변동성을 모르는 종목은 신호를 만들지 않는다."""
    held = {str(symbol).upper() for symbol in held_symbols}
    z_by_symbol = _z_scores(scores)
    ml_share = float(min(1.0, max(0.0, ml_confidence))) if policy.use_ml else 0.0
    predictions = {str(key).upper(): float(value) for key, value in (ml_expected_returns or {}).items()} if ml_share else {}
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
        prior = policy.information_coefficient * sigma * z
        ml_value = predictions.get(symbol)
        ml_return = max(-sigma, min(sigma, ml_value)) if ml_value is not None else None
        expected = prior if ml_return is None else (1.0 - ml_share) * prior + ml_share * ml_return
        constraint: str | None = None
        reason = "FACTOR_ML_BASE" if ml_return is not None else "FACTOR_BASE"
        if not score.passes_quality_gate:
            expected = min(0.0, expected)
            constraint = CONSTRAINT_BLOCK_INCREASE
            reason = "FACTOR_BREAKDOWN"
        view = views.get(symbol) if policy.use_thesis else None
        valid = is_valid_view(view, as_of_at=as_of_at, policy=policy)
        state = view.thesis_state if valid else None
        thesis_direction = {THESIS_POSITIVE: 1, THESIS_NEGATIVE: -1, THESIS_BROKEN: -1}.get(state, 0)
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
            reason = "THESIS_CONFIRMED_TILT" if reason in {"FACTOR_BASE", "FACTOR_ML_BASE"} else reason
        elif not valid and symbol not in held and policy.require_verified_entry and policy.use_thesis:
            constraint = CONSTRAINT_BLOCK_INCREASE
            expected = min(expected, 0.0)
            reason = "UNVERIFIED_ENTRY_BLOCKED"
        confidence = source_agreement(expected, directions=(_direction(prior), _direction(ml_return), thesis_direction))
        signals.append(ExpectedReturnSignal(
            symbol=symbol, expected_return=float(expected), confidence=float(confidence), risk_score=0.5,
            horizon_days=SIGNAL_HORIZON_DAYS, source="alpha", timestamp=timestamp,
            version=policy.version, constraint=constraint,
        ))
        reasons[symbol] = reason
        detail[symbol] = {
            "composite": round(float(score.composite), 6), "z": round(z, 4), "sigma": round(sigma, 6),
            "factor_prior": round(prior, 6),
            "ml_expected_excess_return": round(ml_return, 6) if ml_return is not None else None,
            "ml_share": round(ml_share, 6) if ml_return is not None else 0.0,
            "expected_excess_return": round(float(expected), 6), "confidence": round(confidence, 6),
            "constraint": constraint, "reason": reason,
            "thesis_state": state, "thesis_at": view.as_of_at.isoformat() if valid else None,
            "hard_constraint": view.hard_constraint if valid else None,
            "key_risks": list(view.key_risks) if valid else [],
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
    "source_agreement",
]
