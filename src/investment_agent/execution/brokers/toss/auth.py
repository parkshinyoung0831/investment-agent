"""토스 Open API OAuth 토큰의 프로세스·호스트 공용 경계.

토스는 새 access token을 발급하면 이전 token이 무효가 될 수 있다. 따라서 같은
자격증명을 쓰는 worker들은 메모리 singleton과 로컬 파일 잠금을 함께 사용하고,
토큰 발급과 401 갱신을 반드시 잠금 안에서 직렬화한다.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import math
import os
import secrets
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from investment_agent.platform.storage_paths import repository_root

_BASE = "https://openapi.tossinvest.com"
_TOKEN_URL = f"{_BASE}/oauth2/token"
_CACHE_VERSION = 1
_DEFAULT_TOKEN_TTL_SEC = 3600.0
_DEFAULT_EXPIRY_SKEW_SEC = 60.0
_DEFAULT_LOCK_TIMEOUT_SEC = 90.0
_DEFAULT_STALE_LOCK_SEC = 300.0
_DEFAULT_LOCK_POLL_SEC = 0.05
_MAX_CACHE_BYTES = 64 * 1024
_TOKEN_REQUEST_ATTEMPTS = 3


class TossAuthError(RuntimeError):
    """비밀값을 포함하지 않는 토스 인증·로컬 토큰 캐시 오류."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, repr=False)
class _TokenRecord:
    access_token: str
    issued_at_epoch: float
    expires_at_epoch: float


def _credential_fingerprint(client_id: str, client_secret: str) -> str:
    material = f"{client_id}\0{client_secret}".encode()
    return hashlib.sha256(material).hexdigest()


def _default_cache_path() -> Path:
    configured = os.environ.get("TOSS_TOKEN_CACHE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    # 모든 worker가 저장소 루트의 같은 파일을 사용해 동일 자격증명의 토큰 발급을
    # 직렬화한다.
    return repository_root() / "artifacts" / "toss_auth" / "oauth-token.json"


def credentials_configured() -> bool:
    """공용 토스 client credentials 두 값이 모두 설정됐는지 반환한다."""
    return bool(
        os.environ.get("TOSS_CLIENT_ID", "").strip()
        and os.environ.get("TOSS_CLIENT_SECRET", "").strip()
    )


class TossTokenManager:
    """한 자격증명의 토큰 발급·캐시·401 갱신을 직렬화한다."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        cache_path: str | Path,
        token_url: str = _TOKEN_URL,
        http_post: Callable[..., Any] | None = None,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        expiry_skew_seconds: float = _DEFAULT_EXPIRY_SKEW_SEC,
        lock_timeout_seconds: float = _DEFAULT_LOCK_TIMEOUT_SEC,
        stale_lock_seconds: float = _DEFAULT_STALE_LOCK_SEC,
        lock_poll_seconds: float = _DEFAULT_LOCK_POLL_SEC,
    ) -> None:
        normalized_id = client_id.strip()
        normalized_secret = client_secret.strip()
        if not normalized_id or not normalized_secret:
            raise TossAuthError("TOSS_CLIENT_ID와 TOSS_CLIENT_SECRET이 필요합니다")
        if lock_timeout_seconds <= 0 or stale_lock_seconds <= 0 or lock_poll_seconds <= 0:
            raise ValueError("토큰 잠금 시간 설정은 양수여야 합니다")
        if expiry_skew_seconds < 0:
            raise ValueError("토큰 만료 여유 시간은 음수일 수 없습니다")

        self._client_id = normalized_id
        self._client_secret = normalized_secret
        self._fingerprint = _credential_fingerprint(normalized_id, normalized_secret)
        self._cache_path = Path(cache_path).expanduser().resolve()
        self._lock_path = self._cache_path.with_name(self._cache_path.name + ".lock")
        self._token_url = token_url
        self._http_post = http_post or requests.post
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._sleep = sleep
        self._expiry_skew_seconds = float(expiry_skew_seconds)
        self._lock_timeout_seconds = float(lock_timeout_seconds)
        self._stale_lock_seconds = float(stale_lock_seconds)
        self._lock_poll_seconds = float(lock_poll_seconds)
        self._memory: _TokenRecord | None = None
        self._thread_lock = threading.RLock()

    @property
    def cache_path(self) -> Path:
        """운영 점검용 캐시 경로. 파일 내용은 외부로 노출하지 않는다."""
        return self._cache_path

    def access_token(self) -> str:
        """유효한 공용 token을 반환하고 없을 때만 잠금 안에서 발급한다."""
        with self._thread_lock:
            now = self._wall_clock()
            if self._is_valid(self._memory, now):
                assert self._memory is not None
                return self._memory.access_token

            with self._interprocess_lock():
                now = self._wall_clock()
                cached = self._load_cache()
                if self._is_valid(cached, now):
                    self._memory = cached
                    assert cached is not None
                    return cached.access_token
                issued = self._issue_token()
                self._save_cache(issued)
                self._memory = issued
                return issued.access_token

    def refresh_access_token(self, *, rejected_token: str) -> str:
        """401을 낸 token이 여전히 최신일 때만 잠금 안에서 한 번 갱신한다."""
        if not rejected_token:
            raise TossAuthError("401 갱신에 거절된 토큰이 필요합니다")
        with self._thread_lock:
            now = self._wall_clock()
            if (
                self._is_valid(self._memory, now)
                and self._memory is not None
                and self._memory.access_token != rejected_token
            ):
                return self._memory.access_token

            with self._interprocess_lock():
                now = self._wall_clock()
                cached = self._load_cache()
                if (
                    self._is_valid(cached, now)
                    and cached is not None
                    and cached.access_token != rejected_token
                ):
                    self._memory = cached
                    return cached.access_token
                issued = self._issue_token()
                self._save_cache(issued)
                self._memory = issued
                return issued.access_token

    def authorized_request(
        self,
        request: Callable[..., Any],
        *args: Any,
        headers: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> Any:
        """인증 요청을 보내고 401이면 공용 갱신 후 정확히 한 번만 다시 보낸다."""
        token = self.access_token()
        response = request(
            *args,
            headers=self._headers_with_token(headers, token),
            **kwargs,
        )
        if getattr(response, "status_code", None) != 401:
            return response

        refreshed = self.refresh_access_token(rejected_token=token)
        return request(
            *args,
            headers=self._headers_with_token(headers, refreshed),
            **kwargs,
        )

    @staticmethod
    def _headers_with_token(
        headers: Mapping[str, str] | None,
        token: str,
    ) -> dict[str, str]:
        merged = {
            str(key): str(value)
            for key, value in (headers or {}).items()
            if str(key).lower() != "authorization"
        }
        merged["Authorization"] = f"Bearer {token}"
        merged.setdefault("Accept", "application/json")
        return merged

    def _is_valid(self, record: _TokenRecord | None, now: float) -> bool:
        if record is None or not math.isfinite(now):
            return False
        if record.issued_at_epoch > now + 300:
            return False
        lifetime = record.expires_at_epoch - record.issued_at_epoch
        if not math.isfinite(lifetime) or lifetime <= 0:
            return False
        skew = min(self._expiry_skew_seconds, lifetime / 10.0)
        return now < record.expires_at_epoch - skew

    def _issue_token(self) -> _TokenRecord:
        try:
            response = self._request_token_response()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 403:
                raise TossAuthError(
                    "토스 토큰 발급이 403으로 거부되었습니다. 현재 공인 IP가 허용 목록에 "
                    "등록됐는지 확인하세요",
                    status_code=status,
                ) from None
            raise TossAuthError(
                f"토스 토큰 발급 실패(status={status})",
                status_code=status,
            ) from None
        except (requests.RequestException, OSError):
            raise TossAuthError("토스 토큰 발급 중 네트워크 오류가 발생했습니다") from None

        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise TossAuthError("토스 토큰 응답이 올바른 JSON이 아닙니다") from None
        if not isinstance(payload, dict):
            raise TossAuthError("토스 토큰 응답이 객체가 아닙니다")
        token = payload.get("access_token")
        if (
            not isinstance(token, str)
            or not token.strip()
            or len(token) > _MAX_CACHE_BYTES
            or "\r" in token
            or "\n" in token
        ):
            raise TossAuthError("토스 토큰 응답에 access_token이 없습니다")
        try:
            expires_in = float(payload.get("expires_in", _DEFAULT_TOKEN_TTL_SEC))
        except (TypeError, ValueError):
            raise TossAuthError("토스 토큰 만료 시간이 올바르지 않습니다") from None
        if not math.isfinite(expires_in) or expires_in <= 0:
            raise TossAuthError("토스 토큰 만료 시간이 올바르지 않습니다")
        issued_at = self._wall_clock()
        return _TokenRecord(
            access_token=token.strip(),
            issued_at_epoch=issued_at,
            expires_at_epoch=issued_at + expires_in,
        )

    def _request_token_response(self) -> Any:
        """비밀값을 로그에 넣지 않고 network·429·5xx만 제한적으로 재시도한다."""
        for attempt in range(_TOKEN_REQUEST_ATTEMPTS):
            try:
                response = self._http_post(
                    self._token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                    timeout=20,
                )
                response.raise_for_status()
                return response
            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                retryable = status_code == 429 or (
                    status_code is not None and 500 <= status_code < 600
                )
                if not retryable or attempt + 1 >= _TOKEN_REQUEST_ATTEMPTS:
                    raise
            except (requests.Timeout, requests.ConnectionError, OSError):
                if attempt + 1 >= _TOKEN_REQUEST_ATTEMPTS:
                    raise
            self._sleep(float(2**attempt))
        raise AssertionError("토큰 재시도 loop가 결과 없이 종료됐습니다")

    def _load_cache(self) -> _TokenRecord | None:
        try:
            if self._cache_path.is_symlink():
                return None
            metadata = self._cache_path.stat()
            if metadata.st_size > _MAX_CACHE_BYTES:
                return None
            self._restrict_file_permissions(self._cache_path)
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("version") != _CACHE_VERSION:
            return None
        if payload.get("credential_fingerprint") != self._fingerprint:
            return None
        token = payload.get("access_token")
        if (
            not isinstance(token, str)
            or not token
            or len(token) > _MAX_CACHE_BYTES
            or "\r" in token
            or "\n" in token
        ):
            return None
        try:
            issued_at = float(payload["issued_at_epoch"])
            expires_at = float(payload["expires_at_epoch"])
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(issued_at) or not math.isfinite(expires_at):
            return None
        if expires_at <= issued_at:
            return None
        return _TokenRecord(token, issued_at, expires_at)

    def _save_cache(self, record: _TokenRecord) -> None:
        self._ensure_cache_directory()
        payload = {
            "version": _CACHE_VERSION,
            "credential_fingerprint": self._fingerprint,
            "access_token": record.access_token,
            "issued_at_epoch": record.issued_at_epoch,
            "expires_at_epoch": record.expires_at_epoch,
        }
        file_descriptor = -1
        temporary_path: Path | None = None
        try:
            file_descriptor, raw_path = tempfile.mkstemp(
                prefix=f".{self._cache_path.name}.",
                suffix=".tmp",
                dir=self._cache_path.parent,
            )
            temporary_path = Path(raw_path)
            self._restrict_file_permissions(temporary_path)
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                file_descriptor = -1
                json.dump(payload, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._cache_path)
            temporary_path = None
            self._restrict_file_permissions(self._cache_path)
            self._sync_directory()
        except OSError as exc:
            raise TossAuthError("토스 토큰 캐시를 안전하게 저장하지 못했습니다") from exc
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)
            if temporary_path is not None:
                with suppress(FileNotFoundError):
                    temporary_path.unlink()

    def _ensure_cache_directory(self) -> None:
        try:
            self._cache_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name != "nt":
                os.chmod(self._cache_path.parent, 0o700)
        except OSError as exc:
            raise TossAuthError("토스 토큰 캐시 디렉터리를 준비하지 못했습니다") from exc

    @staticmethod
    def _restrict_file_permissions(path: Path) -> None:
        """POSIX 0600 또는 Windows 현재 사용자 전용 ACL을 적용한다."""
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        if os.name != "nt":
            return
        username = os.environ.get("USERNAME", "").strip() or getpass.getuser()
        domain = os.environ.get("USERDOMAIN", "").strip()
        identity = f"{domain}\\{username}" if domain else username
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                [
                    "icacls",
                    str(path),
                    "/inheritance:r",
                    "/grant:r",
                    f"{identity}:(F)",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=creation_flags,
            )
        except OSError as exc:
            raise TossAuthError("토스 토큰 파일의 Windows ACL을 설정하지 못했습니다") from exc
        if result.returncode != 0:
            raise TossAuthError("토스 토큰 파일의 Windows ACL을 설정하지 못했습니다")

    def _sync_directory(self) -> None:
        if os.name == "nt":
            return
        descriptor = -1
        try:
            descriptor = os.open(self._cache_path.parent, os.O_RDONLY)
            os.fsync(descriptor)
        except OSError:
            return
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @contextmanager
    def _interprocess_lock(self) -> Iterator[None]:
        self._ensure_cache_directory()
        deadline = self._monotonic_clock() + self._lock_timeout_seconds
        nonce = secrets.token_hex(16)
        acquired = False
        while not acquired:
            try:
                descriptor = os.open(
                    self._lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    stat.S_IRUSR | stat.S_IWUSR,
                )
            except (FileExistsError, PermissionError):
                self._recover_stale_lock()
                if self._monotonic_clock() >= deadline:
                    raise TossAuthError("토스 토큰 잠금 대기 시간이 초과됐습니다")
                self._sleep(self._lock_poll_seconds)
                continue
            except OSError as exc:
                raise TossAuthError("토스 토큰 잠금을 만들지 못했습니다") from exc

            try:
                lock_payload = json.dumps(
                    {
                        "pid": os.getpid(),
                        "created_at_epoch": self._wall_clock(),
                        "nonce": nonce,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                self._restrict_file_permissions(self._lock_path)
                os.write(descriptor, lock_payload)
                os.fsync(descriptor)
                acquired = True
            except OSError as exc:
                raise TossAuthError("토스 토큰 잠금을 기록하지 못했습니다") from exc
            finally:
                os.close(descriptor)
                if not acquired:
                    with suppress(FileNotFoundError):
                        self._lock_path.unlink()

        try:
            yield
        finally:
            self._release_lock(nonce)

    def _recover_stale_lock(self) -> None:
        try:
            first = self._lock_path.stat()
        except FileNotFoundError:
            return
        except OSError:
            return
        age = self._wall_clock() - first.st_mtime
        if not math.isfinite(age) or age <= self._stale_lock_seconds:
            return
        try:
            second = self._lock_path.stat()
            first_marker = (first.st_ino, first.st_mtime_ns, first.st_size)
            second_marker = (second.st_ino, second.st_mtime_ns, second.st_size)
            if first_marker == second_marker:
                self._lock_path.unlink()
        except (FileNotFoundError, OSError):
            return

    def _release_lock(self, nonce: str) -> None:
        try:
            payload = json.loads(self._lock_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and secrets.compare_digest(
                str(payload.get("nonce") or ""), nonce
            ):
                self._lock_path.unlink()
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
            return


_SHARED_MANAGERS: dict[tuple[str, str], TossTokenManager] = {}
_SHARED_MANAGERS_LOCK = threading.Lock()


def get_token_manager() -> TossTokenManager:
    """현재 환경 자격증명·cache 경로에 대한 프로세스 singleton을 반환한다."""
    client_id = os.environ.get("TOSS_CLIENT_ID", "").strip()
    client_secret = os.environ.get("TOSS_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise TossAuthError("TOSS_CLIENT_ID와 TOSS_CLIENT_SECRET이 필요합니다")
    cache_path = _default_cache_path()
    fingerprint = _credential_fingerprint(client_id, client_secret)
    key = (fingerprint, os.path.normcase(str(cache_path)))
    with _SHARED_MANAGERS_LOCK:
        manager = _SHARED_MANAGERS.get(key)
        if manager is None:
            manager = TossTokenManager(
                client_id=client_id,
                client_secret=client_secret,
                cache_path=cache_path,
            )
            _SHARED_MANAGERS[key] = manager
        return manager


def access_token() -> str:
    """공용 manager에서 토스 access token을 반환한다."""
    return get_token_manager().access_token()


def refresh_access_token(*, rejected_token: str) -> str:
    """공용 manager에서 거절된 token을 조건부 갱신한다."""
    return get_token_manager().refresh_access_token(rejected_token=rejected_token)


def authorized_request(
    request: Callable[..., Any],
    *args: Any,
    headers: Mapping[str, str] | None = None,
    **kwargs: Any,
) -> Any:
    """공용 token과 401 단일 갱신을 적용한 HTTP 요청 helper."""
    return get_token_manager().authorized_request(
        request,
        *args,
        headers=headers,
        **kwargs,
    )


def _reset_shared_managers_for_tests() -> None:
    """단위 테스트가 환경별 singleton 상태를 격리하기 위한 내부 helper."""
    with _SHARED_MANAGERS_LOCK:
        _SHARED_MANAGERS.clear()
