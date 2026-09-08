"""판단·실행 전체가 공유하는 어휘.

## 세 축은 서로 독립이다

한 낱말로 뭉뚱그리면 조용히 틀린다. 실제로 `mode`라는 이름 하나에 세 가지가 섞여
있었고, 그때 "backtest 결과인데 live로 기록된" 행이 만들어질 수 있었다.

* **`stage`** — 모델 수명주기의 어디인가.
  `shadow → backtest → out_of_sample → walk_forward → paper → live`
* **`execution_mode`** — 주문이 어디로 가는가. `paper` 또는 `live`.
* **`source_kind`** — 입력이 어디서 왔는가. `live_shadow`(실시간 관측) 또는
  `historical_replay`(과거 재생).

셋이 독립인 이유: `stage='live'`인 모델도 `execution_mode='paper'`로 돌 수 있고,
그때 입력은 `live_shadow`다. 반대로 `stage='backtest'`는 언제나
`source_kind='historical_replay'`다 — 그것만이 유일한 종속 관계다.

## 사람이 켜는 것을 코드가 켜지 않는다

`execution_mode='live'`로 올라가는 것은 **사람의 결정**이다. 이 모듈은 값을 검사만
하고, 어디에서도 실거래 플래그를 바꾸지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STAGES = ("shadow", "backtest", "out_of_sample", "walk_forward", "paper", "live")
EXECUTION_MODES = ("paper", "live")
SOURCE_KINDS = ("live_shadow", "historical_replay")

# 과거를 재생하는 stage. 이 단계에서 실시간 입력을 쓰면 그것은 backtest가 아니다.
REPLAY_ONLY_STAGES = ("backtest", "out_of_sample", "walk_forward")

# 판단 지평. 평가 표(`decision_evaluations`)가 받는 값과 같아야 한다.
EVALUATION_HORIZONS = (1, 5, 20, 60)


class ContractViolation(ValueError):
    """세 축의 조합이 말이 되지 않는다."""


@dataclass(frozen=True)
class RunContext:
    """한 판단 회차가 서 있는 자리. 기록되는 모든 행이 이 셋을 갖는다."""

    stage: str
    execution_mode: str
    source_kind: str

    def __post_init__(self) -> None:
        if self.stage not in STAGES:
            raise ContractViolation(f"unknown stage: {self.stage!r}")
        if self.execution_mode not in EXECUTION_MODES:
            raise ContractViolation(f"unknown execution_mode: {self.execution_mode!r}")
        if self.source_kind not in SOURCE_KINDS:
            raise ContractViolation(f"unknown source_kind: {self.source_kind!r}")
        if self.stage in REPLAY_ONLY_STAGES and self.source_kind != "historical_replay":
            # 과거 검증에 실시간 입력을 섞으면 그 성적은 재현되지 않는다.
            raise ContractViolation(
                f"stage {self.stage!r} must replay history, not {self.source_kind!r}"
            )
        if self.execution_mode == "live" and self.stage != "live":
            # 아직 승격되지 않은 모델의 주문이 실계좌로 나가는 길을 막는다.
            raise ContractViolation(
                f"execution_mode 'live' needs stage 'live', not {self.stage!r}"
            )

    @property
    def is_live_money(self) -> bool:
        """실제 돈이 움직이는가. 안전 점검이 보는 유일한 값이다."""
        return self.execution_mode == "live"

    def as_row(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "execution_mode": self.execution_mode,
            "source_kind": self.source_kind,
        }


def shadow_context() -> RunContext:
    """기본값. 판단만 하고 주문은 종이로 간다."""
    return RunContext(stage="shadow", execution_mode="paper", source_kind="live_shadow")


def replay_context(stage: str = "backtest") -> RunContext:
    return RunContext(stage=stage, execution_mode="paper", source_kind="historical_replay")


__all__ = [
    "EVALUATION_HORIZONS",
    "EXECUTION_MODES",
    "REPLAY_ONLY_STAGES",
    "SOURCE_KINDS",
    "STAGES",
    "ContractViolation",
    "RunContext",
    "replay_context",
    "shadow_context",
]
