"""전체 과정을 순서대로 실행하는 '시작 파일'(진입점).

사용법:
    python -m investment_agent.research.strategies.etl                     # 매월 1일 자동 실행 (이번 달 1건 저장)
    python -m investment_agent.research.strategies.etl --mark-sent         # 자동 실행 + '발송 완료'로 바로 표시 (백필용)
    python -m investment_agent.research.strategies.etl --backfill-from YYYY-MM   # 지정한 달부터 이번 달 직전까지 다시 계산

'매월 1일에만 실행' 검사는 이 파일이 아니라 깃허브 워크플로(§6-6)가 맡는다.
"""
from __future__ import annotations

import argparse
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from investment_agent.operations.runtime import elapsed_sec
from investment_agent.platform.logging import get_logger
from investment_agent.research.strategies import BACKFILL_FROM, db
from investment_agent.research.strategies.catalog import STRATEGY_CATALOG
from investment_agent.research.strategies.retention import prune_history as prune_strategy_history
from investment_agent.research.strategies.sources import download_monthly_close
from investment_agent.research.strategies.strategies import (
    STRATEGY_IDS,
    compute_all,
    compute_one,
    monthly_returns,
)
from investment_agent.research.strategies.transforms import decision_and_apply_dates

log = get_logger(__name__)


# ── 백필 헬퍼 ─────────────────────────────────────
def _parse_yyyymm(s: str) -> date:
    # 'YYYY-MM' → 그 달 1일 날짜
    y, m = s.split("-")
    return date(int(y), int(m), 1)


def _compute_available_for_backfill(
    prices: pd.DataFrame,
    *,
    previously_available: set[str] | None = None,
) -> tuple[list[dict], list[str]]:
    """과거 시점에 실제 데이터가 준비된 전략만 계산한다.

    월간 운영 실행은 계속 6개 전략 완결성을 강제한다. 반면 과거 백필에서는
    아직 상장되지 않은 필수 ETF(예: DMSR의 XLC) 때문에 다른 전략의 유효한
    이력까지 막지 않도록, ``None``을 반환한 전략만 해당 월에서 제외한다.
    계산 중 예외는 데이터 부족과 구분해 그대로 실패시킨다.
    """
    rets = monthly_returns(prices)
    seen = previously_available or set()
    results: list[dict] = []
    unavailable: list[str] = []
    for strategy_id in STRATEGY_IDS:
        result = compute_one(strategy_id, rets)
        if result is None:
            if strategy_id in seen:
                raise RuntimeError(
                    "strategy became unavailable after its first valid history: "
                    f"{strategy_id}"
                )
            unavailable.append(strategy_id)
        else:
            results.append(result)
    return results, unavailable


def _run_backfill(target_apply: date) -> int:
    """지정한 달부터 이번 달 직전까지, 매달의 결과를 다시 계산해 저장한다(이미 보낸 것으로 표시)."""
    full = download_monthly_close(period="max")
    # 누락 컬럼·최신 NaN 같은 부분 응답을 "상장 전"으로 오인해 한 전략 전체를
    # 조용히 생략하지 않도록, 어떤 DB write보다 먼저 현재 6개 전략 완결성을 확인한다.
    compute_all(full)
    cur_apply = target_apply
    cur_decision = (pd.Timestamp(cur_apply) - pd.offsets.MonthEnd(1)).date()
    today_first = datetime.now(ZoneInfo("Asia/Seoul")).date().replace(day=1)

    n_months = 0
    available_strategies: set[str] = set()
    while cur_apply < today_first:
        sliced = full[full.index <= pd.Timestamp(cur_decision)]
        if sliced.empty:
            log.warning("skip %s — empty slice", cur_apply)
        else:
            decision, apply_dt = decision_and_apply_dates(sliced)
            if apply_dt != cur_apply:
                raise RuntimeError(
                    f"backfill month mismatch: calculated={apply_dt} expected={cur_apply}"
                )
            results, unavailable = _compute_available_for_backfill(
                sliced,
                previously_available=available_strategies,
            )
            if unavailable:
                log.info(
                    "backfill apply=%s unavailable_strategies=%s",
                    apply_dt,
                    ",".join(unavailable),
                )
            for r in results:
                db.upsert_allocation(
                    strategy_id   = r["strategy_id"],
                    decision_date = decision,
                    apply_date    = apply_dt,
                    mode          = r["mode"],
                    alloc         = r["weights"],
                    signals       = r.get("signals", {}),
                    mark_sent     = True,
                )
            if results:
                available_strategies.update(
                    str(result["strategy_id"]) for result in results
                )
                log.info("backfilled apply=%s strategies=%d", apply_dt, len(results))
                n_months += 1
            else:
                log.warning("skip %s — no strategy has sufficient data", apply_dt)
        cur_apply = (pd.Timestamp(cur_apply) + pd.offsets.MonthBegin(1)).date()
        cur_decision = (pd.Timestamp(cur_apply) - pd.offsets.MonthEnd(1)).date()
    return n_months


# ── 월간 정기 실행 ─────────────────────────────────
def _run_monthly(*, mark_sent: bool) -> None:
    """가장 최근에 끝난 달 기준으로 6개 전략을 계산해 저장한다."""
    apply_month = datetime.now(ZoneInfo("Asia/Seoul")).date().replace(day=1)
    expected = set(STRATEGY_CATALOG)
    existing = db.allocation_strategy_ids(apply_month)
    if existing == expected:
        if mark_sent:
            marked = db.mark_allocations_sent(apply_month)
            log.info("strategy monthly already complete; marked_sent=%d", marked)
        else:
            log.info(
                "strategy monthly no-op: apply=%s existing=%d",
                apply_month,
                len(existing),
            )
        return

    prices = download_monthly_close()
    decision, apply_dt = decision_and_apply_dates(prices)
    if apply_dt != apply_month:
        raise RuntimeError(
            "monthly price data is stale or incomplete: "
            f"calculated_apply={apply_dt} expected_apply={apply_month}"
        )
    results = compute_all(prices)
    result_ids = {str(row["strategy_id"]) for row in results}
    if result_ids != expected:
        raise RuntimeError(
            "strategy result set mismatch: "
            f"missing={sorted(expected - result_ids)} extra={sorted(result_ids - expected)}"
        )
    log.info("decision=%s apply=%s tickers=%d", decision, apply_dt, prices.shape[1])
    for r in results:
        db.upsert_allocation(
            strategy_id   = r["strategy_id"],
            decision_date = decision,
            apply_date    = apply_dt,
            mode          = r["mode"],
            alloc         = r["weights"],
            signals       = r.get("signals", {}),
            mark_sent     = mark_sent,
        )
        log.info("  %-9s %-30s %s", r["strategy_id"], r["mode"], r["weights"])


# ── CLI ───────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="investment_agent.research.strategies.etl")
    ap.add_argument(
        "--backfill-from",
        nargs="?",
        const=BACKFILL_FROM,
        help=(
            "YYYY-MM (apply_date 기준) - 이 월부터 올달 전까지 백필. "
            f"값 없이 주면 기본값 {BACKFILL_FROM} 사용"
        ),
    )
    ap.add_argument(
        "--mark-sent",
        action="store_true",
        help="계산과 동시에 '발송 완료'로 표시. 알림 없이 채우는 백필용.",
    )
    args = ap.parse_args(argv)
    t0 = time.monotonic()

    if args.backfill_from:
        target = _parse_yyyymm(args.backfill_from)
        n = _run_backfill(target)
        prune_strategy_history()
        log.info(
            "backfill done: %d months upserted (from=%s) duration_sec=%.1f",
            n,
            target,
            elapsed_sec(t0),
        )
        return 0

    # 백필이 아니면 월간 계산 실행
    _run_monthly(mark_sent=args.mark_sent)
    prune_strategy_history()
    log.info("strategy monthly done: duration_sec=%.1f", elapsed_sec(t0))
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
