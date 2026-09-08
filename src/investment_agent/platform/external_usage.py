"""외부 뉴스·소셜 공급자 호출량을 로컬 메타데이터로만 원자적으로 기록한다."""
from __future__ import annotations

import math
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_DEFAULT_DAILY_CAPS = {
    "alpha_vantage": 25,
    "yfinance": 25,
}
_MAX_DAILY_CAP = 1_000_000
_RETENTION_DAYS = 90

USAGE_LEDGER_PATH_ENV = "AI_INVESTOR_EXTERNAL_USAGE_LEDGER_PATH"
_DEFAULT_ARTIFACT_DIR_ENV = "AI_INVESTOR_ARTIFACT_DIR"
_DEFAULT_ARTIFACT_DIR = "artifacts/ai_investor/tradingagents"


class ExternalUsageError(RuntimeError):
    """일일 한도 설정이나 로컬 원장을 안전하게 사용할 수 없을 때 발생한다."""


def default_ledger_path() -> Path:
    """모든 provider 호출부가 공유해야 하는 사용량 원장 경로를 단일하게 계산한다.

    두 번째 계산식이 생기면 같은 provider의 예약이 서로 다른 파일로 흩어져
    실효 일일 한도가 조용히 배가된다 — 이 함수 하나만 호출부 전체가 쓴다.
    """
    configured = os.environ.get(USAGE_LEDGER_PATH_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    artifact_root = os.environ.get(_DEFAULT_ARTIFACT_DIR_ENV, _DEFAULT_ARTIFACT_DIR).strip()
    if not artifact_root:
        raise ExternalUsageError(f"{_DEFAULT_ARTIFACT_DIR_ENV} must not be empty")
    return Path(artifact_root).expanduser() / "metadata" / "external-usage.sqlite3"


@dataclass(frozen=True)
class UsageReservation:
    """공급자 호출 한 건을 예약한 결과다."""

    provider: str
    usage_date: str
    allowed: bool
    attempts: int
    cap: int
    warning_due: bool = False

    @property
    def remaining(self) -> int:
        return max(self.cap - self.attempts, 0)


def provider_daily_caps(raw: str | None = None) -> dict[str, int]:
    """환경변수의 `provider=cap` 목록을 기본 안전 한도 위에 적용한다."""
    configured = (
        os.environ.get("AI_INVESTOR_EXTERNAL_DAILY_CAPS", "")
        if raw is None
        else str(raw)
    ).strip()
    caps = dict(_DEFAULT_DAILY_CAPS)
    if not configured:
        return caps

    seen: set[str] = set()
    for entry in configured.split(","):
        item = entry.strip()
        if not item or "=" not in item:
            raise ExternalUsageError(
                "AI_INVESTOR_EXTERNAL_DAILY_CAPS must be a comma-separated provider=cap list"
            )
        provider_raw, cap_raw = item.split("=", 1)
        provider = provider_raw.strip().lower()
        if not _PROVIDER_RE.fullmatch(provider):
            raise ExternalUsageError(
                f"invalid provider name in AI_INVESTOR_EXTERNAL_DAILY_CAPS: {provider_raw!r}"
            )
        if provider in seen:
            raise ExternalUsageError(
                f"duplicate provider in AI_INVESTOR_EXTERNAL_DAILY_CAPS: {provider}"
            )
        try:
            cap = int(cap_raw.strip())
        except ValueError as exc:
            raise ExternalUsageError(
                f"daily cap for {provider} must be an integer"
            ) from exc
        if not 1 <= cap <= _MAX_DAILY_CAP:
            raise ExternalUsageError(
                f"daily cap for {provider} must be in [1, {_MAX_DAILY_CAP}]"
            )
        seen.add(provider)
        caps[provider] = cap
    return caps


def provider_daily_cap(provider: str, raw: str | None = None) -> int:
    """활성 공급자에 명시적 일일 한도가 없으면 네트워크 호출을 허용하지 않는다."""
    normalized = str(provider).strip().lower()
    if not _PROVIDER_RE.fullmatch(normalized):
        raise ExternalUsageError(f"invalid external provider name: {provider!r}")
    caps = provider_daily_caps(raw)
    if normalized not in caps:
        raise ExternalUsageError(
            f"no daily cap configured for external provider {normalized!r}; "
            "add it to AI_INVESTOR_EXTERNAL_DAILY_CAPS"
        )
    return caps[normalized]


def reserve_provider_call(
    path: Path | str,
    *,
    provider: str,
    cap: int,
    now: datetime | None = None,
) -> UsageReservation:
    """SQLite 즉시 트랜잭션으로 공급자 호출 슬롯 하나를 원자적으로 예약한다."""
    normalized = str(provider).strip().lower()
    if not _PROVIDER_RE.fullmatch(normalized):
        raise ExternalUsageError(f"invalid external provider name: {provider!r}")
    if not 1 <= int(cap) <= _MAX_DAILY_CAP:
        raise ExternalUsageError(f"daily cap must be in [1, {_MAX_DAILY_CAP}]")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ExternalUsageError("usage ledger timestamp must be timezone-aware")
    current = current.astimezone(timezone.utc)
    usage_date = current.date().isoformat()
    updated_at = current.isoformat()
    cutoff = (current.date() - timedelta(days=_RETENTION_DAYS)).isoformat()
    threshold = max(1, math.ceil(int(cap) * 0.8))

    ledger_path = Path(path).expanduser().resolve()
    try:
        ledger_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(ledger_path.parent, 0o700)
        connection = sqlite3.connect(
            ledger_path,
            timeout=10.0,
            isolation_level=None,
        )
    except (OSError, sqlite3.Error) as exc:
        raise ExternalUsageError("cannot open the external provider usage ledger") from exc

    try:
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_daily_usage (
              usage_date       TEXT    NOT NULL,
              provider         TEXT    NOT NULL,
              attempts         INTEGER NOT NULL CHECK (attempts >= 0),
              cap              INTEGER NOT NULL CHECK (cap > 0),
              warned_threshold INTEGER,
              updated_at       TEXT    NOT NULL,
              PRIMARY KEY (usage_date, provider)
            )
            """
        )
        connection.execute(
            "DELETE FROM provider_daily_usage WHERE usage_date < ?",
            (cutoff,),
        )
        row = connection.execute(
            """
            SELECT attempts, warned_threshold
              FROM provider_daily_usage
             WHERE usage_date = ? AND provider = ?
            """,
            (usage_date, normalized),
        ).fetchone()
        attempts = int(row[0]) if row is not None else 0
        warned_threshold = int(row[1]) if row is not None and row[1] is not None else None

        if attempts >= int(cap):
            connection.execute(
                """
                INSERT INTO provider_daily_usage
                       (usage_date, provider, attempts, cap, warned_threshold, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (usage_date, provider) DO UPDATE SET
                  cap = excluded.cap,
                  updated_at = excluded.updated_at
                """,
                (usage_date, normalized, attempts, int(cap), warned_threshold, updated_at),
            )
            connection.execute("COMMIT")
            return UsageReservation(
                provider=normalized,
                usage_date=usage_date,
                allowed=False,
                attempts=attempts,
                cap=int(cap),
            )

        attempts += 1
        warning_due = attempts >= threshold and warned_threshold != threshold
        next_warned_threshold = threshold if warning_due else warned_threshold
        connection.execute(
            """
            INSERT INTO provider_daily_usage
                   (usage_date, provider, attempts, cap, warned_threshold, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (usage_date, provider) DO UPDATE SET
              attempts = excluded.attempts,
              cap = excluded.cap,
              warned_threshold = excluded.warned_threshold,
              updated_at = excluded.updated_at
            """,
            (
                usage_date,
                normalized,
                attempts,
                int(cap),
                next_warned_threshold,
                updated_at,
            ),
        )
        connection.execute("COMMIT")
        try:
            if os.name != "nt":
                os.chmod(ledger_path, 0o600)
        except OSError:
            # 사용량 원장은 비밀값을 담지 않으므로 호출 예약 성공을 권한 보정 실패로 되돌리지 않는다.
            pass
        return UsageReservation(
            provider=normalized,
            usage_date=usage_date,
            allowed=True,
            attempts=attempts,
            cap=int(cap),
            warning_due=warning_due,
        )
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise ExternalUsageError("cannot atomically update the external provider usage ledger") from exc
    finally:
        connection.close()
