"""LLM 호출의 토큰·지연 계측.

## 왜 client가 누적하는가

`complete_json()`의 반환값에 계측을 실으면 호출부 8곳과 테스트 fake 전부가 바뀐다.
계측은 판단의 일부가 아니라 그 판단을 만드는 데 든 비용이므로, **client 인스턴스가
자기가 쓴 자원을 들고 있게** 한다. client는 종목 하나의 분석 동안만 살아 있어
(`analysis._attempt_case`가 종목마다 새로 만든다) 누적값이 곧 종목당 합계다.

## provider가 usage를 주지 않을 수 있다

OpenAI 호환 엔드포인트는 대부분 `usage`를 주지만 계약은 아니다. 없으면 토큰을 0으로
적지 않고 `None`으로 두고 `requests_without_usage`로 센다 — 0으로 적으면 "토큰을 안 썼다"와
"모르겠다"가 같은 값이 되어, 나중에 비용을 계산할 때 조용히 과소 추정한다.

## 이 값으로 무엇을 하나

`INVESTMENT_DECISION_ENGINE_DESIGN.md` §50이 요구하는 계측 항목의 입력이다. 이것이 쌓이기
전에는 어떤 provider 비교에도 비용·지연 수치를 적지 않는다(§49, `SYSTEM_UPGRADE_MASTER.md` §16.12).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


def _positive_int(value: Any) -> int | None:
    """provider가 준 토큰 수. 정수가 아니거나 음수면 모르는 것으로 둔다."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


@dataclass(frozen=True)
class CallUsage:
    """LLM 호출 한 건의 계측."""

    task_name: str
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        if not str(self.task_name).strip():
            raise ValueError("task_name is required")
        latency = float(self.latency_ms)
        if not math.isfinite(latency) or latency < 0:
            raise ValueError("latency_ms must be finite and non-negative")
        object.__setattr__(self, "latency_ms", latency)

    @property
    def has_token_counts(self) -> bool:
        return self.input_tokens is not None and self.output_tokens is not None

    @classmethod
    def from_response(cls, *, task_name: str, latency_ms: float, body: Any) -> "CallUsage":
        """provider 응답 본문에서 usage를 꺼낸다. 없으면 토큰은 None이다."""
        usage = body.get("usage") if isinstance(body, Mapping) else None
        if not isinstance(usage, Mapping):
            return cls(task_name=task_name, latency_ms=latency_ms)
        return cls(
            task_name=task_name,
            latency_ms=latency_ms,
            input_tokens=_positive_int(usage.get("prompt_tokens")),
            output_tokens=_positive_int(usage.get("completion_tokens")),
        )


def _percentile(values: Sequence[float], fraction: float) -> float:
    """가장 가까운 순위(nearest-rank) 백분위. 표본이 적어도 실재하는 값 하나를 돌려준다."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return float(ordered[index])


@dataclass
class UsageLedger:
    """한 client 인스턴스가 쓴 LLM 자원의 합계. 종목 하나의 분석 단위다."""

    calls: list[CallUsage] = field(default_factory=list)

    def record(self, call: CallUsage) -> None:
        self.calls.append(call)

    @property
    def requests(self) -> int:
        return len(self.calls)

    @property
    def requests_without_usage(self) -> int:
        """provider가 토큰 수를 주지 않은 호출 수. 합계를 얼마나 믿을지 말해 준다."""
        return sum(1 for call in self.calls if not call.has_token_counts)

    @property
    def input_tokens(self) -> int:
        return sum(call.input_tokens or 0 for call in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(call.output_tokens or 0 for call in self.calls)

    @property
    def latency_ms_total(self) -> float:
        return math.fsum(call.latency_ms for call in self.calls)

    def latency_ms_percentile(self, fraction: float) -> float:
        if not 0.0 < fraction <= 1.0:
            raise ValueError("percentile fraction must be in (0, 1]")
        return _percentile([call.latency_ms for call in self.calls], fraction)

    @property
    def is_complete(self) -> bool:
        """모든 호출이 토큰 수를 갖고 있는가. 거짓이면 토큰 합계는 하한이다."""
        return bool(self.calls) and self.requests_without_usage == 0

    def to_metadata(self) -> dict[str, Any]:
        """로그·기록용 요약. 토큰 합계가 불완전하면 그 사실을 함께 적는다."""
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tokens_are_complete": self.is_complete,
            "requests_without_usage": self.requests_without_usage,
            "latency_ms_total": round(self.latency_ms_total, 1),
            "latency_ms_p50": round(self.latency_ms_percentile(0.50), 1),
            "latency_ms_p95": round(self.latency_ms_percentile(0.95), 1),
            "latency_ms_max": round(self.latency_ms_percentile(1.0), 1),
            "by_task": {
                task: count
                for task, count in sorted(self._counts_by_task().items())
            },
        }

    def _counts_by_task(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for call in self.calls:
            counts[call.task_name] = counts.get(call.task_name, 0) + 1
        return counts


__all__ = ["CallUsage", "UsageLedger"]
