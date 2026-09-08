"""Market 수집 변경 manifest.

가격 fact에 local ingestion timestamp를 중복 저장하지 않는다. feature 재계산이 필요한
최초 거래일은 작은 로컬 manifest가 기록한다.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from investment_agent.platform.storage_paths import (
    MARKET_CHANGE_MANIFEST_PATH_ENV,
    market_change_manifest_path,
)

MANIFEST_PATH_ENV = MARKET_CHANGE_MANIFEST_PATH_ENV
DEFAULT_MANIFEST_PATH = Path("data/local/artifacts/market_change_manifest.json")


def manifest_path() -> Path:
    return market_change_manifest_path()


def earliest_change_since(since: str, *, after_recorded_at: str | None = None) -> str | None:
    path = manifest_path()
    if not path.exists():
        return None
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    dates = [str(row["trade_date"]) for row in rows if str(row.get("trade_date") or "") >= since and (after_recorded_at is None or str(row.get("recorded_at") or "") > after_recorded_at)]
    return min(dates) if dates else None


def record_change_dates(trade_dates: list[str]) -> None:
    values = sorted({str(value) for value in trade_dates if value})
    if not values:
        return
    path = manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, str]] = []
    if path.exists():
        try:
            existing = list(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            existing = []
    now = datetime.now(timezone.utc).isoformat()
    by_date = {str(row.get("trade_date")): row for row in existing}
    for trade_date in values:
        by_date[trade_date] = {"trade_date": trade_date, "recorded_at": now}
    descriptor, temporary_name = tempfile.mkstemp(prefix=".market-change-", suffix=".json", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump([by_date[key] for key in sorted(by_date)], handle, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = ["DEFAULT_MANIFEST_PATH", "MANIFEST_PATH_ENV", "earliest_change_since", "manifest_path", "record_change_dates"]
