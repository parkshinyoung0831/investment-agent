"""전역 거래·job별 kill switch 해석."""
from __future__ import annotations

import re
from typing import Mapping

_ON = {"1", "on", "true", "yes"}
_OFF = {"0", "off", "false", "no"}


def _switch(value: str | None, *, default_on: bool) -> bool:
    if value is None or not value.strip():
        return default_on
    normalized = value.strip().lower()
    if normalized in _ON:
        return True
    if normalized in _OFF:
        return False
    return True


def default_job_kill_env(job_id: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", job_id.upper()).strip("_")
    return f"HARNESS_JOB_{normalized}_KILL_SWITCH"


class KillSwitches:
    """알 수 없는 값은 안전하게 ON으로 해석한다."""

    def __init__(self, environ: Mapping[str, str]):
        self.environ = environ

    @property
    def trading_blocked(self) -> bool:
        return _switch(self.environ.get("TRADING_KILL_SWITCH"), default_on=True)

    def job_blocked(self, job_id: str, explicit_env: str | None = None) -> bool:
        name = explicit_env or default_job_kill_env(job_id)
        return _switch(self.environ.get(name), default_on=False)
