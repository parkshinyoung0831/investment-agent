"""PIT 밸류에이션 관측값을 계산해 원장에 적재한다.

`live_shadow`는 매일의 실행 시각 기준이다. `historical_replay`는 과거 시점을 재현한다 —
가격은 거래 세션 규칙으로, 재무는 공시 버전(`financial_versions`)과 SEC 제출일 규칙으로,
발행주식수는 접수 시각으로 자르므로 그 시점에 알 수 있던 값만 들어간다. 과거 시점의
종목은 그때의 S&P 500 멤버다(지금 남아 있는 종목만 쓰면 생존 편향이 생긴다).
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from investment_agent.platform.cli.runtime import run_log_payload
from investment_agent.platform.logging import get_logger
from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.trading.supabase_repository import SupabaseRepository
from investment_agent.research.datasets.universe import research_universe
from investment_agent.research.storage.repository import ResearchStore
from investment_agent.research.valuation.engine import PITValuationObservation, build_pit_valuation
from investment_agent.research.valuation.inputs import build_valuation_inputs

log = get_logger(__name__)

WORKFLOW = "ai_investor_build_valuations"
SOURCE_VERSION = "pit-valuation-v1"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.build_valuations")
    parser.add_argument("--ticker", action="append", help="지정 종목만 실행. 여러 번 사용 가능")
    parser.add_argument("--limit", type=int, help="처리할 최대 종목 수. 기본은 전체 tracked")
    parser.add_argument("--as-of", help="타임존을 포함한 ISO-8601 기준 시각. 기본은 현재 UTC")
    parser.add_argument(
        "--source-kind", default="live_shadow", choices=("live_shadow", "historical_replay"),
        help="historical_replay는 --as-of 시점의 S&P 500 멤버와 원천 공개 규칙으로 재현한다",
    )
    parser.add_argument("--dry-run", action="store_true", help="계산만 하고 저장하지 않는다")
    return parser.parse_args(argv)


def _number(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _storage_row(observation: PITValuationObservation) -> dict[str, Any]:
    """Decimal을 JSON 직렬화 가능한 형태로 낮춘다."""
    return {
        "ticker": observation.ticker,
        "as_of_at": observation.as_of_at,
        "source_kind": observation.source_kind,
        "source_version": observation.source_version,
        "available_at": observation.available_at,
        "price": _number(observation.price),
        "shares_outstanding": _number(observation.shares_outstanding),
        "market_cap": _number(observation.market_cap),
        "pe_ttm": _number(observation.pe_ttm),
        "pb": _number(observation.pb),
        "ps_ttm": _number(observation.ps_ttm),
        "fcf_yield": _number(observation.fcf_yield),
        "is_meaningful_pe_ttm": observation.is_meaningful_pe_ttm,
        "is_meaningful_pb": observation.is_meaningful_pb,
        "is_meaningful_ps_ttm": observation.is_meaningful_ps_ttm,
        "is_meaningful_fcf_yield": observation.is_meaningful_fcf_yield,
        "missing_reasons": dict(observation.missing_reasons),
        "input_evidence_ids": list(observation.input_evidence_ids),
        "input_hash": observation.input_hash,
    }


def build_valuations(
    *,
    as_of_at: datetime,
    tickers: list[str],
    source_kind: str = "live_shadow",
    dry_run: bool = False,
    repository: SupabaseRepository | None = None,
    store: ResearchStore | None = None,
) -> dict[str, object]:
    """종목별 가격·발행주식수·TTM 재무를 하나의 PIT 관측값으로 만든다."""
    if source_kind not in ("live_shadow", "historical_replay"):
        raise ValueError(f"unsupported source_kind: {source_kind}")
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    selected = repository or SupabaseRepository()
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    complete = 0
    reason_counts: dict[str, int] = {}

    phase = time.monotonic()
    if source_kind == "historical_replay" and hasattr(selected, "prepare_historical_replay"):
        selected.prepare_historical_replay(tuple(tickers), as_of_at)
    prepare_sec = time.monotonic() - phase

    phase = time.monotonic()
    for ticker in tickers:
        try:
            observation = build_pit_valuation(build_valuation_inputs(
                ticker=ticker,
                as_of_at=as_of_at,
                source_version=SOURCE_VERSION,
                price_rows=selected.market_prices(ticker, as_of_at, limit=5),
                fundamental_rows=selected.fundamentals_pit(ticker, as_of_at, limit=12),
                share_rows=selected.share_class_snapshots_pit(ticker, as_of_at),
                split_rows=selected.split_history(ticker) if hasattr(selected, "split_history") else (),
                source_kind=source_kind,
            ))
        except (ContractError, ValueError) as exc:
            # 한 종목의 원천 문제가 그날 전체 적재를 막지 않는다.
            log.warning("valuation build failed ticker=%s: %s", ticker, exc)
            failures.append(ticker)
            continue
        for name in observation.missing_reasons.values():
            reason_counts[name] = reason_counts.get(name, 0) + 1
        if observation.market_cap is not None:
            complete += 1
        rows.append(_storage_row(observation))
    compute_sec = time.monotonic() - phase

    phase = time.monotonic()
    saved = 0
    if not dry_run and rows:
        (store or ResearchStore()).save_valuation_observations(rows)
        saved = len(rows)
    write_sec = time.monotonic() - phase

    payload = run_log_payload(
        workflow=WORKFLOW,
        status="success" if not failures else "partial",
        rows_upserted=saved,
        tickers_processed=len(tickers),
        duration_sec=round(time.monotonic() - started, 3),
        started_at=started_at,
        detail={
            "source_version": SOURCE_VERSION,
            "source_kind": source_kind,
            "as_of_at": as_of_at.isoformat(),
            "built": len(rows),
            "with_market_cap": complete,
            "meaningful_pe": sum(1 for row in rows if row["is_meaningful_pe_ttm"]),
            "meaningful_pb": sum(1 for row in rows if row["is_meaningful_pb"]),
            "top_missing_reasons": dict(
                sorted(reason_counts.items(), key=lambda item: -item[1])[:8]
            ),
            "failed": failures[:20],
            "failed_count": len(failures),
            "dry_run": dry_run,
            "timings_sec": {"prepare": round(prepare_sec, 3), "compute": round(compute_sec, 3),
                            "write": round(write_sec, 3)},
        },
    )
    log.info("pit valuations %s", payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be positive")
    as_of_at = parse_datetime(args.as_of) if args.as_of else datetime.now(timezone.utc)
    repository = SupabaseRepository()
    tickers = [value.upper() for value in (args.ticker or [])] or research_universe(
        repository, as_of_at=as_of_at, source_kind=args.source_kind,
    )
    if args.limit is not None:
        tickers = tickers[:args.limit]
    if not tickers:
        log.error("no tracked ticker is available for valuation building")
        return 1
    payload = build_valuations(
        as_of_at=as_of_at,
        tickers=tickers,
        source_kind=args.source_kind,
        dry_run=args.dry_run,
        repository=repository,
    )
    return 0 if payload["status"] == "success" else 1


__all__ = ["SOURCE_VERSION", "WORKFLOW", "build_valuations", "main"]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
