"""Windows Task Scheduler·macOS launchd 등록 계획과 명시적 installer."""
from __future__ import annotations

import getpass
import os
import plistlib
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

_CONFIRM = "REGISTER_INVESTMENT_SERVICES"
_LABEL = "com.local.investment-ai-harness"
_SERVICE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MODULE_RE = re.compile(r"^investment_agent(?:\.[a-z][a-z0-9_]*)+$")
_PROHIBITED = (
    "TOSS_CLIENT", "SUPABASE_SERVICE", "DISCORD_BOT_TOKEN", "DISCORD_WEBHOOK",
    "PASSWORD=", "SECRET=", "TOKEN=",
)


@dataclass(frozen=True)
class ServiceInstallPlan:
    platform: str
    label: str
    descriptor_path: str
    descriptor_text: str
    register_command: tuple[str, ...]

    def __post_init__(self) -> None:
        serialized = f"{self.descriptor_text}\n{' '.join(self.register_command)}"
        if any(item.lower() in serialized.lower() for item in _PROHIBITED):
            raise ValueError("service descriptor must not contain secret variables")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["register_command"] = list(self.register_command)
        return payload


def _absolute(path: Path | str, name: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_absolute():
        raise ValueError(f"{name} must be absolute")
    return resolved


def windows_task_plan(
    *,
    python_executable: Path | str,
    repository_root: Path | str,
    state_dir: Path | str,
    user_id: str | None = None,
    label: str = _LABEL,
    entry_module: str = "investment_agent.operations.commands.investment_harness",
    entry_arguments: Sequence[str] = ("--serve", "--mode", "analysis_only"),
    descriptor_filename: str = "investment_harness.task.xml",
) -> ServiceInstallPlan:
    python = _absolute(python_executable, "python_executable")
    root = _absolute(repository_root, "repository_root")
    state = _absolute(state_dir, "state_dir")
    if _SERVICE_LABEL_RE.fullmatch(label) is None:
        raise ValueError("service label is invalid")
    if _MODULE_RE.fullmatch(entry_module) is None:
        raise ValueError("service entry module is invalid")
    if Path(descriptor_filename).name != descriptor_filename:
        raise ValueError("descriptor_filename must be a plain filename")
    descriptor = state / descriptor_filename
    module_args = [str(value) for value in entry_arguments]
    if entry_module == "investment_agent.operations.commands.investment_harness":
        module_args += ["--state-dir", str(state)]
    arguments = subprocess.list2cmdline(["-m", entry_module, *module_args])
    import xml.etree.ElementTree as ET

    namespace = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", namespace)
    task = ET.Element(f"{{{namespace}}}Task", {"version": "1.4"})
    registration = ET.SubElement(task, f"{{{namespace}}}RegistrationInfo")
    ET.SubElement(registration, f"{{{namespace}}}Description").text = (
        f"Local investment service {label}; contains no credentials"
    )
    triggers = ET.SubElement(task, f"{{{namespace}}}Triggers")
    logon = ET.SubElement(triggers, f"{{{namespace}}}LogonTrigger")
    ET.SubElement(logon, f"{{{namespace}}}Enabled").text = "true"
    task_user = (user_id or getpass.getuser()).strip()
    if not task_user:
        raise ValueError("Windows task user_id is required")
    ET.SubElement(logon, f"{{{namespace}}}UserId").text = task_user
    principals = ET.SubElement(task, f"{{{namespace}}}Principals")
    principal = ET.SubElement(principals, f"{{{namespace}}}Principal", {"id": "Author"})
    ET.SubElement(principal, f"{{{namespace}}}UserId").text = task_user
    ET.SubElement(principal, f"{{{namespace}}}LogonType").text = "InteractiveToken"
    ET.SubElement(principal, f"{{{namespace}}}RunLevel").text = "LeastPrivilege"
    settings = ET.SubElement(task, f"{{{namespace}}}Settings")
    for name, value in (
        ("MultipleInstancesPolicy", "IgnoreNew"),
        ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"),
        ("StartWhenAvailable", "true"),
        ("ExecutionTimeLimit", "PT0S"),
    ):
        ET.SubElement(settings, f"{{{namespace}}}{name}").text = value
    restart = ET.SubElement(settings, f"{{{namespace}}}RestartOnFailure")
    ET.SubElement(restart, f"{{{namespace}}}Interval").text = "PT1M"
    ET.SubElement(restart, f"{{{namespace}}}Count").text = "999"
    actions = ET.SubElement(task, f"{{{namespace}}}Actions", {"Context": "Author"})
    execute = ET.SubElement(actions, f"{{{namespace}}}Exec")
    ET.SubElement(execute, f"{{{namespace}}}Command").text = str(python)
    ET.SubElement(execute, f"{{{namespace}}}Arguments").text = arguments
    ET.SubElement(execute, f"{{{namespace}}}WorkingDirectory").text = str(root)
    text = ET.tostring(task, encoding="unicode", xml_declaration=True)
    return ServiceInstallPlan(
        platform="windows",
        label=label,
        descriptor_path=str(descriptor),
        descriptor_text=text,
        register_command=(
            "schtasks", "/Create", "/TN", label, "/XML", str(descriptor), "/F",
        ),
    )


def macos_launchd_plan(
    *,
    python_executable: Path | str,
    repository_root: Path | str,
    state_dir: Path | str,
    launch_agents_dir: Path | str | None = None,
    uid: int | None = None,
    label: str = _LABEL,
    entry_module: str = "investment_agent.operations.commands.investment_harness",
    entry_arguments: Sequence[str] = ("--serve", "--mode", "analysis_only"),
    log_prefix: str = "harness",
) -> ServiceInstallPlan:
    python = _absolute(python_executable, "python_executable")
    root = _absolute(repository_root, "repository_root")
    state = _absolute(state_dir, "state_dir")
    agents = _absolute(
        launch_agents_dir or (Path.home() / "Library" / "LaunchAgents"),
        "launch_agents_dir",
    )
    if _SERVICE_LABEL_RE.fullmatch(label) is None:
        raise ValueError("service label is invalid")
    if _MODULE_RE.fullmatch(entry_module) is None:
        raise ValueError("service entry module is invalid")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", log_prefix):
        raise ValueError("log_prefix is invalid")
    module_args = [str(value) for value in entry_arguments]
    if entry_module == "investment_agent.operations.commands.investment_harness":
        module_args += ["--state-dir", str(state)]
    descriptor = agents / f"{label}.plist"
    payload = {
        "Label": label,
        "ProgramArguments": [
            str(python), "-m", entry_module, *module_args,
        ],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "StandardOutPath": str(state / f"{log_prefix}.stdout.log"),
        "StandardErrorPath": str(state / f"{log_prefix}.stderr.log"),
    }
    text = plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True).decode("utf-8")
    get_uid = getattr(os, "getuid", lambda: 501)
    user_id = uid if uid is not None else get_uid()
    return ServiceInstallPlan(
        platform="macos",
        label=label,
        descriptor_path=str(descriptor),
        descriptor_text=text,
        register_command=("launchctl", "bootstrap", f"gui/{user_id}", str(descriptor)),
    )


def apply_install_plan(
    plan: ServiceInstallPlan,
    *,
    apply: bool = False,
    confirm: str = "",
    current_platform: str | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> bool:
    """기본은 무변경이며 apply와 정확한 확인 문구가 함께 있어야 등록한다."""
    if not apply:
        return False
    if confirm != _CONFIRM:
        raise ValueError(f"service registration requires --confirm {_CONFIRM}")
    platform = current_platform or ("windows" if os.name == "nt" else "macos" if sys.platform == "darwin" else "other")
    if platform != plan.platform:
        raise RuntimeError(f"cannot apply {plan.platform} plan on {platform}")
    descriptor = Path(plan.descriptor_path).resolve()
    descriptor.parent.mkdir(parents=True, exist_ok=True)
    temporary = descriptor.with_name(f".{descriptor.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(plan.descriptor_text, encoding="utf-8")
        os.replace(temporary, descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()
    runner(list(plan.register_command), check=True, shell=False)
    return True


INSTALL_CONFIRMATION = _CONFIRM
