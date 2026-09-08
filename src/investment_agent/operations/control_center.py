"""ATLAS 로컬 제어센터.

대시보드는 관측 전용으로 유지하고, 하네스 시작·정지처럼 로컬 프로세스를
변경하는 작업만 이 창에서 명시적으로 실행한다.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Callable

from investment_agent.operations.harness.switch import get_harness_status
from investment_agent.operations.palette import CONTROL_CENTER_PALETTE
from investment_agent.platform.storage_paths import repository_root


ROOT = repository_root()
STATE_DIR = ROOT / "artifacts" / "ops" / "investment_harness"
FONT_SANS = "Pretendard"
MODE_LABELS = {
    "모의투자 · analysis_only": "analysis_only",
    "실계좌 승인 · approval_workflow": "approval_workflow",
}


def dashboard_url(*, host: str = "127.0.0.1", ports: range = range(8501, 8511)) -> str | None:
    """실행 중인 로컬 Streamlit만 찾아 URL을 반환한다."""

    for port in ports:
        url = f"http://{host}:{port}"
        try:
            with urllib.request.urlopen(url, timeout=0.35) as response:
                if 200 <= int(response.status) < 500:
                    return url
        except (OSError, urllib.error.URLError):
            continue
    return None


def control_command(
    action: str,
    *,
    mode: str = "analysis_only",
    root_dir: Path = ROOT,
    python_path: Path | None = None,
) -> list[str]:
    """시작은 사전점검을 거치고 정지는 단일 스위치로 보낸다."""

    root = Path(root_dir).resolve()
    python = Path(python_path or sys.executable).resolve()
    if action == "start":
        if mode == "analysis_only":
            return [str(python), str(root / "launcher.py"), "--shadow"]
        if mode == "approval_workflow":
            return [str(python), str(root / "launcher.py"), "--harness"]
        raise ValueError(f"지원하지 않는 하네스 모드: {mode}")
    if action == "stop":
        return [str(python), "-m", "investment_agent.operations.commands.harness_switch", "--off"]
    raise ValueError(f"지원하지 않는 제어 작업: {action}")


def dashboard_command(
    *,
    root_dir: Path = ROOT,
    python_path: Path | None = None,
) -> list[str]:
    """포트 선택과 사전 점검을 재사용하는 대시보드 실행 명령을 만든다."""

    root = Path(root_dir).resolve()
    python = Path(python_path or sys.executable).resolve()
    return [str(python), str(root / "launcher.py"), "--dashboard"]


class ControlCenter:
    """Tkinter 기반의 작고 명시적인 로컬 운영 제어 창."""

    def __init__(self, *, root_dir: Path = ROOT, state_dir: Path = STATE_DIR) -> None:
        import tkinter as tk
        from tkinter import messagebox

        self.tk = tk
        self.messagebox = messagebox
        self.root_dir = Path(root_dir).resolve()
        self.state_dir = Path(state_dir).resolve()
        self.colors = CONTROL_CENTER_PALETTE
        self.window = tk.Tk()
        self.window.title("ATLAS · Local Control Center")
        self.window.geometry("760x540")
        self.window.minsize(680, 460)
        self.window.configure(bg=self.colors.canvas)
        self.status_var = tk.StringVar(value="상태를 읽는 중…")
        self.meta_var = tk.StringVar(value="")
        self.log_var = tk.StringVar(value="준비됐어요 · 대시보드는 읽기 전용이에요")
        self.mode_var = tk.StringVar(value=next(iter(MODE_LABELS)))
        self._dashboard_starting = False
        self._dashboard_process: subprocess.Popen[Any] | None = None
        self._build()
        self.refresh()

    def _build(self) -> None:
        tk = self.tk
        colors = self.colors
        title = tk.Label(
            self.window,
            text="ATLAS",
            fg=colors.text,
            bg=colors.canvas,
            font=(FONT_SANS, 25, "bold"),
        )
        title.pack(anchor="w", padx=32, pady=(26, 0))
        tk.Label(
            self.window,
            text="로컬 운영 제어센터",
            fg=colors.muted_text,
            bg=colors.canvas,
            font=(FONT_SANS, 10, "bold"),
        ).pack(anchor="w", padx=34)

        card = tk.Frame(
            self.window,
            bg=colors.surface,
            highlightbackground=colors.border,
            highlightthickness=1,
        )
        card.pack(fill="x", padx=28, pady=22)
        tk.Label(
            card,
            textvariable=self.status_var,
            fg=colors.text,
            bg=colors.surface,
            font=(FONT_SANS, 20, "bold"),
            anchor="w",
        ).pack(fill="x", padx=22, pady=(18, 2))
        tk.Label(
            card,
            textvariable=self.meta_var,
            fg=colors.secondary_text,
            bg=colors.surface,
            font=(FONT_SANS, 10),
            anchor="w",
        ).pack(fill="x", padx=22, pady=(0, 18))

        actions = tk.Frame(self.window, bg=colors.canvas)
        actions.pack(fill="x", padx=28)
        self._button(actions, "선택한 모드로 시작", self.start_harness, colors.primary, 0, 0)
        self._button(actions, "안전하게 완전 정지", self.stop, colors.danger, 0, 1)
        self._button(
            actions,
            "대시보드 시작·열기",
            self.open_dashboard,
            colors.surface_subtle,
            1,
            0,
        )
        self._button(
            actions,
            "상태 새로고침",
            self.refresh,
            colors.surface_subtle,
            1,
            1,
        )
        tk.Label(
            actions,
            text="운영 모드",
            fg=colors.secondary_text,
            bg=colors.canvas,
            font=(FONT_SANS, 10),
        ).grid(row=2, column=0, sticky="w", pady=(18, 4))
        mode_menu = tk.OptionMenu(
            actions,
            self.mode_var,
            *MODE_LABELS,
        )
        mode_menu.configure(
            bg=colors.surface_subtle,
            fg=colors.text,
            activebackground=colors.surface,
            activeforeground=colors.text,
            highlightthickness=0,
            relief="flat",
            font=(FONT_SANS, 10),
        )
        mode_menu["menu"].configure(
            bg=colors.surface,
            fg=colors.text,
            activebackground=colors.surface_subtle,
            activeforeground=colors.text,
            font=(FONT_SANS, 10),
        )
        mode_menu.grid(row=2, column=1, sticky="e", pady=(12, 0))
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)
        tk.Label(
            self.window,
            textvariable=self.log_var,
            fg=colors.secondary_text,
            bg=colors.canvas,
            font=(FONT_SANS, 10),
            anchor="w",
        ).pack(fill="x", padx=32, pady=(24, 10))
        tk.Label(
            self.window,
            text="실주문은 RiskGate와 Discord 승인을 모두 통과해야 해요. 이 창은 로컬 제어만 담당해요.",
            fg=colors.muted_text,
            bg=colors.canvas,
            font=(FONT_SANS, 9),
            anchor="w",
        ).pack(fill="x", padx=32)

    def _button(self, parent: Any, text: str, command: Callable[[], None], color: str, row: int, column: int) -> None:
        button = self.tk.Button(
            parent,
            text=text,
            command=command,
            bg=color,
            fg=self.colors.text,
            activebackground=color,
            activeforeground=self.colors.text,
            relief="flat",
            bd=0,
            padx=16,
            pady=13,
            font=(FONT_SANS, 10, "bold"),
            cursor="hand2",
        )
        button.grid(row=row, column=column, sticky="ew", padx=5, pady=5)

    def _run(self, action: str, *, mode: str = "analysis_only") -> None:
        command = control_command(action, mode=mode, root_dir=self.root_dir)
        action_text = "하네스를 시작하고 있어요" if action == "start" else "하네스를 정지하고 있어요"
        self.log_var.set(action_text)

        def worker() -> None:
            try:
                result = subprocess.run(command, cwd=self.root_dir, capture_output=True, text=True, encoding="utf-8", check=False)
                output = (result.stdout or result.stderr or "완료").strip().splitlines()
                message = output[-1] if output else f"종료 코드 {result.returncode}"
            except OSError as error:
                message = f"작업을 실행하지 못했어요 · 실행 환경을 확인해 주세요 ({type(error).__name__}: {error})"
            self.window.after(0, lambda: (self.log_var.set(message[:180]), self.refresh()))

        threading.Thread(target=worker, daemon=True).start()

    def refresh(self) -> None:
        def worker() -> None:
            try:
                status = get_harness_status(state_dir=self.state_dir, root_dir=self.root_dir).to_dict()
                running = bool(status.get("is_running"))
                headline = "● 실행 중" if running else "○ 정지됨"
                meta = f"mode={status.get('mode') or '—'}  ·  PID={status.get('process_id') or '—'}  ·  kill switch={str(status.get('trading_kill_switch') or 'on').upper()}"
                if status.get("maintenance_hold"):
                    meta += "  ·  정비 보류"
            except Exception as error:
                headline = "? 상태를 확인하지 못했어요"
                meta = f"상태 새로고침을 다시 눌러 주세요 · {type(error).__name__}"
            self.window.after(0, lambda: (self.status_var.set(headline), self.meta_var.set(meta)))

        threading.Thread(target=worker, daemon=True).start()

    def start_harness(self) -> None:
        mode = MODE_LABELS[self.mode_var.get()]
        if mode == "approval_workflow" and not self.messagebox.askyesno(
            "승인 하네스 시작",
            "실계좌 승인 워크플로를 시작해요. kill switch와 Discord 승인 경계를 확인했나요?",
        ):
            self.log_var.set("시작하지 않았어요 · 승인 하네스는 명시적 확인이 필요해요")
            return
        self._run("start", mode=mode)

    def stop(self) -> None:
        if self.messagebox.askyesno("안전하게 완전 정지", "하네스를 정지하고 프로세스 락을 정리할까요?"):
            self._run("stop")

    def open_dashboard(self) -> None:
        if self._dashboard_starting:
            self.log_var.set("대시보드를 시작하고 있어요 · 잠시만 기다려 주세요")
            return
        url = dashboard_url()
        if url:
            webbrowser.open(url)
            self.log_var.set(f"대시보드를 열었어요 · {url}")
            return
        if self._dashboard_process is not None and self._dashboard_process.poll() is None:
            self.log_var.set("대시보드 프로세스가 준비 중이에요 · 잠시 뒤 다시 열어 주세요")
            return
        self._dashboard_starting = True
        self.log_var.set("대시보드를 시작하고 있어요 · 준비되면 자동으로 열어요")
        command = dashboard_command(root_dir=self.root_dir)

        def finish(
            message: str,
            *,
            url_to_open: str | None = None,
            clear_process: bool = False,
        ) -> None:
            self._dashboard_starting = False
            if clear_process:
                self._dashboard_process = None
            self.log_var.set(message)
            if url_to_open:
                webbrowser.open(url_to_open)

        def worker() -> None:
            try:
                process_kwargs: dict[str, Any] = {
                    "cwd": self.root_dir,
                    "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL,
                }
                if sys.platform == "win32":
                    process_kwargs["creationflags"] = (
                        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                        | getattr(subprocess, "DETACHED_PROCESS", 0)
                    )
                else:
                    process_kwargs["start_new_session"] = True
                process = subprocess.Popen(command, **process_kwargs)
                self._dashboard_process = process
                for _ in range(60):
                    ready_url = dashboard_url()
                    if ready_url:
                        self.window.after(
                            0,
                            lambda value=ready_url: finish(
                                f"대시보드를 열었어요 · {value}",
                                url_to_open=value,
                            ),
                        )
                        return
                    return_code = process.poll()
                    if return_code is not None:
                        self.window.after(
                            0,
                            lambda code=return_code: finish(
                                "대시보드를 시작하지 못했어요 · "
                                f"종료 코드 {code}를 확인하려면 run.bat --dashboard를 실행해 주세요",
                                clear_process=True,
                            ),
                        )
                        return
                    time.sleep(0.25)
                self.window.after(
                    0,
                    lambda: finish(
                        "대시보드 준비가 오래 걸리고 있어요 · 잠시 뒤 다시 열어 주세요"
                    ),
                )
            except OSError as error:
                self.window.after(
                    0,
                    lambda detail=str(error): finish(
                        f"대시보드를 시작하지 못했어요 · 실행 환경을 확인해 주세요 ({detail})",
                        clear_process=True,
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def run(self) -> int:
        self.window.mainloop()
        return 0


def run_control_center() -> int:
    """GUI를 만들 수 없는 환경에서는 명확한 오류를 반환한다."""

    try:
        return ControlCenter().run()
    except Exception as error:
        print(json.dumps({"status": "error", "message": f"제어센터를 시작할 수 없습니다: {error}"}, ensure_ascii=False))
        return 1


__all__ = [
    "ControlCenter",
    "control_command",
    "dashboard_command",
    "dashboard_url",
    "run_control_center",
]
