"""투자 하네스 ON/OFF 스위치 및 런타임 제어 유틸리티.

하네스 프로세스의 시작, 안전 정지, 런타임 상태 진단,
.env 내의 킬스위치/실매매 플래그 변경을 단일 모듈에서 제어한다.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from investment_agent.operations.harness.emergency import is_execution_locked_down
from investment_agent.operations.harness.maintenance import is_maintenance_held, read_maintenance_hold
from investment_agent.operations.harness.state import JsonStateStore, utc_iso

from investment_agent.operations.paths import (
    HARNESS_STATE_DIR as _DEFAULT_STATE_DIR,
    REPOSITORY_ROOT as _ROOT,
)


@dataclass(frozen=True)
class HarnessStatusInfo:
    """하네스 종합 상태 정보 데이터클래스."""

    is_running: bool
    process_id: int | None
    started_at: str | None
    heartbeat_at: str | None
    stopped_cleanly: bool
    mode: str | None
    trading_kill_switch: str
    toss_live_enabled: bool
    ai_investor_mode: str
    execution_lockdown: bool
    maintenance_hold: bool
    maintenance_reason: str | None
    lock_file_exists: bool
    active_jobs_count: int
    jobs_summary: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_pid_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            process_query_info = 0x1000
            still_active = 259
            handle = ctypes.windll.kernel32.OpenProcess(process_query_info, False, pid)
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            success = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return bool(success and exit_code.value == still_active)
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def _find_running_harness_pids() -> list[int]:
    """OS 프로세스 목록에서 investment_harness 또는 approval_listener_service를 실행 중인 PID를 찾는다."""
    found: list[int] = []
    current_pid = os.getpid()
    if sys.platform == "win32":
        try:
            cmd = (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.Name -eq 'python.exe' -and "
                "($_.CommandLine -like '*investment_harness*' -or "
                "$_.CommandLine -like '*approval_listener_service*') } | "
                "Select-Object -ExpandProperty ProcessId"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in res.stdout.splitlines():
                val = line.strip()
                if val.isdigit():
                    pid = int(val)
                    if pid != current_pid and _is_pid_alive(pid):
                        found.append(pid)
        except Exception:
            pass
    return sorted(set(found))


def _terminate_pid(pid: int) -> bool:
    if not _is_pid_alive(pid):
        return True
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
        else:
            os.kill(pid, signal.SIGTERM)
        import time

        for _ in range(20):
            if not _is_pid_alive(pid):
                return True
            time.sleep(0.05)
        return not _is_pid_alive(pid)
    except Exception:
        return False


def parse_env_file(root_dir: Path | str | None = None) -> dict[str, str]:
    """`.env` 파일을 파싱하여 딕셔너리로 반환한다."""
    root = Path(root_dir).resolve() if root_dir is not None else _ROOT
    env_file = root / ".env"
    result: dict[str, str] = {}
    if env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" in stripped:
                    key, val = stripped.split("=", 1)
                    result[key.strip()] = val.strip().strip("'\"")
        except Exception:
            pass
    return result


def update_env_variable(key: str, value: str, root_dir: Path | str | None = None) -> bool:
    """`.env` 파일 내의 특정 환경변수를 안전하게 추가 또는 수정한다."""
    root = Path(root_dir).resolve() if root_dir is not None else _ROOT
    env_file = root / ".env"
    try:
        content = env_file.read_text(encoding="utf-8") if env_file.is_file() else ""
        pattern = rf"^{re.escape(key)}=.*$"
        new_line = f"{key}={value}"
        if re.search(pattern, content, flags=re.MULTILINE):
            updated = re.sub(pattern, new_line, content, flags=re.MULTILINE)
        else:
            updated = content + ("\n" if content and not content.endswith("\n") else "") + new_line + "\n"
        env_file.write_text(updated, encoding="utf-8")
        return True
    except Exception:
        return False


def get_harness_status(
    state_dir: Path | str | None = None,
    root_dir: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> HarnessStatusInfo:
    """하네스의 종합 런타임 상태를 조회한다."""
    s_dir = Path(state_dir).resolve() if state_dir is not None else _DEFAULT_STATE_DIR
    store = JsonStateStore(s_dir / "state.json")
    state = store.load()
    lock_file = s_dir / "harness.lock"

    env_map = parse_env_file(root_dir)
    if environ is not None:
        env_map.update(environ)

    pid = state.process_id
    recorded_alive = _is_pid_alive(pid) if pid is not None else False
    os_pids = _find_running_harness_pids()
    is_running = recorded_alive or bool(os_pids)
    effective_pid = pid if recorded_alive else (os_pids[0] if os_pids else None)

    jobs_summary: dict[str, str] = {}
    active_count = 0
    for j_id, job in state.jobs.items():
        jobs_summary[j_id] = f"{job.status} (stage={job.stage or '-'})"
        if job.active:
            active_count += 1

    trading_kill = env_map.get("TRADING_KILL_SWITCH", "on").strip().lower()
    toss_live = env_map.get("TOSS_LIVE_ENABLED", "false").strip().lower() == "true"
    ai_mode = env_map.get("AI_INVESTOR_MODE", "shadow").strip()

    return HarnessStatusInfo(
        is_running=is_running,
        process_id=effective_pid,
        started_at=state.process_started_at,
        heartbeat_at=state.process_heartbeat_at,
        stopped_cleanly=state.stopped_cleanly,
        mode="approval_workflow" if not trading_kill.startswith("on") and toss_live else "analysis_only",
        trading_kill_switch=trading_kill,
        toss_live_enabled=toss_live,
        ai_investor_mode=ai_mode,
        execution_lockdown=is_execution_locked_down(s_dir),
        maintenance_hold=is_maintenance_held(s_dir),
        maintenance_reason=(read_maintenance_hold(s_dir) or {}).get("reason"),
        lock_file_exists=lock_file.is_file(),
        active_jobs_count=active_count,
        jobs_summary=jobs_summary,
    )


def start_harness_service(
    *,
    mode: str = "analysis_only",
    state_dir: Path | str | None = None,
    root_dir: Path | str | None = None,
    background: bool = True,
    adaptive_schedule: bool = True,
) -> dict[str, Any]:
    """하네스 서비스를 시작한다 (ON)."""
    s_dir = Path(state_dir).resolve() if state_dir is not None else _DEFAULT_STATE_DIR
    r_dir = Path(root_dir).resolve() if root_dir is not None else _ROOT

    # 정비 보류가 걸려 있으면 어떤 경로로 불려도 뜨지 않는다. 킬스위치는 프로세스를
    # 띄운 뒤 주문만 막으므로, 코드를 고치는 동안에는 기동 자체를 막아야 한다.
    if is_maintenance_held(s_dir):
        hold = read_maintenance_hold(s_dir) or {}
        return {
            "success": False,
            "error": "maintenance_hold",
            "message": (
                "정비 보류 중이라 기동하지 않습니다 "
                f"(reason={hold.get('reason', '-')}, held_at={hold.get('held_at', '-')}). "
                "해제: python -m investment_agent.operations.commands.harness_switch --maintenance off"
            ),
            "maintenance": hold,
        }

    # 이미 실행 중인지 확인
    status = get_harness_status(state_dir=s_dir, root_dir=r_dir)
    if status.is_running:
        return {
            "success": False,
            "error": "already_running",
            "message": f"하네스가 이미 실행 중입니다 (PID: {status.process_id}).",
            "process_id": status.process_id,
        }

    # Python 실행 파일 결정
    venv_python = r_dir / ".venv" / "Scripts" / "python.exe"
    python_exe = str(venv_python) if venv_python.is_file() else sys.executable

    cmd = [
        python_exe,
        "-m",
        "investment_agent.operations.commands.investment_harness",
        "--serve",
        "--mode",
        mode,
        "--state-dir",
        str(s_dir),
    ]
    if adaptive_schedule:
        cmd.append("--adaptive-schedule")

    try:
        if background:
            if sys.platform == "win32":
                creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(r_dir),
                    creationflags=creation_flags,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    close_fds=True,
                )
            else:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(r_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
            return {
                "success": True,
                "mode": mode,
                "process_id": proc.pid,
                "background": True,
                "message": f"하네스가 백그라운드에서 시작되었습니다 (PID: {proc.pid}, 모드: {mode}).",
            }
        else:
            return {
                "success": True,
                "mode": mode,
                "command": cmd,
                "background": False,
                "message": "포그라운드 실행을 준비했습니다.",
            }
    except Exception as exc:
        return {
            "success": False,
            "error": type(exc).__name__,
            "message": f"하네스 시작 실패: {exc}",
        }


def stop_harness_service(
    *,
    state_dir: Path | str | None = None,
    root_dir: Path | str | None = None,
) -> dict[str, Any]:
    """실행 중인 하네스 프로세스 및 리스너를 완전히 정지하고 락을 정리한다 (OFF)."""
    s_dir = Path(state_dir).resolve() if state_dir is not None else _DEFAULT_STATE_DIR
    _ = root_dir  # 공개 호출 계약은 유지하되 stop 경로에는 working directory가 필요 없다.

    store = JsonStateStore(s_dir / "state.json")
    state = store.load()
    target_pids: set[int] = set()

    if state.process_id is not None:
        target_pids.add(state.process_id)

    # OS 프로세스 검색으로 추가 수집
    for pid in _find_running_harness_pids():
        target_pids.add(pid)

    killed_pids: list[int] = []
    failed_pids: list[int] = []

    for pid in target_pids:
        if _terminate_pid(pid):
            killed_pids.append(pid)
        else:
            failed_pids.append(pid)

    # 잔여 락 파일 제거
    lock_file = s_dir / "harness.lock"
    lock_removed = False
    if lock_file.exists():
        try:
            lock_file.unlink()
            lock_removed = True
        except Exception:
            pass

    # 상태 파일 정지 상태로 갱신
    now_iso = utc_iso()
    state.stopped_cleanly = True
    state.stopped_at = now_iso
    state.process_id = None
    for job in state.jobs.values():
        if job.active:
            job.status = "paused"
            job.pause_reason = "service_stopped"
    store.save(state)

    success = len(failed_pids) == 0
    return {
        "success": success,
        "target_pids": sorted(target_pids),
        "killed_pids": sorted(killed_pids),
        "failed_pids": sorted(failed_pids),
        "lock_removed": lock_removed,
        "state_updated": True,
        "timestamp": now_iso,
        "message": "하네스가 안전하게 완전 정지되었습니다." if success else "일부 프로세스 정지에 실패했습니다.",
    }


def set_kill_switch(value: str, root_dir: Path | str | None = None) -> dict[str, Any]:
    """TRADING_KILL_SWITCH 환경변수 값을 on/off 로 설정한다."""
    normalized = "on" if value.strip().lower() in {"1", "on", "true", "yes"} else "off"
    success = update_env_variable("TRADING_KILL_SWITCH", normalized, root_dir=root_dir)
    return {
        "success": success,
        "trading_kill_switch": normalized,
        "message": f"TRADING_KILL_SWITCH가 '{normalized}'으로 설정되었습니다.",
    }


def set_live_enabled(enabled: bool, root_dir: Path | str | None = None) -> dict[str, Any]:
    """TOSS_LIVE_ENABLED 환경변수 값을 true/false 로 설정한다."""
    val_str = "true" if enabled else "false"
    success = update_env_variable("TOSS_LIVE_ENABLED", val_str, root_dir=root_dir)
    return {
        "success": success,
        "toss_live_enabled": enabled,
        "message": f"TOSS_LIVE_ENABLED가 '{val_str}'으로 설정되었습니다.",
    }


__all__ = [
    "HarnessStatusInfo",
    "get_harness_status",
    "parse_env_file",
    "set_kill_switch",
    "set_live_enabled",
    "start_harness_service",
    "is_maintenance_held",
    "stop_harness_service",
    "update_env_variable",
]
