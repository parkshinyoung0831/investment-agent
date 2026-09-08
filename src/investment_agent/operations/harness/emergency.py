"""비상 긴급 정지(Emergency Stop) 및 하네스 영구 잠금(Durable Lockdown) 유틸리티."""
from __future__ import annotations

import json
import os
import signal
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping

from investment_agent.platform.serialization import canonical_json
from investment_agent.operations.harness.reporting import HarnessReporter
from investment_agent.operations.harness.state import JsonStateStore, utc_iso

from investment_agent.operations.paths import (
    HARNESS_STATE_DIR as _DEFAULT_STATE_DIR,
)
LOCKDOWN_SENTINEL_FILENAME = "EXECUTION_LOCKDOWN"
REARM_CONFIRMATION_PHRASE = "I_CONFIRM_REARM_TRADING"


def get_lockdown_path(state_dir: Path | str | None = None) -> Path:
    base = Path(state_dir).expanduser().resolve() if state_dir is not None else _DEFAULT_STATE_DIR
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
        "locked_at": utc_iso(),
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


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            success = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return bool(success and exit_code.value == STILL_ACTIVE)
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def _terminate_process(pid: int) -> bool:
    if not _is_process_alive(pid):
        return False
    try:
        if sys.platform == "win32":
            import subprocess
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
        else:
            os.kill(pid, signal.SIGTERM)
        import time
        for _ in range(20):
            if not _is_process_alive(pid):
                return True
            time.sleep(0.05)
        return not _is_process_alive(pid)
    except Exception:
        return False


def check_runtime_status(
    *,
    state_dir: Path,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """현재 실행 중인 하네스 데몬의 프로세스 생존 상태, durable lockdown, 킬스위치 상태를 조회한다."""
    env = environ if environ is not None else os.environ
    store = JsonStateStore(state_dir / "state.json")
    state = store.load()

    pid = state.process_id
    process_alive = _is_process_alive(pid) if pid is not None else False
    trading_kill_switch = env.get("TRADING_KILL_SWITCH", "on").strip().lower()
    lockdown_active = is_execution_locked_down(state_dir)
    lockdown_info = read_execution_lockdown(state_dir) if lockdown_active else None

    return {
        "process_id": pid,
        "process_alive": process_alive,
        "stopped_cleanly": state.stopped_cleanly,
        "stopped_at": state.stopped_at,
        "heartbeat_at": state.process_heartbeat_at,
        "trading_kill_switch": trading_kill_switch,
        "execution_lockdown": lockdown_active,
        "lockdown_info": lockdown_info,
        "active_jobs_count": sum(1 for j in state.jobs.values() if j.active),
    }


def emergency_stop(
    *,
    state_dir: Path,
    kill_process: bool = True,
    lockdown_env_file: bool = False,
    repository_root: Path | None = None,
    reporter: HarnessReporter | None = None,
) -> dict[str, Any]:
    """원자적 durable lockdown을 먼저 기록한 후 프로세스를 종료하고 상태를 갱신한다."""
    # 1. Atomic durable execution lockdown FIRST
    lockdown_file = set_execution_lockdown(
        state_dir=state_dir,
        reason="emergency_stop",
    )

    # 2. State transition
    store = JsonStateStore(state_dir / "state.json")
    state = store.load()
    pid = state.process_id
    now_iso = utc_iso()

    for job in state.jobs.values():
        if job.active:
            job.status = "paused"
            job.pause_reason = "emergency_lockdown"

    state.stopped_cleanly = False
    state.stopped_at = now_iso
    state.process_id = None
    store.save(state)

    # 3. Terminate process and verify termination
    process_killed = False
    if kill_process and pid is not None:
        if _is_process_alive(pid):
            process_killed = _terminate_process(pid)
        else:
            process_killed = True
    elif pid is None:
        process_killed = True

    # 4. Update .env if requested
    env_locked = False
    if lockdown_env_file:
        root = repository_root or state_dir.parents[2]
        env_path = root / ".env"
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")
            if "TRADING_KILL_SWITCH=" in content:
                import re
                new_content = re.sub(
                    r"^TRADING_KILL_SWITCH=.*$",
                    "TRADING_KILL_SWITCH=on",
                    content,
                    flags=re.MULTILINE,
                )
            else:
                new_content = content + "\nTRADING_KILL_SWITCH=on\n"
            env_path.write_text(new_content, encoding="utf-8")
            env_locked = True

    overall_success = lockdown_file.exists() and process_killed

    if reporter is not None:
        reporter.error(
            "emergency_stop_triggered",
            process_id=pid,
            process_killed=process_killed,
            env_locked=env_locked,
            lockdown_sentinel=str(lockdown_file),
            overall_success=overall_success,
        )

    return {
        "success": overall_success,
        "target_pid": pid,
        "process_killed": process_killed,
        "durable_lockdown_set": True,
        "lockdown_file": str(lockdown_file),
        "state_updated": True,
        "env_locked": env_locked,
        "timestamp": now_iso,
    }


__all__ = [
    "LOCKDOWN_SENTINEL_FILENAME",
    "REARM_CONFIRMATION_PHRASE",
    "check_runtime_status",
    "emergency_stop",
    "get_lockdown_path",
    "is_execution_locked_down",
    "read_execution_lockdown",
    "rearm_execution",
    "set_execution_lockdown",
]
