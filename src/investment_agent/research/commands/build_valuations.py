"""거래일마다 PIT 밸류에이션 관측값을 계산해 원장에 적재한다.

Phase 0 감사 결론에 따라 **live_shadow만** 만든다. 과거 시점은 만들지 않는다 —
`market.prices_daily.ingested_at`이 이번 재적재 시각이라 과거의 실제 가용시각이
아니고, wide 재무표는 정정 전 행을 보존하지 않아 TTM 구성 분기의 vintage를
증명할 수 없기 때문이다. 근거는 docs/EVIDENCE_DOSSIER_PHASE_0_1.md에 있다.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from investment_agent.operations.runtime import run_log_payload
from investment_agent.platform.logging import get_logger
from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.trading.supabase_repository import SupabaseRepository
from investment_agent.research.valuation.engine import PITValuationObservation, build_pit_valuation
from investment_agent.research.valuation.inputs import build_valuation_inputs

log = get_logger(__name__)

WORKFLOW = "ai_investor_build_valuations"
SOURCE_VERSION = "pit-valuation-v1"
_UPSERT_CHUNK = 100


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.build_valuations")
    parser.add_argument("--ticker", action="append", help="지정 종목만 실행. 여러 번 사용 가능")
    parser.add_argument("--limit", type=int, help="처리할 최대 종목 수. 기본은 전체 tracked")
    parser.add_argument("--as-of", help="타임존을 포함한 ISO-8601 기준 시각. 기본은 현재 UTC")
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
    dry_run: bool = False,
    repository: SupabaseRepository | None = None,
) -> dict[str, object]:
    """종목별 가격·발행주식수·TTM 재무를 하나의 PIT 관측값으로 만든다."""
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    selected = repository or SupabaseRepository()
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    complete = 0
    reason_counts: dict[str, int] = {}

    for ticker in tickers:
        try:
            observation = build_pit_valuation(build_valuation_inputs(
                ticker=ticker,
                as_of_at=as_of_at,
                source_version=SOURCE_VERSION,
                price_rows=selected.market_prices(ticker, as_of_at, limit=5),
                fundamental_rows=selected.fundamentals_pit(ticker, as_of_at, limit=12),
                share_rows=selected.share_class_snapshots_pit(ticker, as_of_at),
                source_kind="live_shadow",
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

    saved = 0
    if not dry_run:
        for start in range(0, len(rows), _UPSERT_CHUNK):
            chunk = rows[start:start + _UPSERT_CHUNK]
            selected.save_valuation_observations(chunk)
            saved += len(chunk)

    payload = run_log_payload(
        workflow=WORKFLOW,
        status="success" if not failures else "partial",
        rows_upserted=saved,
        tickers_processed=len(tickers),
        duration_sec=round(time.monotonic() - started, 3),
        started_at=started_at,
        detail={
            "source_version": SOURCE_VERSION,
            "source_kind": "live_shadow",
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
    tickers = [value.upper() for value in (args.ticker or [])] or repository.current_tracked_tickers()
    if args.limit is not None:
        tickers = tickers[:args.limit]
    if not tickers:
        log.error("no tracked ticker is available for valuation building")
        return 1
    payload = build_valuations(
        as_of_at=as_of_at,
        tickers=tickers,
        dry_run=args.dry_run,
        repository=repository,
    )
    return 0 if payload["status"] == "success" else 1


__all__ = ["SOURCE_VERSION", "WORKFLOW", "build_valuations", "main"]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
