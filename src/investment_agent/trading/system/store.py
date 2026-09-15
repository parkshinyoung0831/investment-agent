"""System Portfolio 원장(로컬 SQLite `system_*` 표)의 읽기·쓰기 경계."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from investment_agent.platform.db.sqlite import runtime_connection
from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.system.accounting import DailyMark

T_TARGETS = "system_targets"
T_NAV = "system_nav"


@dataclass(frozen=True)
class SystemTargetRecord:
    target_id: str
    decided_at: str
    factor_snapshot_as_of: str
    proposal_id: str
    risk_decision_id: str
    model_artifact_id: str
    is_approved: bool
    weights: dict[str, float]
    applied_session: str | None
    detail: dict[str, Any]


def _target(row) -> SystemTargetRecord:
    return SystemTargetRecord(str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]), str(row[5]),
                              bool(row[6]), json.loads(row[7]), row[8], json.loads(row[9]))


_TARGET_COLUMNS = ("target_id,decided_at,factor_snapshot_as_of,proposal_id,risk_decision_id,model_artifact_id,"
                   "is_approved,weights_json,applied_session,detail_json")
_NAV_COLUMNS = ("trade_date,nav,daily_return,benchmark_nav,benchmark_close,turnover,cost,weights_json,closes_json,"
                "applied_target_id,stale_price_tickers_json")


def _mark(row) -> DailyMark:
    return DailyMark(
        trade_date=str(row[0]), nav=float(row[1]), daily_return=float(row[2]), benchmark_nav=float(row[3]),
        benchmark_close=float(row[4]), turnover=float(row[5]), cost=float(row[6]), weights=json.loads(row[7]),
        closes=json.loads(row[8]), applied_target_id=row[9], stale_price_tickers=tuple(json.loads(row[10])),
    )


class SystemPortfolioStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = path

    def _connect(self):
        # 읽기도 쓰기 연결로 연다. 읽기 전용 연결은 선언을 적용하지 않아, 표가 생기기 전의 원장에서 실패한다.
        return runtime_connection(self.path)

    # ── 목표 ──────────────────────────────────────────────────────────────
    def record_target(self, *, target_id: str, decided_at: datetime, factor_snapshot_as_of: str, proposal_id: str,
                      risk_decision_id: str, model_artifact_id: str, is_approved: bool,
                      weights: Mapping[str, float], detail: Mapping[str, Any]) -> None:
        """같은 목표를 두 번 기록하지 않는다."""
        with self._connect() as connection:
            connection.execute(
                f"INSERT INTO {T_TARGETS}({_TARGET_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,NULL,?)"
                " ON CONFLICT(target_id) DO NOTHING",
                (target_id, decided_at.isoformat(), factor_snapshot_as_of, proposal_id, risk_decision_id,
                 model_artifact_id, int(bool(is_approved)), canonical_json(dict(weights) if is_approved else {}),
                 canonical_json(dict(detail))),
            )

    def latest_target(self, *, approved_only: bool = False) -> SystemTargetRecord | None:
        where = " WHERE is_approved=1" if approved_only else ""
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {_TARGET_COLUMNS} FROM {T_TARGETS}{where} ORDER BY decided_at DESC, target_id DESC LIMIT 1"
            ).fetchone()
        return _target(row) if row else None

    def pending_target(self) -> SystemTargetRecord | None:
        """승인됐지만 아직 NAV에 반영되지 않은 가장 최근 목표."""
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {_TARGET_COLUMNS} FROM {T_TARGETS} WHERE is_approved=1 AND applied_session IS NULL"
                " ORDER BY decided_at DESC, target_id DESC LIMIT 1"
            ).fetchone()
        return _target(row) if row else None

    def target(self, target_id: str) -> SystemTargetRecord | None:
        with self._connect() as connection:
            row = connection.execute(f"SELECT {_TARGET_COLUMNS} FROM {T_TARGETS} WHERE target_id=?",
                                     (target_id,)).fetchone()
        return _target(row) if row else None

    def targets(self, *, limit: int = 50) -> list[SystemTargetRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {_TARGET_COLUMNS} FROM {T_TARGETS} ORDER BY decided_at DESC, target_id DESC LIMIT ?", (limit,),
            ).fetchall()
        return [_target(row) for row in rows]

    # ── NAV ───────────────────────────────────────────────────────────────
    def record_mark(self, mark: DailyMark) -> None:
        """평가 한 날과 그날 적용한 목표 표시를 한 트랜잭션으로 남긴다."""
        with self._connect() as connection:
            connection.execute(
                f"INSERT INTO {T_NAV}({_NAV_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (mark.trade_date, mark.nav, mark.daily_return, mark.benchmark_nav, mark.benchmark_close,
                 mark.turnover, mark.cost, canonical_json(mark.weights), canonical_json(mark.closes),
                 mark.applied_target_id, json.dumps(list(mark.stale_price_tickers))),
            )
            if mark.applied_target_id:
                connection.execute(
                    f"UPDATE {T_TARGETS} SET applied_session=? WHERE target_id=? AND applied_session IS NULL",
                    (mark.trade_date, mark.applied_target_id),
                )

    def latest_mark(self) -> DailyMark | None:
        with self._connect() as connection:
            row = connection.execute(f"SELECT {_NAV_COLUMNS} FROM {T_NAV} ORDER BY trade_date DESC LIMIT 1").fetchone()
        return _mark(row) if row else None

    def history(self) -> list[DailyMark]:
        with self._connect() as connection:
            rows = connection.execute(f"SELECT {_NAV_COLUMNS} FROM {T_NAV} ORDER BY trade_date").fetchall()
        return [_mark(row) for row in rows]

    def held_tickers(self) -> list[str]:
        """System이 지금 보유한 종목. 분석 대상 선정이 실계좌 대신 이것을 본다."""
        mark = self.latest_mark()
        return list(mark.held_tickers) if mark else []


__all__ = ["SystemPortfolioStore", "SystemTargetRecord", "T_NAV", "T_TARGETS"]
