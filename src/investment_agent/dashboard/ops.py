"""운영 하네스 상태를 변경 없이 읽어 Dashboard 표시 계약으로 투영한다."""

from __future__ import annotations

import errno
import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from investment_agent.dashboard.calculations import inspect_harness_state
from investment_agent.platform.cache import cache_data
from investment_agent.reporting.models import DataResult, public_exception_message


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HARNESS_STATE = ROOT / "artifacts" / "ops" / "investment_harness" / "state.json"
LOCAL_SOURCE_HARNESS = "로컬 읽기 · investment harness state.json"


def _harness_stale_seconds() -> float:
    try:
        stale_after = float(os.environ.get("DASHBOARD_HARNESS_STALE_SECONDS", "180"))
    except ValueError:
        stale_after = 180.0
    return min(max(stale_after, 30.0), 86_400.0)


def _pid_exists_readonly(process_id: int) -> bool:
    """프로세스를 변경하지 않고 PID 생존 여부만 확인한다."""
    if process_id <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        open_process.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        get_exit_code = kernel32.GetExitCodeProcess
        get_exit_code.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        get_exit_code.restype = wintypes.BOOL

        handle = open_process(process_query_limited_information, False, process_id)
        if not handle:
            error_code = ctypes.get_last_error()
            if error_code in {87, 1168}:
                return False
            raise OSError(error_code, "PID 조회 권한 또는 OS 상태를 확인할 수 없습니다.")
        try:
            exit_code = wintypes.DWORD()
            if not get_exit_code(handle, ctypes.byref(exit_code)):
                error_code = ctypes.get_last_error()
                raise OSError(error_code, "프로세스 종료 상태를 확인할 수 없습니다.")
            return exit_code.value == still_active
        finally:
            close_handle(handle)

    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        raise
    except OSError as error:
        if error.errno == errno.ESRCH:
            return False
        raise
    return True


def _harness_health(state: Mapping[str, Any]) -> dict[str, Any]:
    health = inspect_harness_state(
        state,
        pid_exists=_pid_exists_readonly,
        process_stale_after_seconds=_harness_stale_seconds(),
    )
    status = str(health.get("process_status") or "unknown")
    labels = {
        "running": "실행 중",
        "stopped": "정상 종료",
        "pid_not_alive": "프로세스 종료",
        "never_started": "시작 기록 없음",
        "heartbeat_missing": "하트비트 없음",
        "stale": "하트비트 지연",
        "clock_skew": "시계 불일치",
        "state_missing": "상태 없음",
    }
    return {
        **health,
        "status": status,
        "label": labels.get(status, "상태 확인 불가"),
        "recorded_process_id": health.get("process_id"),
        "stale_after_seconds": _harness_stale_seconds(),
    }


@cache_data(ttl="3s", max_entries=8)
def read_harness_state(path: str | Path = DEFAULT_HARNESS_STATE) -> DataResult:
    """하네스 JSON을 변경하지 않고 PID·heartbeat·잡 상태를 계산한다."""
    source = LOCAL_SOURCE_HARNESS
    state_path = Path(path).expanduser()
    try:
        if not state_path.exists():
            return DataResult.empty(source=source, message="하네스 상태 파일이 없습니다.")
        if not state_path.is_file():
            return DataResult.error(source=source, message="하네스 상태 경로가 파일이 아닙니다.")
        metadata = state_path.stat()
        if metadata.st_size > 2_000_000:
            return DataResult.error(source=source, message="하네스 상태 파일이 허용 크기를 넘었습니다.")
        value = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return DataResult.error(source=source, message="하네스 상태 JSON이 객체가 아닙니다.")
        payload = {
            **value,
            "health": _harness_health(value),
            "state_file_modified_at": datetime.fromtimestamp(
                metadata.st_mtime, tz=timezone.utc
            ).isoformat(),
        }
        observed_at = value.get("process_heartbeat_at") or payload["state_file_modified_at"]
        return DataResult.ok(value=payload, source=source, observed_at=observed_at)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return DataResult.error(
            source=source,
            message=public_exception_message("하네스 상태 파일을 읽지 못했습니다.", error),
        )


__all__ = ["DEFAULT_HARNESS_STATE", "read_harness_state"]
