"""Execution lifecycle owner persistence methods."""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone

from investment_agent.execution.contracts import ExecutionSafetyError
from investment_agent.execution.orders.market_state import MarketQuote
from investment_agent.execution.safety.repository import PRIOR_BASELINE_MAX_AGE
from investment_agent.platform.db.sqlite import default_runtime_database_path, runtime_connection
from investment_agent.platform.serialization import parse_datetime


class BrokerRepository:
    def save_broker_order_snapshot(self, row: dict) -> bool:
        payload = dict(row)
        raw = payload.pop("raw_broker_response", None) or payload.pop("raw_response", None)
        if raw:
            payload.update(self._raw_artifact(dict(raw)))
        key = str(payload.get("snapshot_hash") or "")
        if not key:
            raise ExecutionSafetyError("broker snapshot identity is required")
        with runtime_connection() as connection:
            old = self._record(connection, "broker_order_snapshot", key)
            if old is not None:
                if {k: v for k, v in old.items() if k != "observed_at"} != {k: v for k, v in payload.items() if k != "observed_at"}:
                    raise ExecutionSafetyError("broker snapshot conflicts with immutable identity")
                return False
            self._save_record(connection, "broker_order_snapshot", key, payload)
        return True

    def latest_broker_order_snapshot(self, client_order_id: str) -> dict | None:
        """이 주문의 가장 최근 관측. `_incremental_fill_row`가 체결 증분을 계산하는 유일한 근거다."""
        with runtime_connection(read_only=True) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM runtime_records WHERE record_type='broker_order_snapshot'"
            ).fetchall()
        matches = [
            self._decode(row[0]) for row in rows
        ]
        matches = [row for row in matches if row.get("client_order_id") == client_order_id]
        if not matches:
            return None
        return max(matches, key=lambda row: (row["observed_at"], row["snapshot_hash"]))

    def _raw_artifact(cls, payload: dict) -> dict:
        """원본 응답을 내용 주소 파일로 보존하고 원장에는 경로·해시만 남긴다."""
        import os
        data = cls._encode(payload).encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        root = default_runtime_database_path().resolve().parent / "artifacts" / "execution" / "raw"
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"{digest}.json"
        if not target.exists():
            from tempfile import NamedTemporaryFile
            with NamedTemporaryFile(dir=root, delete=False) as stream:
                temporary = stream.name
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ExecutionSafetyError("broker artifact digest mismatch")
        return {"raw_artifact_path": str(target), "raw_sha256": digest}
    def save_fill(self, row: dict) -> None:
        payload = dict(row)
        fill_id = str(payload.get("broker_fill_id") or payload.get("fill_id") or "")
        if not fill_id:
            raise ExecutionSafetyError("fill identity is required")
        if any(not math.isfinite(float(payload[key])) or float(payload[key]) <= 0 for key in ("quantity", "price")):
            raise ExecutionSafetyError("fill quantity and price must be finite and positive")
        payload["filled_at"] = parse_datetime(payload["filled_at"]).isoformat()
        with runtime_connection() as connection:
            old = connection.execute("SELECT payload_json FROM fills WHERE fill_id=?", (fill_id,)).fetchone()
            if old:
                if self._decode(old[0]) != payload:
                    raise ExecutionSafetyError("fill identity conflicts with stored fill")
                return
            connection.execute("INSERT INTO fills(fill_id,broker_order_id,filled_at,quantity,price,payload_json) VALUES(?,?,?,?,?,?)", (fill_id, payload["broker_order_id"], payload["filled_at"], float(payload["quantity"]), float(payload["price"]), self._encode(payload)))
    def save_quote_snapshot(self, quote: MarketQuote, *, purpose: str, source_kind: str = "paper", captured_at: datetime | None = None, metadata: dict | None = None) -> None:
        if not isinstance(quote, MarketQuote):
            raise ExecutionSafetyError("quote snapshot requires MarketQuote")
        payload = quote.to_snapshot_row(purpose=purpose, source_kind=source_kind, captured_at=captured_at, metadata=metadata)
        self._save_auxiliary("quote_snapshot", str(payload["snapshot_id"]), payload)
    def save_account_snapshot(self, row: dict) -> int:
        payload = dict(row)
        moment = parse_datetime(payload.get("captured_at") or datetime.now(timezone.utc))
        captured_at = moment.isoformat()
        try:
            equity = float(payload["equity"])
            cash = float(payload["cash"])
            buying_power = (float(payload["buying_power"])
                            if payload.get("buying_power") is not None else None)
            market_value = float(payload.get("market_value", equity - cash))
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionSafetyError("account snapshot amounts are invalid") from exc
        if any(not math.isfinite(value) for value in (equity, cash, market_value)) or (
            buying_power is not None and not math.isfinite(buying_power)
        ):
            raise ExecutionSafetyError("account snapshot amounts must be finite")
        raw = payload.pop("raw_snapshot", None)
        artifact = self._raw_artifact(dict(raw)) if isinstance(raw, dict) and raw else {}
        payload.update(artifact, captured_at=captured_at)
        key = hashlib.sha256(self._encode({
            "execution_mode": payload.get("execution_mode"),
            "broker_account_hash": payload.get("broker_account_hash"),
            "captured_at": captured_at,
        }).encode()).hexdigest()
        execution_mode = payload.get("execution_mode")
        broker_account_hash = payload.get("broker_account_hash")
        if execution_mode not in ("paper", "live") or not broker_account_hash:
            raise ExecutionSafetyError("account snapshot requires execution_mode and broker_account_hash")
        with runtime_connection() as connection:
            existing = self._record(connection, "performance_snapshot", key)
            if existing is not None and existing != payload:
                raise ExecutionSafetyError("performance snapshot identity conflicts with stored snapshot")
            self._save_record(connection, "performance_snapshot", key, payload)
            self._save_record(connection, "account_snapshot", key, payload)
            connection.execute(
                "INSERT INTO account_snapshots(snapshot_id,broker_account_hash,execution_mode,"
                "snapshot_date,captured_at,cash,market_value,equity,buying_power,"
                "source_artifact_path,source_artifact_sha256) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(broker_account_hash,execution_mode,snapshot_date) DO UPDATE SET "
                "snapshot_id=excluded.snapshot_id,captured_at=excluded.captured_at,cash=excluded.cash,"
                "market_value=excluded.market_value,equity=excluded.equity,"
                "buying_power=excluded.buying_power,source_artifact_path=excluded.source_artifact_path,"
                "source_artifact_sha256=excluded.source_artifact_sha256",
                (key, broker_account_hash, execution_mode, moment.date().isoformat(), captured_at,
                 cash, market_value, equity, buying_power,
                 artifact.get("raw_artifact_path"), artifact.get("raw_sha256")),
            )
            # 주문 전후 위험 계산용 상세점은 짧게 유지하고 장기 사실은 일일 표가 맡는다.
            # 보관 창은 **조회 창과 같은 상수**에서 나온다 — 전에는 보관 2일 · 조회 5일이라
            # 연휴 뒤 첫 장에서 fallback 기준점이 이미 지워져 실주문이 전부 막혔고, 오류 문구는
            # 원인을 "장전 스냅샷을 찍어라"로 돌렸다(감사 EX2-05).
            cutoff = (moment - PRIOR_BASELINE_MAX_AGE).isoformat()
            connection.execute(
                "DELETE FROM runtime_records WHERE record_type='account_snapshot' "
                "AND json_extract(payload_json,'$.captured_at') < ?",
                (cutoff,),
            )
        return int(key[:15], 16)
