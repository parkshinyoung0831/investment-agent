"""한 장비에서 하네스 프로세스가 하나만 실행되게 하는 OS file lock."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any


class DuplicateProcessError(RuntimeError):
    """이미 같은 state 디렉터리를 소유한 프로세스가 있는 경우다."""


class ProcessFileLock:
    def __init__(self, path: Path | str):
        self.path = Path(path).resolve()
        self._handle: IO[str] | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            raise RuntimeError("process lock is already acquired by this object")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        if self.path.stat().st_size == 0:
            handle.write("\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise DuplicateProcessError(f"harness lock is already held: {self.path}") from exc
        metadata: dict[str, Any] = {
            "pid": os.getpid(),
            "acquired_at": datetime.now(timezone.utc).isoformat(),
        }
        handle.seek(1)
        handle.truncate()
        handle.write(json.dumps(metadata, sort_keys=True))
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None

    def __enter__(self) -> "ProcessFileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
