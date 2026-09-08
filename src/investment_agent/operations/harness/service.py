"""process lock, signal, heartbeat loop와 정상 종료를 묶는 서비스 경계."""
from __future__ import annotations

import os
import signal
from datetime import datetime, timezone
from threading import Event
from typing import Callable

from investment_agent.operations.harness.lock import DuplicateProcessError, ProcessFileLock
from investment_agent.operations.harness.reporting import HarnessReporter
from investment_agent.operations.harness.runtime import HarnessScheduler


class HarnessService:
    def __init__(
        self,
        *,
        scheduler: HarnessScheduler,
        lock: ProcessFileLock,
        poll_seconds: float = 15.0,
        now: Callable[[], datetime] | None = None,
        reporter: HarnessReporter | None = None,
    ) -> None:
        if poll_seconds <= 0.0:
            raise ValueError("poll_seconds must be positive")
        self.scheduler = scheduler
        self.lock = lock
        self.poll_seconds = float(poll_seconds)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.reporter = reporter or scheduler.reporter
        self.stop_event: Event = scheduler.stop_event

    def request_stop(self) -> None:
        self.stop_event.set()

    def run_once(self) -> int:
        try:
            self.lock.acquire()
        except DuplicateProcessError as exc:
            self.reporter.error("duplicate_process", error=str(exc))
            return 2
        try:
            self.scheduler.start(now=self.now(), process_id=os.getpid())
            self.scheduler.tick(now=self.now())
            return 0
        except Exception as exc:  # noqa: BLE001 - 오류 타입만 알리고 상태를 안전 종료한다
            self.reporter.error("service_failed", error_type=type(exc).__name__)
            return 1
        finally:
            self.scheduler.shutdown(now=self.now())
            self.lock.release()

    def run_forever(self, *, install_signal_handlers: bool = True) -> int:
        try:
            self.lock.acquire()
        except DuplicateProcessError as exc:
            self.reporter.error("duplicate_process", error=str(exc))
            return 2
        previous: dict[int, object] = {}

        def handle_signal(signum, frame) -> None:
            self.reporter.event("shutdown_requested", signal=signum)
            self.request_stop()

        heartbeat_interval = min(5.0, self.poll_seconds)

        def _heartbeat_worker() -> None:
            while not self.stop_event.wait(heartbeat_interval):
                try:
                    self.scheduler.update_process_heartbeat(now=self.now())
                except Exception:
                    pass

        import threading
        heartbeat_thread = threading.Thread(
            target=_heartbeat_worker,
            name="HarnessServiceHeartbeatThread",
            daemon=True,
        )

        try:
            if install_signal_handlers:
                for signum in (signal.SIGINT, signal.SIGTERM):
                    previous[signum] = signal.getsignal(signum)
                    signal.signal(signum, handle_signal)
            self.scheduler.start(now=self.now(), process_id=os.getpid())
            heartbeat_thread.start()
            import gc
            while not self.stop_event.is_set():
                self.scheduler.tick(now=self.now())
                gc.collect()
                self.stop_event.wait(self.poll_seconds)
            return 0
        except Exception as exc:  # noqa: BLE001 - 서비스 오류는 알리고 안전 종료한다
            self.reporter.error("service_failed", error_type=type(exc).__name__)
            return 1
        finally:
            self.stop_event.set()
            if heartbeat_thread.is_alive():
                heartbeat_thread.join(timeout=2.0)
            self.scheduler.shutdown(now=self.now())
            if install_signal_handlers:
                for signum, handler in previous.items():
                    signal.signal(signum, handler)
            self.lock.release()
