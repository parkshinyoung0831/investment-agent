"""정비 보류(maintenance hold) — 하네스가 기동 자체를 거부하게 만드는 sentinel.

`EXECUTION_LOCKDOWN`은 이미 뜬 하네스가 **실주문**을 내지 못하게 막는다. 코드를
고치는 동안 필요한 건 그 앞 단계다 — 배치 파일을 잘못 눌렀든, 메뉴에서 잘못 골랐든,
**하네스가 아예 뜨지 않아야** 한다. 킬스위치는 프로세스를 띄운 뒤 주문만 막으므로
그동안 분석 잡이 돌고 상태 파일이 갱신돼 작업 중인 코드와 섞인다.

`EXECUTION_LOCKDOWN`과 파일을 나눈 이유: 정비가 끝나면 이건 지우지만, 거래 잠금은
사람이 확인 문구를 넣어 따로 풀어야 한다. 한 파일로 합치면 정비 해제가 거래 잠금까지
같이 푸는 사고가 난다.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Mapping

from investment_agent.platform.serialization import canonical_json
from investment_agent.operations.harness.state import utc_iso

from investment_agent.operations.paths import (
    HARNESS_STATE_DIR as _DEFAULT_STATE_DIR,
)
MAINTENANCE_SENTINEL_FILENAME = "MAINTENANCE_HOLD"


def get_maintenance_path(state_dir: Path | str | None = None) -> Path:
    base = Path(state_dir).expanduser().resolve() if state_dir is not None else _DEFAULT_STATE_DIR
    return base / MAINTENANCE_SENTINEL_FILENAME


def is_maintenance_held(state_dir: Path | str | None = None) -> bool:
    """정비 보류 sentinel이 있으면 하네스는 기동하지 않는다."""
    path = get_maintenance_path(state_dir)
    return path.exists() and path.is_file()


def read_maintenance_hold(state_dir: Path | str | None = None) -> dict[str, Any] | None:
    path = get_maintenance_path(state_dir)
    if not path.exists() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"raw": data}
    except Exception:  # noqa: BLE001 - 깨진 sentinel도 '보류 중'으로 읽는 편이 안전하다
        return {"error": "corrupted_maintenance_file"}


def set_maintenance_hold(
    *,
    state_dir: Path | str | None = None,
    reason: str = "manual",
    details: Mapping[str, Any] | None = None,
) -> Path:
    """정비 보류를 건다. 임시 파일에 쓴 뒤 rename해 반쯤 쓰인 sentinel이 남지 않게 한다."""
    path = get_maintenance_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "hold_id": f"hold_{uuid.uuid4().hex[:16]}",
        "reason": reason,
        "held_at": utc_iso(),
        "pid": os.getpid(),
        "details": dict(details or {}),
    }
    tmp_path = path.parent / f".{MAINTENANCE_SENTINEL_FILENAME}.tmp.{os.getpid()}"
    tmp_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


def clear_maintenance_hold(state_dir: Path | str | None = None) -> bool:
    """정비 보류를 푼다. 거래 킬스위치와 durable lockdown은 건드리지 않는다."""
    path = get_maintenance_path(state_dir)
    if path.exists():
        path.unlink()
        return True
    return False


__all__ = [
    "MAINTENANCE_SENTINEL_FILENAME",
    "clear_maintenance_hold",
    "get_maintenance_path",
    "is_maintenance_held",
    "read_maintenance_hold",
    "set_maintenance_hold",
]
