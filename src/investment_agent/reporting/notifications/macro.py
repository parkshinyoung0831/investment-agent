"""매크로 알림용 v1 조회 저장소. 보낼지 말지는 알림 원장이 판단한다."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

import pandas as pd

from investment_agent.platform.clock import kst_today
from investment_agent.config import load_config
from investment_agent.data.macro.repository import MacroRepository
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.logging import get_logger
from investment_agent.reporting.services.macro.constants import CORE_SERIES, WATCH_SERIES
from investment_agent.reporting.services.macro.freshness import freshness_for
from investment_agent.reporting.services.macro.metrics import compute_metrics_series, row_scalars

_WINDOW_DAYS = 400
_SPARK_N = 30
#: 경보 구간(에피소드)을 되짚는 관측 수. 구간이 이보다 길면 시작일을 이 창의 첫날로 본다.
HISTORY_N = 60

log = get_logger(__name__)


def _rows_from_window(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """원천 관측을 카드가 소비하는 최신값+파생지표 행으로 접는다.

    `history`에는 최근 관측마다 경보 판정에 필요한 값(현재·직전 값과 지표)을 남긴다 —
    경보는 "오늘 넘었나"가 아니라 "언제부터 넘어 있나"로 한 번만 알린다.
    """
    by_sid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in raw:
        by_sid[str(row["series_id"])].append(row)

    out: list[dict[str, Any]] = []
    for sid, observations in by_sid.items():
        observations.sort(key=lambda row: str(row["obs_date"]))
        latest = observations[-1]
        values = pd.Series(
            [float(row["value"]) for row in observations],
            index=pd.to_datetime([row["obs_date"] for row in observations]),
        ).dropna()
        if values.empty:
            continue
        metrics = compute_metrics_series(values, latest.get("series_kind") or "")
        current = row_scalars(metrics.iloc[-1]) if not metrics.empty else {}
        previous = row_scalars(metrics.iloc[-2]) if len(metrics) >= 2 else {}
        history = []
        start = max(len(observations) - HISTORY_N, 0)
        for index in range(start, len(observations)):
            history.append({
                "obs_date": str(observations[index]["obs_date"]),
                "curr": float(observations[index]["value"]),
                "prev_value": float(observations[index - 1]["value"]) if index >= 1 else None,
                "metrics": row_scalars(metrics.iloc[index]) if index < len(metrics) else {},
                "prev_metrics": row_scalars(metrics.iloc[index - 1]) if 1 <= index <= len(metrics) else {},
            })
        out.append({
            "series_id": sid,
            "name_ko": latest.get("name_ko"),
            "category": latest.get("category"),
            "unit": latest.get("unit"),
            "series_kind": latest.get("series_kind"),
            "frequency": latest.get("frequency"),
            "obs_date": latest["obs_date"],
            "curr": float(observations[-1]["value"]),
            "prev_value": float(observations[-2]["value"]) if len(observations) >= 2 else None,
            "metrics": current,
            "prev_metrics": previous,
            "spark": [float(row["value"]) for row in observations[-_SPARK_N:]],
            "history": history,
            "freshness": freshness_for(
                latest["obs_date"], str(latest.get("frequency") or "daily")
            ),
        })
    return out


class MacroNotificationStore:
    """매크로 보고서 조회를 담당한다."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._macro = MacroRepository(db)

    @classmethod
    def configured(cls, config: Any | None = None) -> "MacroNotificationStore":
        return cls(Database.from_config(config or load_config()))

    @property
    def database(self) -> Database:
        return self._db

    def _load_window(self, series_ids: tuple[str, ...]) -> list[dict[str, Any]]:
        selected = set(series_ids)
        catalog = {
            str(row["series_id"]): row
            for row in self._macro.market_catalog()
            if str(row["series_id"]) in selected
        }
        since = kst_today() - timedelta(days=_WINDOW_DAYS)
        observations = self._macro.observations(series_ids, since=since)
        raw = []
        for observation in observations:
            info = catalog.get(observation.series_id)
            if info is None:
                log.warning("macro notification skipped unknown series=%s", observation.series_id)
                continue
            raw.append({
                "series_id": observation.series_id,
                "obs_date": observation.ref_period.isoformat(),
                "value": observation.value,
                "name_ko": info.get("name_ko"),
                "category": info.get("category"),
                "unit": info.get("unit"),
                "series_kind": info.get("series_kind"),
                "frequency": info.get("frequency"),
            })
        return _rows_from_window(raw)

    def load_core(self) -> list[dict[str, Any]]:
        return self._load_window(tuple(CORE_SERIES))

    def load_watch(self) -> list[dict[str, Any]]:
        return self._load_window(tuple(WATCH_SERIES))


__all__ = ["HISTORY_N", "MacroNotificationStore", "_rows_from_window"]
