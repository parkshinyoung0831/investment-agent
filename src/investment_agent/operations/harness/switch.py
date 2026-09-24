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
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from investment_agent.operations.harness.emergency import is_execution_locked_down
from investment_agent.operations.harness.maintenance import is_maintenance_held, read_maintenance_hold
from investment_agent.operations.harness.state import JsonStateStore, utc_iso
from investment_agent.platform.trading_switch import KILL_SWITCH_FLAG, LIVE_FLAG, kill_switch_on, live_enabled

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
    mode: str | None  # 실제 기동 모드(state.json에 적은 값). 한 번도 안 떴으면 None(감사 OP2-07)
    mode_would_be: str  # 지금 `.env`로 기동하면 어느 모드가 될지 — 실제 모드의 근거가 아니다
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
    os_pids = _find_running_harness_pids()
    # 기록된 PID가 살아 있다는 것만으로는 하네스가 아니다. 재부팅 뒤 같은 번호를 다른 프로그램이 받는다.
    recorded_alive = pid is not None and pid in os_pids
    is_running = recorded_alive or bool(os_pids)
    effective_pid = pid if recorded_alive else (os_pids[0] if os_pids else None)

    jobs_summary: dict[str, str] = {}
    active_count = 0
    for j_id, job in state.jobs.items():
        jobs_summary[j_id] = f"{job.status} (stage={job.stage or '-'})"
        if job.active:
            active_count += 1

    trading_kill = "on" if kill_switch_on(env_map.get(KILL_SWITCH_FLAG)) else "off"
    toss_live = live_enabled(env_map.get(LIVE_FLAG))
    ai_mode = env_map.get("AI_INVESTOR_MODE", "shadow").strip()

    return HarnessStatusInfo(
        is_running=is_running,
        process_id=effective_pid,
        started_at=state.process_started_at,
        heartbeat_at=state.process_heartbeat_at,
        stopped_cleanly=state.stopped_cleanly,
        mode=state.mode,
        mode_would_be="approval_workflow" if not trading_kill.startswith("on") and toss_live else "analysis_only",
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
    mode: str = "approval_workflow",
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
        "-u",
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
            s_dir.mkdir(parents=True, exist_ok=True)
            log_path = s_dir / "service.log"
            kwargs: dict[str, Any] = {
                "cwd": str(r_dir),
                "stdin": subprocess.DEVNULL,
                "close_fds": True,
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
            else:
                kwargs["start_new_session"] = True
            # 부모가 끝나도 자식과 그 하위 잡의 진단을 로컬에 남긴다.
            with log_path.open("ab", buffering=0) as output:
                proc = subprocess.Popen(cmd, stdout=output, stderr=output, **kwargs)
            deadline = time.monotonic() + 10.0
            store = JsonStateStore(s_dir / "state.json")
            while True:
                return_code = proc.poll()
                if return_code is not None:
                    return {
                        "success": False,
                        "error": "startup_failed",
                        "return_code": return_code,
                        "log_path": str(log_path),
                        "message": f"하네스가 기동 중 종료되었습니다 (exit={return_code}). 로그: {log_path}",
                    }
                state = store.load()
                # Windows venv launcher는 별도 Python worker를 띄울 수 있다.
                # 기존 checkpoint는 거부하고 이번 기동의 살아 있는 worker만 인정한다.
                is_new_worker = (
                    state.process_started_at is not None
                    and state.process_started_at != status.started_at
                    and _is_pid_alive(state.process_id)
                )
                if (state.process_id == proc.pid or is_new_worker) and state.process_heartbeat_at and not state.stopped_cleanly:
                    break
                if time.monotonic() >= deadline:
                    if sys.platform == "win32":
                        _terminate_pid(proc.pid)
                    else:
                        proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                    return {
                        "success": False,
                        "error": "startup_timeout",
                        "log_path": str(log_path),
                        "message": f"하네스 기동 확인 시간이 초과되어 종료했습니다. 로그: {log_path}",
                    }
                time.sleep(0.1)
            return {
                "success": True,
                "mode": mode,
                "process_id": state.process_id,
                "background": True,
                "log_path": str(log_path),
                "message": f"하네스가 백그라운드에서 시작되었습니다 (PID: {state.process_id}, 모드: {mode}).",
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

    # 명령줄로 하네스임을 확인한 프로세스만 끈다. 상태 파일의 PID는 재부팅 뒤 다른 프로그램의 번호일 수
    # 있어서, 그 번호에 `taskkill /T`를 보내면 무관한 프로그램과 그 자식까지 강제 종료한다.
    harness_pids = set(_find_running_harness_pids())
    target_pids = set(harness_pids)
    stale_recorded_pid = (
        state.process_id if state.process_id is not None and state.process_id not in harness_pids else None
    )

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
        "stale_recorded_pid": stale_recorded_pid,
        "state_updated": True,
        "timestamp": now_iso,
        "message": "하네스가 안전하게 완전 정지되었습니다." if success else "일부 프로세스 정지에 실패했습니다.",
    }


# 주문을 **허용하는 방향**으로 게이트를 바꿀 때만 요구하는 확인 문구.
# 막는 방향(킬스위치 on · 실매매 false)은 안전 방향이므로 그대로 허용한다 —
# 급할 때 문구를 몰라서 끄지 못하는 것이 더 나쁘다.
# 문구를 요구하는 곳은 진입점이 아니라 **이 setter**다. 진입점에 두면 새 진입점이
# 생길 때마다 빠뜨릴 수 있고, CLAUDE.md의 첫 "하지 말 것"이 바로 이 게이트다.
ALLOW_ORDERS_CONFIRMATION = "ALLOW_TRADING_ORDERS"
ENABLE_LIVE_CONFIRMATION = "ENABLE_TOSS_LIVE"


def set_kill_switch(
    value: str, root_dir: Path | str | None = None, *, confirm: str | None = None,
) -> dict[str, Any]:
    """TRADING_KILL_SWITCH 환경변수 값을 on/off 로 설정한다.

    `off`(= 신규 주문 허용)는 `confirm=ALLOW_ORDERS_CONFIRMATION`이 있어야 한다.
    """
    normalized = "on" if value.strip().lower() in {"1", "on", "true", "yes"} else "off"
    if normalized == "off" and confirm != ALLOW_ORDERS_CONFIRMATION:
        return {
            "success": False,
            "changed": False,
            "trading_kill_switch": normalized,
            "message": (
                "거절: 신규 주문을 허용하는 변경입니다. 확인 문구가 필요합니다 — "
                f"--confirm {ALLOW_ORDERS_CONFIRMATION}"
            ),
        }
    success = update_env_variable("TRADING_KILL_SWITCH", normalized, root_dir=root_dir)
    return {
        "success": success,
        "changed": success,
        "trading_kill_switch": normalized,
        "message": f"TRADING_KILL_SWITCH가 '{normalized}'으로 설정되었습니다.",
    }


def set_live_enabled(
    enabled: bool, root_dir: Path | str | None = None, *, confirm: str | None = None,
) -> dict[str, Any]:
    """TOSS_LIVE_ENABLED 환경변수 값을 true/false 로 설정한다.

    `true`(= 실매매 연동)는 `confirm=ENABLE_LIVE_CONFIRMATION`이 있어야 한다.
    """
    if enabled and confirm != ENABLE_LIVE_CONFIRMATION:
        return {
            "success": False,
            "changed": False,
            "toss_live_enabled": True,
            "message": (
                "거절: 실매매를 켜는 변경입니다. 확인 문구가 필요합니다 — "
                f"--confirm {ENABLE_LIVE_CONFIRMATION}"
            ),
        }
    val_str = "true" if enabled else "false"
    success = update_env_variable("TOSS_LIVE_ENABLED", val_str, root_dir=root_dir)
    return {
        "success": success,
        "changed": success,
        "toss_live_enabled": enabled,
        "message": f"TOSS_LIVE_ENABLED가 '{val_str}'으로 설정되었습니다.",
    }


__all__ = [
    "ALLOW_ORDERS_CONFIRMATION",
    "ENABLE_LIVE_CONFIRMATION",
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
