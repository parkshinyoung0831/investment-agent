"""SEC·S&P500·Toss 수집 흐름을 조율한다."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from investment_agent.platform.logging import get_logger
from collections.abc import Callable
from typing import Any
from investment_agent.data.universe import persistence as db
from investment_agent.data.universe.infrastructure.sources.sec_entities import (
    fetch_entity_results,
    fetch_exchange_listed_tickers,
)
from investment_agent.data.universe.infrastructure.sources.toss import fetch_korean_names as fetch_toss_korean_names
from investment_agent.data.universe.infrastructure.sources.wikipedia_sp500 import (
    fetch_current_members,
    fetch_selected_changes,
)
from investment_agent.data.universe.domain.normalization import (
    build_membership_snapshots,
    build_reconcile_rows,
)

log = get_logger(__name__)


def _missing_sec_get_json(_: str) -> Any:
    raise RuntimeError("SEC client must be injected by the entrypoint")


def sync_exchange_listings(*, sec_get_json: Callable[[str], Any] | None = None) -> None:
    """SEC 거래소 master를 동기화하고 새 CIK의 entity 이름만 seed한다."""
    rows = fetch_exchange_listed_tickers(get_json=sec_get_json or _missing_sec_get_json)
    log.info("  미국 거래소 종목 동기화: %d", db.upsert_securities(rows))


def sync_sec_entities(
    *, tracked_only: bool = False, sec_get_json: Callable[[str], Any] | None = None
) -> dict[str, int]:
    """CIK별 SEC submissions metadata를 증분 보강한다."""
    pending = db.select_entity_pending(tracked_only=tracked_only)
    if not pending:
        log.info("  SEC entity 보강: 대상 0건 (skip)")
        return {
            "candidate_entities": 0,
            "unique_ciks": 0,
            "fetched": 0,
            "affected": 0,
            "outcomes": {},
        }
    ciks = sorted({row["cik"] for row in pending})
    fetched = affected = 0
    outcomes: dict[str, int] = {}
    for start in range(0, len(ciks), _ENTITY_CHUNK):
        chunk = ciks[start:start + _ENTITY_CHUNK]
        results = fetch_entity_results(
            chunk, get_json=sec_get_json or _missing_sec_get_json
        )
        durable = [
            result
            for result in results
            if str(result.get("outcome") or "") != "retryable_failure"
        ]
        affected += db.apply_entity_results(durable)
        fetched += len(results)
        for result in results:
            outcome = str(result.get("outcome") or "invalid")
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        log.info(
            "  SEC entity 보강 진행: CIK %d/%d (누적 응답 %d)",
            start + len(chunk), len(ciks), fetched,
        )
        for result in results:
            if str(result.get("outcome") or "") == "retryable_failure":
                log.error(
                    "SEC entity provider failed: cik=%s error_code=%s http_status=%s",
                    result.get("cik"),
                    result.get("error_code"),
                    result.get("http_status"),
                )
    metrics = {
        "candidate_entities": len(pending),
        "unique_ciks": len(ciks),
        "fetched": fetched,
        "affected": affected,
        "outcomes": outcomes,
    }
    if outcomes.get("retryable_failure"):
        raise RuntimeError(
            "SEC entity collection incomplete: "
            f"retryable_failures={outcomes['retryable_failure']} outcomes={outcomes}"
        )
    return metrics


def _repair_tracked_gate(current_set: set[str]) -> int:
    """수집 게이트를 현재 멤버 집합에 맞춘다. 고친 종목 수를 돌려준다."""
    tracked = set(db.select_tracked_tickers())
    rows = [{"ticker": ticker, "is_tracked": True} for ticker in sorted(current_set - tracked)]
    rows += [{"ticker": ticker, "is_tracked": False} for ticker in sorted(tracked - current_set)]
    return db.set_membership(rows) if rows else 0


def reconcile_membership(*, audit_history: bool = True) -> dict[str, object]:
    """현재 S&P 집합을 비교하고 실제 변경 또는 월간 감사 때만 저장한다.

    `is_tracked`는 범용 gate이므로, 과거 멤버 전체를 false로 덮지 않고 직전 S&P
    snapshot에서 실제로 빠진 ticker만 해제한다. 향후 확대 유니버스 정책은 이 최종
    gate 계산에 합성할 수 있다.
    """
    members = fetch_current_members()              # 현재 멤버 목록 (개수 안전 점검 포함)
    current_set = set(members["ticker"])
    previous_set = db.select_latest_sp500_symbols()
    if not previous_set:
        # append-only membership 원장은 현재 S&P gate를 tracked 기준으로 사용한다.
        previous_set = set(db.select_tracked_tickers())
    added = sorted(current_set - previous_set)
    removed = sorted(previous_set - current_set)
    changed = bool(added or removed)
    if not changed and not audit_history:
        # 멤버십이 그대로라도 게이트가 그대로라는 뜻은 아니다. 상류 단계가 게이트를
        # 건드렸을 수 있으므로 실제 값과 대조하고 어긋난 것만 고친다 — 보통 0건이라
        # 왕복이 늘지 않는다.
        repaired = _repair_tracked_gate(current_set)
        if repaired:
            log.warning("  S&P 멤버십은 그대로인데 수집 게이트가 어긋나 있었다: %d종목 복구", repaired)
        log.info("  S&P 500 멤버십 변경 없음 (경량 점검 종료)")
        return {"changed": False, "added": [], "removed": [], "snapshots_inserted": 0}

    changes = fetch_selected_changes()             # 편입/탈락 기록에서 과거 멤버 뽑기
    plan = build_reconcile_rows(members, changes)
    log.info(f"  현재 멤버: {db.set_membership(plan['current_rows'])}")
    if plan["past_rows"]:
        log.info(f"  과거 멤버: {db.set_membership(plan['past_rows'])}")
    leaving = [{"ticker": ticker, "is_tracked": False} for ticker in removed]
    if leaving:
        log.info(f"  현재→과거 전환: {db.set_membership(leaving)}")
    snapshots = build_membership_snapshots(members, changes)
    snapshots_inserted = 0
    if snapshots:
        snapshots_inserted = db.append_memberships(snapshots)
        log.info("  과거 멤버십 snapshot 신규 append: %d", snapshots_inserted)
    else:
        log.warning("  변경 이력이 없어 과거 멤버십 snapshot은 기존 값을 보존")
    log.info("  멤버십 diff: changed=%s added=%s removed=%s", changed, added, removed)
    return {
        "changed": changed,
        "added": added,
        "removed": removed,
        "snapshots_inserted": snapshots_inserted,
    }


def refresh_korean_names(*, retry_after_days: int = 90) -> dict[str, int]:
    """추적 종목의 누락 한글명을 토스증권으로 보강한다.

    토스 IP 허용목록에 등록된 로컬 환경에서만 별도 실행한다. 기존 ``company_name_ko``는
    조회 대상에서 제외해 수동 교정값을 덮어쓰지 않는다. 정상 조회 뒤 이름을 받지
    못한 종목은 ``retry_after_days``가 지난 후 다시 시도한다.
    """
    retry_before = (
        datetime.now(timezone.utc) - timedelta(days=retry_after_days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    pending = db.select_name_ko_pending(retry_before)
    names, attempted = fetch_toss_korean_names(pending)
    db.apply_toss_names(names, attempted)
    log.info(
        "한글명 보강(토스): pending=%d attempted=%d updated=%d retry_after_days=%d",
        len(pending),
        len(attempted),
        len(names),
        retry_after_days,
    )
    return {
        "pending": len(pending),
        "attempted": len(attempted),
        "updated": len(names),
    }


# 조회→저장을 이 단위로 끊는다. 중간에 잡이 끊겨도 여기까지는 남는다.
_ENTITY_CHUNK = 200
