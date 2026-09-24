"""로컬 사본(Parquet)의 읽기·쓰기. Supabase 조회 함수와 같은 모양의 결과를 돌려준다.

```
data/local/mirror/
  manifest.json        동기화 시각·가격 최신일·행 수
  securities.parquet   universe.securities + 산업분류(sic_division)
  memberships.parquet  S&P 500 멤버십 구간
  prices.parquet       market.prices_daily (가격 대상 종목)
  actions.parquet      market.actions_daily (배당·분할)
```

운영 DB의 가격 이력은 적재했던 백필 창만큼이다. 그보다 오래된 봉·기업행위는 `market_history/yahoo/<security_id>/daily.parquet`
(`commands/archive_long_history`)에서 읽을 때 채운다 — 종목마다 사본의 첫 날짜보다 앞선 날만 쓰므로 두 원천이
겹치는 날은 언제나 운영 DB 값이다. 사본 파일 자체에는 섞지 않는다(사본은 Supabase의 복사본이다).

- 결과 모양은 Supabase 경로(`data.market.persistence.price_history_as_of`,
  `data.universe.persistence.select_sp500_membership_snapshots` 등)와 같다. 부르는 쪽은 어느 저장소에서 왔는지
  몰라도 된다(동등성은 테스트가 강제).
- 파일은 임시 파일에 쓴 뒤 교체한다. 동기화 도중 읽어도 반쯤 쓴 파일을 보지 않는다.
- 판단 시각이 사본 동기화 시각보다 뒤인데 사본이 `max_age`보다 오래됐으면 쓰지 않는다(`covers`). 부르는 쪽이
  Supabase로 돌아간다 — 오래된 사본으로 조용히 판단하지 않는다.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from investment_agent.data.market.domain.actions import merge_corporate_actions
from investment_agent.data.universe.domain.memberships import membership_snapshots
from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import parse_datetime
from investment_agent.platform.storage_paths import local_mirror_root

log = get_logger(__name__)

MIRROR_VERSION = "local-mirror-v1"
MANIFEST = "manifest.json"
T_SECURITIES = "securities"
T_MEMBERSHIPS = "memberships"
T_PRICES = "prices"
T_ACTIONS = "actions"
TABLES = (T_SECURITIES, T_MEMBERSHIPS, T_PRICES, T_ACTIONS)
# 동기화 뒤 이 시간이 지나면 "지금" 판단에는 쓰지 않는다. 하네스가 몇 시간마다 증분 동기화한다.
DEFAULT_MAX_AGE = timedelta(hours=30)
_PRICE_COLUMNS = ("security_id", "trade_date", "open", "high", "low", "close", "volume", "is_repaired")


def mirror_root() -> Path:
    return local_mirror_root()


@dataclass(frozen=True)
class MirrorManifest:
    synced_at: datetime
    price_through: str | None
    counts: Mapping[str, int]
    # 가격 전체 이력을 마지막으로 다시 받은 시각. 증분이 못 잡는 과거 정정(분할 재기준 등)을 주기적으로 덮는다.
    full_synced_at: datetime | None = None
    version: str = MIRROR_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {"synced_at": self.synced_at.isoformat(), "price_through": self.price_through,
                "counts": dict(self.counts), "version": self.version,
                "full_synced_at": self.full_synced_at.isoformat() if self.full_synced_at else None}


def _write_atomically(frame: pd.DataFrame, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.stem}.", suffix=".parquet", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, engine="pyarrow")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


class LocalMirror:
    """사본 한 벌. 읽기는 처음 한 번 메모리에 올리고, 같은 프로세스 안에서 재사용한다."""

    def __init__(self, root: Path | str | None = None, *, history_root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else mirror_root()
        # 긴 이력 archive. 기본 사본을 쓸 때만 기본 archive를 붙인다 — 임시 사본(테스트)이 실제 archive를 읽지 않게.
        if history_root is not None:
            self.history_root: Path | None = Path(history_root)
        elif root is None:
            from investment_agent.data.market.infrastructure.archive import archive_root

            self.history_root = archive_root() / "yahoo"
        else:
            self.history_root = None
        self._lock = threading.Lock()
        self._frames: dict[str, pd.DataFrame] = {}
        self._price_index: dict[int, Any] | None = None
        self._action_index: dict[int, Any] | None = None
        self._ticker_ids: dict[str, int] | None = None

    # ── 상태 ──────────────────────────────────────────────────────────────
    def manifest(self) -> MirrorManifest | None:
        path = self.root / MANIFEST
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("version") != MIRROR_VERSION:
                return None
            full = payload.get("full_synced_at")
            return MirrorManifest(parse_datetime(payload["synced_at"]), payload.get("price_through"),
                                  dict(payload.get("counts") or {}), parse_datetime(full) if full else None)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def covers(self, as_of_at: datetime, *, now: datetime | None = None, max_age: timedelta = DEFAULT_MAX_AGE) -> bool:
        """이 판단 시각을 사본으로 답해도 되는가.

        동기화 시각 이전의 판단(과거 재현)은 언제나 된다. 그 뒤의 판단은 사본이 `max_age` 안에 동기화됐을 때만
        된다 — 그동안 적재된 봉은 다음 동기화에 들어온다.
        """
        manifest = self.manifest()
        if manifest is None or not all((self.root / f"{name}.parquet").exists() for name in TABLES):
            return False
        if as_of_at <= manifest.synced_at:
            return True
        current = now or datetime.now(timezone.utc)
        return current - manifest.synced_at <= max_age

    # ── 쓰기 ──────────────────────────────────────────────────────────────
    def write(self, tables: Mapping[str, pd.DataFrame], *, synced_at: datetime, is_full: bool = False) -> MirrorManifest:
        """표를 교체하고 마지막에 manifest를 쓴다. manifest가 없으면 사본 전체를 쓰지 않은 것으로 본다."""
        unknown = set(tables) - set(TABLES)
        if unknown:
            raise ValueError(f"unknown mirror tables: {sorted(unknown)}")
        for name, frame in tables.items():
            _write_atomically(frame.reset_index(drop=True), self.root / f"{name}.parquet")
        prices = tables.get(T_PRICES)
        if prices is None and (self.root / f"{T_PRICES}.parquet").exists():
            prices = pd.read_parquet(self.root / f"{T_PRICES}.parquet", columns=["trade_date"])
        counts = {name: int(len(frame)) for name, frame in tables.items()}
        previous = self.manifest()
        merged_counts = {**(dict(previous.counts) if previous else {}), **counts}
        manifest = MirrorManifest(synced_at, str(prices["trade_date"].max()) if prices is not None and len(prices) else None,
                                  merged_counts, synced_at if is_full else (previous.full_synced_at if previous else None))
        target = self.root / MANIFEST
        temporary = target.with_suffix(".pending.json")
        temporary.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temporary, target)
        with self._lock:
            self._frames.clear()
            self._price_index = self._action_index = self._ticker_ids = None
        return manifest

    # ── 읽기 ──────────────────────────────────────────────────────────────
    def frame(self, name: str) -> pd.DataFrame:
        with self._lock:
            if name not in self._frames:
                self._frames[name] = pd.read_parquet(self.root / f"{name}.parquet", engine="pyarrow")
            return self._frames[name]

    def _securities(self) -> list[dict[str, Any]]:
        return self.frame(T_SECURITIES).to_dict("records")

    def security_ids(self, tickers: Sequence[str]) -> dict[str, int]:
        """ticker → security_id. 같은 ticker 후보가 여럿이면 상장 중 → 신원 확인 → 최근 발급 순(universe와 같은 규칙)."""
        if self._ticker_ids is None:
            best: dict[str, tuple[tuple[bool, bool, int], int]] = {}
            for row in self._securities():
                ticker = str(row["ticker"]).upper()
                key = (bool(row["is_active_listing"]), bool(row["is_identity_verified"]), int(row["security_id"]))
                if ticker not in best or key > best[ticker][0]:
                    best[ticker] = (key, int(row["security_id"]))
            self._ticker_ids = {ticker: value[1] for ticker, value in best.items()}
        return {str(ticker).upper(): self._ticker_ids[str(ticker).upper()]
                for ticker in tickers if str(ticker).upper() in self._ticker_ids}

    def tracked_tickers(self) -> list[str]:
        return sorted({str(row["ticker"]).upper() for row in self._securities() if row["is_tracked"]})

    def sector_map(self, tickers: Sequence[str]) -> dict[str, str]:
        """추적 중인 종목의 SIC division. universe의 `select_security_profiles(tracked_only=True)`와 같은 대상이다."""
        preferred = self.security_ids(tickers)
        by_id = {int(row["security_id"]): row for row in self._securities()}
        output: dict[str, str] = {}
        for ticker, security_id in preferred.items():
            row = by_id[security_id]
            if row["is_tracked"] and row.get("sic_division"):
                output[ticker] = str(row["sic_division"])
        return output

    def membership_snapshots(self, *, start_date: date, end_date: date) -> list[dict]:
        rows = [{**row, "valid_to": row["valid_to"] if isinstance(row.get("valid_to"), str) and row["valid_to"] else None}
                for row in self.frame(T_MEMBERSHIPS).to_dict("records")]
        return membership_snapshots(rows, start_date=start_date, end_date=end_date)

    def _indexes(self) -> tuple[dict[int, Any], dict[int, Any]]:
        with self._lock:
            if self._price_index is None:
                prices = self._frames.get(T_PRICES)
                if prices is None:
                    prices = pd.read_parquet(self.root / f"{T_PRICES}.parquet", engine="pyarrow")
                    actions = pd.read_parquet(self.root / f"{T_ACTIONS}.parquet", engine="pyarrow")
                    try:
                        prices, actions = _with_long_history(prices, actions, self.history_root)
                    except Exception as exc:  # noqa: BLE001 - 긴 이력은 보조다. 운영 DB 사본만으로도 판단은 돈다
                        log.warning("long history archive not merged: %s: %s", type(exc).__name__, exc)
                    prices = prices.sort_values(["security_id", "trade_date"]).reset_index(drop=True)
                    self._frames[T_PRICES] = prices
                    self._frames[T_ACTIONS] = actions
                self._price_index = prices.groupby("security_id").indices
                actions = self._frames.get(T_ACTIONS)
                if actions is None:
                    actions = pd.read_parquet(self.root / f"{T_ACTIONS}.parquet", engine="pyarrow")
                    self._frames[T_ACTIONS] = actions
                self._action_index = actions.groupby("security_id").indices
            return self._price_index, self._action_index or {}

    def price_history_as_of(self, ticker: str, as_of_at: datetime, *, limit: int = 260) -> list[dict]:
        """판단일까지의 마지막 `limit`개 봉과 그 구간의 배당·분할(`market.persistence.price_history_as_of`와 같은 모양)."""
        if as_of_at.tzinfo is None:
            raise ValueError("as_of_at must include timezone")
        security_id = self.security_ids([ticker]).get(str(ticker).upper())
        if security_id is None:
            return []
        price_index, action_index = self._indexes()
        positions = price_index.get(security_id)
        if positions is None:
            return []
        end = as_of_at.date().isoformat()
        prices = self._frames[T_PRICES].iloc[positions]
        prices = prices[prices["trade_date"] <= end].tail(limit)
        if prices.empty:
            return []
        rows = [
            {"ticker": ticker.upper(), **{column: _python(record[column]) for column in _PRICE_COLUMNS}}
            for record in prices.to_dict("records")
        ]
        first, last = rows[0]["trade_date"], rows[-1]["trade_date"]
        dividends: list[dict] = []
        splits: list[dict] = []
        action_positions = action_index.get(security_id)
        if action_positions is not None:
            for record in self._frames[T_ACTIONS].iloc[action_positions].to_dict("records"):
                day = str(record["action_date"])
                if not first <= day <= last:
                    continue
                if pd.notna(record.get("dividend_amount")):
                    dividends.append({"ticker": ticker.upper(), "ex_date": day, "div_amount": float(record["dividend_amount"])})
                if pd.notna(record.get("split_ratio")):
                    splits.append({"ticker": ticker.upper(), "action_date": day, "split_ratio": float(record["split_ratio"])})
        return merge_corporate_actions(rows, dividends, splits)

    def split_histories(self, tickers: Sequence[str]) -> dict[str, list[dict]]:
        """사본의 분할 이력을 여러 ticker에 한 번에 나눠 돌려준다."""
        ids = self.security_ids(tickers)
        _price_index, action_index = self._indexes()
        output: dict[str, list[dict]] = {str(ticker).upper(): [] for ticker in tickers}
        for ticker, security_id in ids.items():
            positions = action_index.get(security_id)
            if positions is None:
                continue
            output[ticker] = [
                {"ticker": ticker, "action_date": str(row["action_date"]),
                 "split_ratio": float(row["split_ratio"])}
                for row in self._frames[T_ACTIONS].iloc[positions].to_dict("records")
                if pd.notna(row.get("split_ratio"))
            ]
        return output

    def closes_between(self, tickers: Sequence[str], *, start: date, end: date) -> list[dict]:
        """라벨 계산용 원시 종가 창을 여러 ticker에서 한 번에 읽는다."""
        if end < start:
            raise ValueError("close window end must not precede start")
        ids = self.security_ids(tickers)
        price_index, _action_index = self._indexes()
        output: list[dict] = []
        for ticker, security_id in ids.items():
            positions = price_index.get(security_id)
            if positions is None:
                continue
            rows = self._frames[T_PRICES].iloc[positions]
            rows = rows[(rows["trade_date"] >= start.isoformat()) & (rows["trade_date"] <= end.isoformat())]
            output.extend({"ticker": ticker, "trade_date": str(row["trade_date"]), "close": float(row["close"])}
                          for row in rows.to_dict("records") if pd.notna(row.get("close")))
        return sorted(output, key=lambda row: (row["ticker"], row["trade_date"]))


def _with_long_history(prices: pd.DataFrame, actions: pd.DataFrame,
                       history_root: Path | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """사본보다 오래된 봉과 그 기간의 배당·분할을 archive에서 앞에 붙인다.

    archive 종가는 사본과 같은 분할 기준(provider의 split-normalized close)이다. 종목마다 사본의 첫 날짜 전
    봉만 쓰고, 기업행위는 사본에 없는 날짜만 더한다.
    """
    if history_root is None or not history_root.is_dir():
        return prices, actions
    # 디렉터리 이름이 security_id인 파일만 읽는다. 이전 세대의 ticker 경로 파일(`yahoo/AAPL/`)은 신원이 없다.
    files = sorted(path for path in history_root.glob("*/daily.parquet") if path.parent.name.isdigit())
    if not files:
        return prices, actions
    columns = {"security_id": "float64", "trade_date": "object", "open": "float64", "high": "float64",
               "low": "float64", "close": "float64", "volume": "float64", "div_amount": "float64",
               "split_ratio": "float64"}
    frames = [
        frame.reindex(columns=list(columns)).astype(columns)
        for frame in (pd.read_parquet(path, engine="pyarrow") for path in files) if not frame.empty
    ]
    if not frames:
        return prices, actions
    history = pd.concat(frames, ignore_index=True)
    history = history.dropna(subset=["security_id", "trade_date", "close"])
    if history.empty:
        return prices, actions
    history["security_id"] = history["security_id"].astype("int64")
    history["trade_date"] = pd.to_datetime(history["trade_date"]).dt.strftime("%Y-%m-%d")
    first = prices.groupby("security_id")["trade_date"].min()
    cutoff = history["security_id"].map(first)
    older = history[cutoff.isna() | (history["trade_date"] < cutoff.fillna(""))]
    bars = older.loc[:, ["security_id", "trade_date", "open", "high", "low", "close", "volume"]].copy()
    bars["volume"] = bars["volume"].fillna(0).round().astype("int64")
    bars["is_repaired"] = False
    merged_prices = pd.concat([bars, prices], ignore_index=True)

    events = older.loc[older["div_amount"].notna() | older["split_ratio"].notna(),
                       ["security_id", "trade_date", "split_ratio", "div_amount"]]
    events = events.rename(columns={"trade_date": "action_date", "div_amount": "dividend_amount"})
    known = set(zip(actions["security_id"], actions["action_date"]))
    events = events[[key not in known for key in zip(events["security_id"], events["action_date"])]]
    events = events.astype({column: actions[column].dtype for column in events.columns if column in actions})
    merged_actions = pd.concat([actions, events], ignore_index=True) if len(events) else actions
    return merged_prices, merged_actions


def _python(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


__all__ = [
    "DEFAULT_MAX_AGE",
    "LocalMirror",
    "MIRROR_VERSION",
    "MirrorManifest",
    "TABLES",
    "mirror_root",
]
