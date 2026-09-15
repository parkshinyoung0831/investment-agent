"""S&P 500 멤버십 구간 행을 시점별 스냅샷으로 펼치는 순수 규칙.

Supabase 조회(`universe.persistence`)와 로컬 사본(`data.market.local_mirror`)이 같은 규칙을 쓴다. 두 곳이 따로
구현하면 같은 날짜의 멤버가 저장소에 따라 달라진다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Mapping, Sequence

# 한 시점의 멤버 수가 이 범위를 벗어나면 구간 행이 빠졌거나 겹친 것이다.
MEMBER_COUNT_RANGE = (450, 520)


def membership_snapshots(
    rows: Sequence[Mapping[str, Any]],
    *,
    start_date: date,
    end_date: date,
    source: str = "universe.index_memberships",
) -> list[dict]:
    """구간 행(`security_id`·`ticker`·`valid_from`·`valid_to`)을 시작일과 변경일마다의 스냅샷으로 만든다."""
    if end_date < start_date:
        raise ValueError("historical membership end_date must not precede start_date")
    usable = [row for row in rows if str(row["valid_from"]) <= end_date.isoformat()]
    boundaries = {start_date.isoformat()}
    boundaries.update(str(value) for row in usable for value in (row["valid_from"], row.get("valid_to"))
                      if value and start_date.isoformat() < str(value) <= end_date.isoformat())
    result = []
    for boundary in sorted(boundaries):
        active = [row for row in usable
                  if str(row["valid_from"]) <= boundary and (not row.get("valid_to") or boundary < str(row["valid_to"]))]
        ids = sorted(int(row["security_id"]) for row in active)
        tickers = sorted({str(row.get("ticker") or "").upper() for row in active})
        low, high = MEMBER_COUNT_RANGE
        if "" in tickers or len(ids) != len(set(ids)) or len(tickers) != len(ids) or not low <= len(ids) <= high:
            raise RuntimeError("point-in-time S&P 500 membership is unavailable or inconsistent")
        digest = hashlib.sha256(json.dumps({"date": boundary, "security_ids": ids}, sort_keys=True).encode()).hexdigest()
        result.append({
            "effective_date": boundary,
            "symbols": tickers,
            "security_ids": ids,
            "member_count": len(tickers),
            "source": source,
            "source_hash": digest,
        })
    return result


__all__ = ["MEMBER_COUNT_RANGE", "membership_snapshots"]
