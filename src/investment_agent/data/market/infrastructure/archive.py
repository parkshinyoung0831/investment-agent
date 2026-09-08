"""Yahoo 원본 일봉 Parquet archive.

운영 DB는 조회 비용을 위해 보존 형태를 바꿀 수 있지만, provider가 준 원본 일봉은
백필 write 전에 별도 artifact에 남긴다. archive 실패는 DB write보다 먼저 실패한다.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

ARCHIVE_ENV = "INVESTMENT_AGENT_MARKET_ARCHIVE_DIR"
DEFAULT_ARCHIVE_ROOT = Path("artifacts/market_history")
_COLUMNS = (
    "ticker", "trade_date", "open", "high", "low", "close", "adj_close",
    "volume", "div_amount", "split_ratio", "source",
)


class MarketArchiveError(RuntimeError):
    """원본 시세 archive를 안전하게 기록할 수 없다."""


def archive_root(root: str | Path | None = None) -> Path:
    """명시한 영속 볼륨 또는 프로젝트 artifact root를 반환한다."""
    configured = root if root is not None else os.environ.get(ARCHIVE_ENV)
    return Path(configured).expanduser() if configured else DEFAULT_ARCHIVE_ROOT


def _frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        raise MarketArchiveError("cannot archive an empty market response")
    frame = pd.DataFrame(rows).copy()
    missing = [column for column in ("ticker", "trade_date", "close") if column not in frame]
    if missing:
        raise MarketArchiveError(f"market archive rows missing columns: {missing}")
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    if (frame["ticker"] == "").any():
        raise MarketArchiveError("market archive has an empty ticker")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.date
    for column in _COLUMNS:
        if column not in frame:
            frame[column] = None
    frame = frame.loc[:, _COLUMNS].drop_duplicates(["ticker", "trade_date"], keep="last")
    return frame.sort_values(["ticker", "trade_date"]).reset_index(drop=True)


def _write_atomically(frame: pd.DataFrame, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}.", suffix=".parquet", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, engine="pyarrow")
        os.replace(temporary, target)
    except (OSError, ValueError, ImportError) as exc:
        raise MarketArchiveError(
            f"market archive write failed for {target}: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def archive_daily_rows(rows: list[dict[str, Any]], *, root: str | Path | None = None) -> int:
    """ticker별 full daily snapshot을 merge해 원자적으로 교체한다.

    백필은 항상 이 함수를 먼저 호출한다. 새 응답은 같은 ticker/date의 이전 관측을
    대체하고, 받지 않은 과거 일봉은 남긴다.
    """
    incoming = _frame(rows)
    destination = archive_root(root)
    try:
        for ticker, current in incoming.groupby("ticker", sort=True):
            target = destination / "yahoo" / str(ticker) / "daily.parquet"
            if target.exists():
                existing = pd.read_parquet(target, engine="pyarrow")
                merged = pd.concat([_frame(existing.to_dict("records")), current], ignore_index=True)
                current = _frame(merged.to_dict("records"))
            _write_atomically(current, target)
    except MarketArchiveError:
        raise
    except (OSError, ValueError, ImportError) as exc:
        raise MarketArchiveError(
            f"market archive failed: {type(exc).__name__}: {exc}"
        ) from exc
    return len(incoming)


__all__ = ["ARCHIVE_ENV", "DEFAULT_ARCHIVE_ROOT", "MarketArchiveError", "archive_daily_rows", "archive_root"]
