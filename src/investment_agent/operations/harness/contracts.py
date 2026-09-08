"""운영 하네스 job·stage의 실행 계약."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from threading import Event
from typing import Any, Callable, Mapping

from investment_agent.platform.serialization import canonical_json

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_OUTCOMES = {"succeeded", "waiting", "skipped"}


class HarnessMode(str, Enum):
    ANALYSIS_ONLY = "analysis_only"
    APPROVAL_WORKFLOW = "approval_workflow"


@dataclass(frozen=True)
class StageOutcome:
    """handler가 상태머신에 돌려주는 제한된 결과다."""

    status: str
    metadata: dict[str, Any] = field(default_factory=dict)
    resume_after_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.status not in _OUTCOMES:
            raise ValueError(f"invalid stage outcome: {self.status}")
        if not isinstance(self.metadata, dict):
            raise ValueError("stage metadata must be a mapping")
        canonical_json(self.metadata)
        if self.status == "waiting":
            if self.resume_after_seconds is None:
                raise ValueError("waiting outcome requires resume_after_seconds")
            delay = float(self.resume_after_seconds)
            if not math.isfinite(delay) or delay <= 0.0:
                raise ValueError("resume_after_seconds must be finite and positive")
            object.__setattr__(self, "resume_after_seconds", delay)
        elif self.resume_after_seconds is not None:
            raise ValueError("only waiting outcome can define resume_after_seconds")

    @classmethod
    def succeeded(cls, metadata: Mapping[str, Any] | None = None) -> "StageOutcome":
        return cls("succeeded", dict(metadata or {}))

    @classmethod
    def skipped(cls, metadata: Mapping[str, Any] | None = None) -> "StageOutcome":
        return cls("skipped", dict(metadata or {}))

    @classmethod
    def waiting(
        cls,
        *,
        resume_after_seconds: float,
        metadata: Mapping[str, Any] | None = None,
    ) -> "StageOutcome":
        return cls("waiting", dict(metadata or {}), resume_after_seconds)


@dataclass(frozen=True)
class StageContext:
    """재시도해도 유지되는 멱등키와 앞 단계 결과, 종료 신호다."""

    job_id: str
    run_id: str
    stage_id: str
    attempt: int
    idempotency_key: str
    now: datetime
    stop_event: Event
    prior_metadata: dict[str, Any]
    completed_metadata: dict[str, dict[str, Any]]


StageHandler = Callable[[StageContext], StageOutcome]


@dataclass(frozen=True)
class StageDefinition:
    stage_id: str
    handler: StageHandler
    trading_sensitive: bool = False
    approval_workflow_only: bool = False
    max_attempts: int = 3
    retry_delay_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(self.stage_id):
            raise ValueError(f"invalid stage_id: {self.stage_id}")
        if not callable(self.handler):
            raise ValueError("stage handler must be callable")
        if self.trading_sensitive and not self.approval_workflow_only:
            object.__setattr__(self, "approval_workflow_only", True)
        if not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        delay = float(self.retry_delay_seconds)
        if not math.isfinite(delay) or delay <= 0.0:
            raise ValueError("retry_delay_seconds must be finite and positive")
        object.__setattr__(self, "retry_delay_seconds", delay)


@dataclass(frozen=True)
class JobDefinition:
    job_id: str
    stages: tuple[StageDefinition, ...]
    interval_seconds: float
    stale_after_seconds: float = 180.0
    kill_switch_env: str | None = None

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(self.job_id):
            raise ValueError(f"invalid job_id: {self.job_id}")
        if not self.stages:
            raise ValueError("job must contain at least one stage")
        stage_ids = [item.stage_id for item in self.stages]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("job stage ids must be unique")
        for name in ("interval_seconds", "stale_after_seconds"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
            object.__setattr__(self, name, value)
        if self.kill_switch_env is not None and not re.fullmatch(
            r"[A-Z][A-Z0-9_]{0,127}", self.kill_switch_env
        ):
            raise ValueError("kill_switch_env must be an environment variable name")
