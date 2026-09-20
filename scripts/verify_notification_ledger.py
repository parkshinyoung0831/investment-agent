"""알림 원장 SQL 함수가 `MemoryLedger`와 같은 규칙으로 동작하는지 실DB에서 확인한다.

단위 테스트는 DB를 때리지 않으므로 엔진 테스트는 `notifications/ledger.py`의 MemoryLedger로
돈다. 그 구현이 `db/postgres/v1/60_notifications.sql`과 어긋나면 테스트는 초록인데 운영에서만
중복·누락이 난다. 이 스크립트는 같은 시나리오를 두 구현에 똑같이 태워 결과를 대조한다.

실DB에는 전용 probe topic(`probe.ledger_check`)의 행만 만들고 끝나면 지운다.
    python scripts/verify_notification_ledger.py
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


PROBE_TOPIC = "probe.ledger_check"
A, B = ("A", "1"), ("B", "1")
REV_1, REV_2 = "a" * 64, "d" * 64


def _item(key: tuple[str, str], revision: str, fact_at: datetime) -> dict:
    return {"subject": key[0], "occurrence": key[1], "revision": revision, "fact_at": fact_at.isoformat()}


def scenario(ledger, now: datetime) -> list[tuple[str, object]]:
    """두 구현에 똑같이 태울 단계. 각 단계의 관찰값을 돌려준다."""
    recent, ancient = now - timedelta(minutes=1), datetime(2000, 1, 1, tzinfo=timezone.utc)
    out: list[tuple[str, object]] = []

    def actions(reservations):
        return sorted((r.subject, r.action) for r in reservations)

    out.append(("first reserve", actions(ledger.reserve(
        PROBE_TOPIC, [_item(A, REV_1, recent), _item(B, REV_1, ancient)], owner="o1", lease_seconds=60, revisable=False))))
    out.append(("concurrent reserve", actions(ledger.reserve(
        PROBE_TOPIC, [_item(A, REV_1, recent)], owner="o2", lease_seconds=60, revisable=False))))
    out.append(("begin by stranger", ledger.begin_send(PROBE_TOPIC, [A], owner="o2")))
    out.append(("begin by owner", ledger.begin_send(PROBE_TOPIC, [A], owner="o1")))
    out.append(("finish sent", ledger.finish(PROBE_TOPIC, [A], owner="o1", action="create", outcome="sent",
                                             location_id="111", message_id="222", failure_code=None, retry_seconds=None)))
    out.append(("same content", actions(ledger.reserve(
        PROBE_TOPIC, [_item(A, REV_1, recent)], owner="o3", lease_seconds=60, revisable=True))))
    out.append(("edit on change", actions(ledger.reserve(
        PROBE_TOPIC, [_item(A, REV_2, recent), _item(B, REV_2, ancient)], owner="o4", lease_seconds=60, revisable=True))))
    out.append(("finish edit failed", ledger.finish(PROBE_TOPIC, [A], owner="o4", action="edit", outcome="failed",
                                                    location_id=None, message_id=None, failure_code="x", retry_seconds=3600)))
    out.append(("finish create unknown", ledger.finish(PROBE_TOPIC, [B], owner="o4", action="create", outcome="unknown",
                                                       location_id=None, message_id=None, failure_code="y", retry_seconds=None)))
    out.append(("retry not due, unknown held", actions(ledger.reserve(
        PROBE_TOPIC, [_item(A, REV_2, recent), _item(B, REV_2, ancient)], owner="o5", lease_seconds=60, revisable=True))))
    out.append(("replay unknown", ledger.replay(PROBE_TOPIC, *B)))
    out.append(("after replay", actions(ledger.reserve(
        PROBE_TOPIC, [_item(B, REV_2, ancient)], owner="o6", lease_seconds=60, revisable=True))))
    known = ledger.last_known(PROBE_TOPIC, "A")
    out.append(("last known", None if known is None else (known.occurrence, known.revision[:4])))
    states = ledger.states(PROBE_TOPIC, [A, B])
    out.append(("states", sorted((key, state.status) for key, state in states.items())))
    return out


def main() -> int:
    from investment_agent.config import load_config
    from investment_agent.notifications.db import SCHEMA, T_NOTICES, T_TOPICS, PostgresNotificationLedger
    from investment_agent.notifications.ledger import MemoryLedger
    from investment_agent.platform.db.postgres import Database

    database = Database.from_config(load_config())
    now = datetime.now(timezone.utc)
    baseline = now - timedelta(days=1)
    real = PostgresNotificationLedger(database)
    memory = MemoryLedger()
    memory.ensure_baseline(PROBE_TOPIC, baseline)

    def cleanup() -> None:
        database.table(SCHEMA, T_NOTICES).delete().eq("topic", PROBE_TOPIC).execute()
        database.table(SCHEMA, T_TOPICS).delete().eq("topic", PROBE_TOPIC).execute()

    cleanup()
    try:
        real.ensure_baseline(PROBE_TOPIC, baseline)
        expected, observed = scenario(memory, now), scenario(real, datetime.now(timezone.utc))
    finally:
        cleanup()

    mismatches = 0
    for (step, want), (_step, got) in zip(expected, observed):
        same = want == got
        mismatches += not same
        print(f"{'OK  ' if same else 'DIFF'} {step}: memory={want} postgres={got}")
    print(f"run={uuid.uuid4().hex[:8]} mismatches={mismatches}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
