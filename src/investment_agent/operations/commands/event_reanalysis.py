"""새 공시·고영향 사건·검증된 글로벌 사건이 생긴 보유 종목을 정기 주기를 기다리지 않고 다시 분석한다.

    python -m investment_agent.operations.commands.event_reanalysis

한 번에 `MAX_TICKERS_PER_RUN`개만 분석한다. 사건이 몰린 날 LLM 예산을 한꺼번에 태우면 정기 분석이
멈춘다. 이미 그 사건 뒤에 분석한 종목은 다시 고르지 않으므로(`last_analyzed_at`), 같은 사건으로
반복 호출되지 않는다. 결과는 보통의 SignalBatch라 매매는 여전히 optimizer·RiskGate·승인을 거친다.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any, Callable

from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import canonical_json, parse_datetime

log = get_logger(__name__)

MAX_TICKERS_PER_RUN = 3


def _refresh_events(now: datetime) -> dict[str, Any]:
    """로컬 뉴스·소셜 원문을 사건으로 다시 압축한다. 실패해도 공시 기반 재분석은 계속한다."""
    from investment_agent.research.commands.build_events import build_events
    from investment_agent.trading.evidence.cache import LocalEvidenceCache
    from investment_agent.trading.supabase_repository import SupabaseRepository

    repository = SupabaseRepository()
    try:
        return build_events(cache=LocalEvidenceCache(None), repository=repository, as_of_at=now.isoformat(),
                            tickers=repository.current_tracked_tickers())
    except Exception as exc:  # noqa: BLE001 - 사건 저장소 장애가 공시 트리거까지 막지 않게 한다
        log.warning("event refresh failed: %s", type(exc).__name__)
        return {"error": type(exc).__name__}


def run_event_reanalysis(
    *,
    now: datetime,
    repository: Any,
    analyze: Callable[[list[str]], int],
    refresh: Callable[[datetime], dict[str, Any]] = _refresh_events,
    max_tickers: int = MAX_TICKERS_PER_RUN,
) -> dict[str, Any]:
    refreshed = refresh(now)
    priorities = repository.event_reanalysis_priorities(as_of_at=now)
    selected = list(priorities[:max_tickers])
    result: dict[str, Any] = {
        "as_of_at": now.isoformat(),
        "events": refreshed,
        "pending": len(priorities),
        "triggered": [{"ticker": item.ticker, "reason": item.reason} for item in selected],
    }
    if not selected:
        return result
    argv = ["--as-of", now.isoformat(), "--limit", str(len(selected))]
    for item in selected:
        argv += ["--ticker", item.ticker]
    result["analysis_exit_code"] = analyze(argv)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.commands.event_reanalysis")
    parser.add_argument("--as-of")
    parser.add_argument("--max-tickers", type=int, default=MAX_TICKERS_PER_RUN)
    args = parser.parse_args(argv)
    if not 1 <= args.max_tickers <= 10:
        raise SystemExit("--max-tickers must be between 1 and 10")
    now = parse_datetime(args.as_of) if args.as_of else datetime.now(timezone.utc)
    from investment_agent.trading.decision import analysis
    from investment_agent.trading.supabase_repository import SupabaseRepository

    result = run_event_reanalysis(now=now, repository=SupabaseRepository(), analyze=analysis.main,
                                  max_tickers=args.max_tickers)
    log.info("event reanalysis %s", canonical_json(result))
    return int(result.get("analysis_exit_code") or 0)


__all__ = ["MAX_TICKERS_PER_RUN", "main", "run_event_reanalysis"]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
