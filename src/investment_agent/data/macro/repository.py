"""Macro canonical reader/writer.

코드는 안정적인 ``series_id``라는 이름을 계속 사용하지만 DB fact는 작은
``series_key``를 참조한다. 시장 지표는 한 관측값으로 갱신하고, 경제 발표만 vintage
행을 append한다.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from investment_agent.data.macro.domain.catalog import MARKET_INDICATOR_CATALOG
from investment_agent.data.macro.domain.revisions import Observation, series_as_of
from investment_agent.platform.db.postgres import Database

SCHEMA = "macro"
T_SERIES = "series"
RPC_PRUNE_RELEASES = "prune_release_snapshots"
# 발표가 끝났어도 이 기간 안쪽은 통째로 남긴다 — 그래야 그 시점 판단을 재현할 수 있다.
PRUNE_RECENT_DAYS = 180
T_MEASURES = "measures"
T_MARKET_OBSERVATIONS = "market_observations"
T_ECONOMIC_OBSERVATIONS = "economic_observations"
T_RELEASE_EVENTS = "release_events"
T_RELEASE_SCHEDULE = "release_schedule_versions"
T_FORECASTS = "forecast_snapshots"
T_OBSERVATIONS = T_ECONOMIC_OBSERVATIONS

DOMAIN_MARKET = "market_indicator"
DOMAIN_RELEASE = "economic_release"
DOMAINS = (DOMAIN_MARKET, DOMAIN_RELEASE)


class MacroRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _series_rows(self, series_ids: Sequence[str] | None = None) -> list[dict[str, Any]]:
        if series_ids is None:
            return self._db.select_paged(
                lambda: self._db.table(SCHEMA, T_SERIES).select("series_key,series_code,domain"),
                order_by="series_code",
            )
        return self._db.select_in_chunks(
            schema=SCHEMA, table=T_SERIES, columns="series_key,series_code,domain",
            filter_column="series_code", values=list(series_ids), order_by="series_code",
        )

    def series_ids(self, *, domain: str | None = None) -> list[str]:
        if domain is not None and domain not in DOMAINS:
            raise ValueError(f"unknown domain: {domain!r}")
        rows = self._db.select_paged(
            lambda: self._db.table(SCHEMA, T_SERIES).select("series_code")
            if domain is None else self._db.table(SCHEMA, T_SERIES).select("series_code").eq("domain", domain),
            order_by="series_code",
        )
        return [str(row["series_code"]) for row in rows]

    def market_catalog(self) -> list[dict[str, Any]]:
        """수집 설정은 코드 catalog가 소유한다. DB는 display metadata만 보관한다."""
        return [dict(row) for row in MARKET_INDICATOR_CATALOG]

    def observations(self, series_ids: Sequence[str], *, since: date | None = None) -> list[Observation]:
        meta = self._series_rows(series_ids)
        keys = {int(row["series_key"]): (str(row["series_code"]), str(row["domain"])) for row in meta}
        if not keys:
            return []
        economic = [key for key, (_, domain) in keys.items() if domain == DOMAIN_RELEASE]
        market = [key for key, (_, domain) in keys.items() if domain == DOMAIN_MARKET]
        result: list[Observation] = []
        if market:
            rows = self._db.select_in_chunks(
                schema=SCHEMA, table=T_MARKET_OBSERVATIONS,
                columns="series_key,observation_date,value", filter_column="series_key", values=market,
                configure=(lambda query: query.gte("observation_date", since.isoformat())) if since else None,
                order_by="series_key,observation_date",
            )
            for row in rows:
                code = keys[int(row["series_key"])][0]
                observed = str(row["observation_date"])
                result.append(Observation.from_row({
                    "series_id": code, "ref_period": observed, "value": row["value"],
                    "effective_at": f"{observed}T00:00:00+00:00", "collected_at": f"{observed}T00:00:00+00:00",
                    "time_precision": "date_only",
                }))
        if economic:
            rows = self._db.select_in_chunks(
                schema=SCHEMA, table=T_ECONOMIC_OBSERVATIONS,
                columns="series_key,observation_date,value,vintage_at,available_at,time_precision",
                filter_column="series_key", values=economic,
                configure=(lambda query: query.gte("observation_date", since.isoformat())) if since else None,
                order_by="series_key,observation_date,available_at",
            )
            for row in rows:
                result.append(Observation.from_row({
                    "series_id": keys[int(row["series_key"])][0], "ref_period": row["observation_date"],
                    "value": row["value"], "effective_at": row["vintage_at"],
                    "collected_at": row["available_at"], "time_precision": row["time_precision"],
                }))
        return sorted(result, key=lambda item: (item.series_id, item.ref_period, item.effective_at))

    def values_as_of(self, series_id: str, as_of: datetime, *, since: date | None = None) -> dict[date, float]:
        return series_as_of(self.observations([series_id], since=since), as_of)

    def latest_values(self, series_ids: Sequence[str]) -> dict[str, tuple[date, float]]:
        latest: dict[str, Observation] = {}
        for observation in self.observations(series_ids):
            current = latest.get(observation.series_id)
            if current is None or (observation.ref_period, observation.effective_at) > (current.ref_period, current.effective_at):
                latest[observation.series_id] = observation
        return {key: (item.ref_period, item.value) for key, item in latest.items()}

    def observation_snapshot_as_of(self, as_of_at: datetime, *, lookback_days: int = 800) -> dict[str, Any]:
        catalog = self.market_catalog()
        observed = self.observations([str(row["series_id"]) for row in catalog], since=as_of_at.date() - timedelta(days=lookback_days))
        latest: dict[str, Observation] = {}
        for item in observed:
            if item.known_at(as_of_at):
                current = latest.get(item.series_id)
                if current is None or item.ref_period > current.ref_period:
                    latest[item.series_id] = item
        metadata = {str(row["series_id"]): row for row in catalog}
        rows = [{"series_id": code, "name_ko": metadata[code]["name_ko"], "category": metadata[code]["category"], "unit": metadata[code]["unit"], "series_kind": metadata[code]["series_kind"], "frequency": metadata[code]["frequency"], "obs_date": item.ref_period.isoformat(), "value": item.value, "created_at": item.collected_at.isoformat()} for code, item in sorted(latest.items())]
        return {"run": None if not rows else {"mode": "observation_snapshot", "status": "available", "finished_at": max(row["created_at"] for row in rows)}, "observations": rows}

    def _upsert_catalog(self, table: str, key: str, rows: Iterable[dict[str, Any]]) -> int:
        items = list(rows)
        saved = self._db.select_paged(lambda: self._db.table(SCHEMA, table).select("*"), order_by=key)
        existing = {row[key]: row for row in saved}
        new = []
        changed = 0
        for row in items:
            old = existing.get(row[key])
            if old is None:
                new.append(row)
            elif any(old.get(column) != value for column, value in row.items()):
                self._db.table(SCHEMA, table).update(row).eq(key, row[key]).execute()
                changed += 1
        return changed + self._db.upsert(schema=SCHEMA, table=table, rows=new, on_conflict=key)

    def upsert_series(self, rows: Iterable[dict[str, Any]]) -> int:
        payload = []
        for row in rows:
            source = str(row.get("source") or "")
            # 원천 이름이 비면 그 series는 어디서 온 값인지 말할 수 없다.
            if not source:
                raise ValueError(f"macro catalog series has no source: {row.get('series_id')!r}")
            params = row.get("source_params") or {}
            payload.append({
                "series_code": row["series_id"], "domain": row.get("domain", DOMAIN_MARKET),
                "name_ko": row["name_ko"], "source_code": source,
                "provider_series_code": params.get("fred_id") or params.get("ticker"),
                "frequency": row["frequency"], "unit": row["unit"], "category": row.get("category"),
                "series_kind": row.get("series_kind"), "country": row.get("country"), "timezone": row.get("timezone"),
            })
        return self._upsert_catalog(T_SERIES, "series_code", payload)

    def upcoming_releases(self, *, on_or_after: date) -> list[dict[str, Any]]:
        meta = {int(row["series_key"]): row["series_code"] for row in self._series_rows()}
        rows = self._db.select_paged(lambda: self._db.table(SCHEMA, T_RELEASE_SCHEDULE).select("*"), order_by="series_key,ref_period,collected_at")
        latest = {}
        for row in rows:
            key = (int(row["series_key"]), str(row["ref_period"]))
            if key not in latest or str(row["collected_at"]) > str(latest[key]["collected_at"]):
                latest[key] = row
        return [{**row, "series_id": meta[key[0]]} for key, row in sorted(latest.items())
                if not row.get("is_cancelled") and str(row["scheduled_at"])[:10] >= on_or_after.isoformat()]

    def prune_release_snapshots(self, recent_days: int = PRUNE_RECENT_DAYS) -> dict[str, int]:
        """실제치가 나온 발표의 일정·예상 스냅샷을 계약이 읽는 한 건씩만 남긴다.

        발표 전에는 일정 변경과 예상 변동 자체가 신호지만, 실제치가 나오면 계속
        읽히는 것은 확정된 마지막 일정과 실제치 직전의 예상뿐이다.
        """
        if recent_days < 1:
            raise ValueError("recent_days must be at least 1")
        rows = self._db.rpc(SCHEMA, RPC_PRUNE_RELEASES, {"p_recent_days": recent_days}).execute().data or []
        row = rows[0] if isinstance(rows, list) and rows else (rows if isinstance(rows, dict) else {})
        return {
            "schedules_deleted": int(row.get("schedules_deleted") or 0),
            "forecasts_deleted": int(row.get("forecasts_deleted") or 0),
        }

    def upsert_measures(self, rows: Iterable[dict[str, Any]]) -> int:
        """코드 catalog의 measure를 물리 series_key로 변환해 적재한다."""
        items = [dict(row) for row in rows]
        meta = {str(row["series_code"]): int(row["series_key"]) for row in self._series_rows(
            [str(row["series_id"]) for row in items]
        )}
        payload = []
        for row in items:
            series_id = str(row["series_id"])
            if series_id not in meta:
                raise ValueError(f"macro measure series is not registered: {series_id}")
            payload.append({**{key: row[key] for key in ("measure_id", "name_ko", "unit", "transform", "decimal_places", "is_primary", "rollup_method")}, "series_key": meta[series_id]})
        return self._db.upsert(schema=SCHEMA, table=T_MEASURES, rows=payload, on_conflict="measure_id")

    def record_observations(self, observations: Iterable[Observation], *, source_code: str) -> int:
        items = list(observations)
        meta = {str(row["series_code"]): row for row in self._series_rows([item.series_id for item in items])}
        market_rows, economic_rows = [], []
        for item in items:
            row = meta.get(item.series_id)
            if row is None:
                raise ValueError(f"macro series is not registered: {item.series_id}")
            key = int(row["series_key"])
            if row["domain"] == DOMAIN_MARKET:
                market_rows.append({"series_key": key, "observation_date": item.ref_period.isoformat(), "value": item.value})
            else:
                economic_rows.append({"series_key": key, "observation_date": item.ref_period.isoformat(), "value": item.value, "source_code": source_code, "vintage_at": item.effective_at.isoformat(), "available_at": item.collected_at.isoformat(), "time_precision": item.time_precision})
        return self._db.upsert(schema=SCHEMA, table=T_MARKET_OBSERVATIONS, rows=market_rows, on_conflict="series_key,observation_date") + self._db.upsert(schema=SCHEMA, table=T_ECONOMIC_OBSERVATIONS, rows=economic_rows, on_conflict="series_key,observation_date,vintage_at,available_at")


__all__ = ["DOMAINS", "DOMAIN_MARKET", "DOMAIN_RELEASE", "MacroRepository", "SCHEMA", "T_ECONOMIC_OBSERVATIONS", "T_FORECASTS", "T_MARKET_OBSERVATIONS", "T_MEASURES", "T_OBSERVATIONS", "T_RELEASE_EVENTS", "T_RELEASE_SCHEDULE", "T_SERIES", "RPC_PRUNE_RELEASES"]
