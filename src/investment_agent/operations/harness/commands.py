"""shell 없이 고정된 Python entry만 실행하는 하네스 command 경계."""
from __future__ import annotations

import math
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Mapping, Protocol, Sequence

_MODULE_RE = re.compile(r"^investment_agent(?:\.[a-z][a-z0-9_]*)+$")


class CommandExecutionError(RuntimeError):
    """인자나 자격증명 없이 command의 실패 유형만 상위 상태머신에 알린다."""


@dataclass(frozen=True)
class PythonModuleCommand:
    module: str
    arguments: tuple[str, ...] = ()
    timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if _MODULE_RE.fullmatch(self.module) is None:
            raise ValueError("command module must be a canonical investment_agent.* module")
        if not math.isfinite(float(self.timeout_seconds)) or self.timeout_seconds <= 0:
            raise ValueError("command timeout must be finite and positive")
        for value in self.arguments:
            if not isinstance(value, str) or "\x00" in value:
                raise ValueError("command arguments must be NUL-free strings")


@dataclass(frozen=True)
class CommandResult:
    module: str
    return_code: int
    elapsed_seconds: float


class ModuleCommandRunner(Protocol):
    def run(
        self,
        command: PythonModuleCommand,
        *,
        stop_event: Event,
    ) -> CommandResult: ...


class SubprocessModuleRunner:
    """argv 배열만 사용하고 stdout/stderr를 credential 보관소로 만들지 않는다."""

    def __init__(
        self,
        *,
        repository_root: Path | str,
        python_executable: Path | str | None = None,
        allowed_modules: Sequence[str],
        environ: Mapping[str, str] | None = None,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        monotonic: Callable[[], float] = time.monotonic,
        poll_seconds: float = 0.25,
    ) -> None:
        self.repository_root = Path(repository_root).expanduser().resolve()
        self.python_executable = str(
            Path(python_executable or sys.executable).expanduser().resolve()
        )
        self.allowed_modules = frozenset(allowed_modules)
        if not self.allowed_modules:
            raise ValueError("at least one command module must be allowed")
        for module in self.allowed_modules:
            if _MODULE_RE.fullmatch(module) is None:
                raise ValueError("allowed command module is invalid")
        if not math.isfinite(float(poll_seconds)) or poll_seconds <= 0:
            raise ValueError("poll_seconds must be finite and positive")
        if environ is None:
            env = dict(os.environ)
            env.setdefault("PYTHONUTF8", "1")
            env.setdefault("PYTHONIOENCODING", "utf-8")
            self.environ = env
        else:
            self.environ = dict(environ)
        self._popen = popen
        self._monotonic = monotonic
        self.poll_seconds = float(poll_seconds)

    @staticmethod
    def _stop_process(process: subprocess.Popen) -> None:
        """종료 요청은 자식에게 먼저 전달하고 짧게 기다린 뒤 강제 종료한다."""
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass

    def run(
        self,
        command: PythonModuleCommand,
        *,
        stop_event: Event,
    ) -> CommandResult:
        if command.module not in self.allowed_modules:
            raise CommandExecutionError("command module is not in the fixed allowlist")
        argv = [self.python_executable, "-m", command.module, *command.arguments]
        kwargs: dict = {
            "cwd": str(self.repository_root),
            "env": self.environ,
            "stdin": subprocess.DEVNULL,
            "shell": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        started = self._monotonic()
        process = self._popen(argv, **kwargs)
        deadline = started + float(command.timeout_seconds)
        while True:
            return_code = process.poll()
            if return_code is not None:
                elapsed = max(0.0, self._monotonic() - started)
                if return_code != 0:
                    raise CommandExecutionError(
                        f"module exited unsuccessfully: {command.module}"
                    )
                return CommandResult(command.module, return_code, elapsed)
            if stop_event.wait(self.poll_seconds):
                self._stop_process(process)
                raise CommandExecutionError("module stopped by service shutdown")
            if self._monotonic() >= deadline:
                self._stop_process(process)
                raise CommandExecutionError(f"module timed out: {command.module}")
