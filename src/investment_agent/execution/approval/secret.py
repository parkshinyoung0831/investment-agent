"""Discord 승인 버튼용 로컬 HMAC 비밀값을 안전하게 준비한다."""
from __future__ import annotations

import getpass
import os
import secrets
import stat
import subprocess
from pathlib import Path
from typing import Mapping

from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.platform.storage_paths import repository_root

_MIN_SECRET_BYTES = 32
_MAX_SECRET_BYTES = 512


def _default_path(env: Mapping[str, str]) -> Path:
    configured = str(env.get("DISCORD_APPROVAL_HMAC_SECRET_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (
        repository_root()
        / "artifacts"
        / "execution"
        / "approval-hmac.key"
    )


def _validate(value: str) -> str:
    secret = value.strip()
    size = len(secret.encode("utf-8"))
    if not _MIN_SECRET_BYTES <= size <= _MAX_SECRET_BYTES:
        raise ExecutionSafetyError("Discord approval HMAC secret has an invalid length")
    return secret


def _restrict(path: Path) -> None:
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    if os.name != "nt":
        return
    username = os.environ.get("USERNAME", "").strip() or getpass.getuser()
    domain = os.environ.get("USERDOMAIN", "").strip()
    identity = f"{domain}\\{username}" if domain else username
    try:
        result = subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{identity}:(F)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise ExecutionSafetyError("Discord approval secret ACL could not be secured") from exc
    if result.returncode != 0:
        raise ExecutionSafetyError("Discord approval secret ACL could not be secured")


def _read(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ExecutionSafetyError("Discord approval secret file is not a regular file")
    if path.stat().st_size > _MAX_SECRET_BYTES + 2:
        raise ExecutionSafetyError("Discord approval secret file is too large")
    _restrict(path)
    try:
        return _validate(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ExecutionSafetyError("Discord approval secret file could not be read") from exc


def load_or_create_approval_secret(
    env: Mapping[str, str] | None = None,
) -> str:
    """환경변수를 우선 사용하고, 없으면 Git 제외 로컬 파일을 원자 생성한다."""
    values = os.environ if env is None else env
    inline = str(values.get("DISCORD_APPROVAL_HMAC_SECRET") or "").strip()
    if inline:
        return _validate(inline)

    path = _default_path(values)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(path.parent, 0o700)
    except OSError as exc:
        raise ExecutionSafetyError("Discord approval secret directory could not be prepared") from exc
    if path.exists():
        return _read(path)

    generated = secrets.token_urlsafe(48)
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = -1
            handle.write(generated + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _restrict(path)
        return _validate(generated)
    except FileExistsError:
        return _read(path)
    except OSError as exc:
        raise ExecutionSafetyError("Discord approval secret file could not be created") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


__all__ = ["load_or_create_approval_secret"]
