"""실주문을 즉시 차단하는 durable lockdown sentinel의 소유 경계."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Mapping

from investment_agent.platform.clock import to_utc_iso, utc_now
from investment_agent.platform.serialization import canonical_json
from investment_agent.platform.storage_paths import harness_state_dir


LOCKDOWN_SENTINEL_FILENAME = "EXECUTION_LOCKDOWN"
REARM_CONFIRMATION_PHRASE = "I_CONFIRM_REARM_TRADING"


def get_lockdown_path(state_dir: Path | str | None = None) -> Path:
    """sentinel 위치. 실주문 게이트는 인자 없이(정본 위치) 읽으므로 다른 폴더에 만든 sentinel은 게이트가 보지 못한다."""
    base = Path(state_dir).expanduser().resolve() if state_dir is not None else harness_state_dir()
    return base / LOCKDOWN_SENTINEL_FILENAME


def is_execution_locked_down(state_dir: Path | str | None = None) -> bool:
    """durable EXECUTION_LOCKDOWN sentinel 파일이 존재하는지 확인한다."""
    path = get_lockdown_path(state_dir)
    return path.exists() and path.is_file()


def read_execution_lockdown(state_dir: Path | str | None = None) -> dict[str, Any] | None:
    path = get_lockdown_path(state_dir)
    if not path.exists() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"raw": data}
    except Exception:
        return {"error": "corrupted_lockdown_file"}


def set_execution_lockdown(
    *,
    state_dir: Path | str | None = None,
    reason: str = "emergency_stop",
    details: Mapping[str, Any] | None = None,
) -> Path:
    """원자적으로 EXECUTION_LOCKDOWN sentinel 파일을 생성하여 모든 실주문 실행을 차단한다."""
    path = get_lockdown_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "lockdown_id": f"lockdown_{uuid.uuid4().hex[:16]}",
        "reason": reason,
        "locked_at": to_utc_iso(utc_now()),
        "pid": os.getpid(),
        "details": dict(details or {}),
    }
    tmp_path = path.parent / f".{LOCKDOWN_SENTINEL_FILENAME}.tmp.{os.getpid()}"
    tmp_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


def rearm_execution(
    *,
    state_dir: Path | str | None = None,
    confirmation: str,
) -> bool:
    """명시적 확인 문구를 검증한 후 durable lockdown sentinel을 안전하게 해제한다."""
    if confirmation != REARM_CONFIRMATION_PHRASE:
        raise ValueError(
            f"rearm confirmation mismatch; expected exact string: '{REARM_CONFIRMATION_PHRASE}'"
        )
    path = get_lockdown_path(state_dir)
    if path.exists():
        path.unlink()
        return True
    return False


__all__ = [
    "LOCKDOWN_SENTINEL_FILENAME",
    "REARM_CONFIRMATION_PHRASE",
    "get_lockdown_path",
    "is_execution_locked_down",
    "read_execution_lockdown",
    "rearm_execution",
    "set_execution_lockdown",
]
