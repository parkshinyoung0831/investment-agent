"""Gurus 13F 증분·백필 ETL 오케스트레이션."""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

from investment_agent.operations.backfill import add_backfill_from_arg
from investment_agent.operations.runtime import elapsed_sec
from investment_agent.platform.logging import get_logger
from investment_agent.data.institutional import POLL_WINDOW_DAYS, persistence as db
from investment_agent.data.institutional.domain import shadow_diff
from investment_agent.data.institutional.application.settings import shadow_parser_enabled
from investment_agent.data.institutional.domain.models import FilingRecord
from investment_agent.data.institutional.infrastructure.sources import sec13f as edgar
from investment_agent.data.institutional.infrastructure.sources import openfigi

log = get_logger(__name__)


class GuruEtlError(RuntimeError):
    """Gurus ETL 실행 실패의 공통 기반 예외."""


class GuruConfigurationError(GuruEtlError):
    """실행 구간 또는 대상 설정이 잘못되었을 때 발생한다."""


class GuruProviderError(GuruEtlError):
    """운용사별 SEC 공급자 호출이 실패했다."""

    def __init__(self, manager_cik: str, cause: Exception) -> None:
        self.manager_cik = manager_cik
        self.cause_type = type(cause).__name__
        # requests 예외 원문에는 URL/query가 들어갈 수 있어 운영 메트릭에는
        # 공급자·형식만 공개하고 원본은 __cause__로 보존한다.
        super().__init__(
            f"manager {manager_cik}: SEC provider failed ({self.cause_type})"
        )
        self.__cause__ = cause


class AllGuruManagersFailedError(GuruEtlError):
    """모든 활성 운용사의 SEC 수집이 실패한 fail-closed 상태."""


def _validate_filing(record: FilingRecord) -> None:
    """SEC Summary와 직접 파싱 결과가 완전히 일치하는지 검증한다."""
    if not record.accepted_at:
        raise ValueError(
            f"missing accepted_at accession_no={record.accession_no}"
        )
    if not record.source_url:
        raise ValueError(
            f"missing source_url accession_no={record.accession_no}"
        )
    if len(record.content_sha256) != 64:
        raise ValueError(
            f"invalid content hash accession_no={record.accession_no}"
        )
    if not record.report_type:
        raise ValueError(
            f"missing report type accession_no={record.accession_no}"
        )
    if record.form_type.endswith("/A") and record.amendment_type not in {
        "RESTATEMENT",
        "NEW HOLDINGS",
    }:
        raise ValueError(
            f"unknown amendment type accession_no={record.accession_no}"
        )
    # SEC 요약(tableEntryTotal)이 세는 것은 informationTable의 **원시 행**이다.
    # 13F COMBINATION REPORT는 같은 증권을 자회사 운용사마다 한 행씩 신고하므로
    # (cusip, 종류, 단위)로 합산한 positions는 늘 이보다 적다. 합산 결과와 비교하면
    # 정상 공시가 통째로 버려진다 — 버크셔가 매 분기 그렇게 빠졌다.
    if record.reported_line_count != record.parsed_line_count:
        raise ValueError(
            "holding row count mismatch "
            f"accession_no={record.accession_no} "
            f"reported={record.reported_line_count} "
            f"parsed={record.parsed_line_count}"
        )
    parsed_value = sum(position.value_usd for position in record.positions)
    # SEC Summary 총액(tableValueTotal)은 종종 천 달러 단위로 반올림되어 infoTable
    # 합계와 소액 차이가 난다(예: 33억 중 $1,000). 규모에 비례한 허용오차(약 10ppm,
    # 최소 $1)로 반올림 차이만 통과시킨다. 단위(scale) 오류는 1000배라 항상 걸러진다.
    value_tolerance = max(1, record.reported_value_usd // 100_000)
    if abs(parsed_value - record.reported_value_usd) > value_tolerance:
        raise ValueError(
            "holding value mismatch "
            f"accession_no={record.accession_no} "
            f"reported={record.reported_value_usd} parsed={parsed_value}"
        )


def _make_shadow_sink(manager_cik: str, metrics: dict):
    """edgartools shadow 대조 결과를 받는 콜백을 만든다.

    불일치는 실행 로그와 실패 메트릭에 남긴다. 운영 적재는 표준 결과를 사용하며
    오류 원문은 GitHub Actions에서 확인한다.
    """

    def sink(diff: shadow_diff.ShadowDiff) -> None:
        metrics["shadow_checked"] += 1
        if diff.matched:
            return
        metrics["shadow_mismatched"] += 1
        reason = diff.reason() or "shadow mismatch"
        metrics["failures"].append(
            {
                "manager_cik": manager_cik,
                "accession_no": diff.accession_no,
                "step": "shadow_compare",
                "error": reason,
                "type": "ShadowParserMismatch",
            }
        )
        log.warning(
            "shadow mismatch accession_no=%s reason=%s",
            diff.accession_no,
            reason,
        )

    return sink


def _make_filing_error_sink(manager_cik: str, metrics: dict):
    """개별 SEC filing 파싱 실패를 실행 로그와 메트릭에 기록한다."""

    def sink(filing, exc: Exception) -> None:
        metrics["failures"].append(
            {
                "manager_cik": manager_cik,
                "accession_no": filing.accession_no,
                "step": "parse_filing",
                "error": repr(exc),
            }
        )
        log.error(
            "filing parse failed manager_cik=%s accession_no=%s error_type=%s error=%s",
            manager_cik,
            filing.accession_no,
            type(exc).__name__,
            exc,
        )

    return sink


def _resolve_tickers(
    identifiers: set[tuple[str, str]],
    cache: dict[tuple[str, str], dict],
    *,
    universe_tickers: set[str] | None = None,
    force: bool = False,
) -> tuple[int, int, dict[str, int]]:
    """재시도 가능한 CUSIP/CINS만 다시 조회하고 universe로 후보를 검증한다."""
    missing = [
        pair for pair in sorted(identifiers)
        if (
            str((cache.get(pair) or {}).get("mapping_status"))
            not in {"mapped", "historical"}
            if force
            else db.mapping_is_due(cache.get(pair))
        )
    ]
    if not missing:
        return 0, 0, {}
    try:
        mapped, requests_made = openfigi.map_identifiers(
            [identifier for identifier, _id_type in missing]
        )
    except Exception as exc:  # noqa: BLE001 - 포지션 적재 성공을 가리지 않는다.
        log.warning("openfigi batch failed jobs=%d error=%r", len(missing), exc)
        return len(missing), 0, {"provider_failed": len(missing)}
    if universe_tickers is None:
        try:
            universe_tickers = db.known_universe_tickers()
        except Exception as exc:  # noqa: BLE001 - 포지션 원천 적재는 보존한다.
            log.warning("universe ticker verification failed jobs=%d error=%r", len(missing), exc)
            return len(missing), requests_made, {"provider_failed": len(missing)}
    results = [
        replace(result, mapping_status="historical")
        if result.mapping_status == "mapped" and result.ticker not in universe_tickers
        else result
        for result in mapped.values()
    ]
    db.cache_mappings(results, universe_tickers=universe_tickers)
    updated_at = datetime.now(timezone.utc).isoformat()
    for result in results:
        cache[(result.identifier, result.identifier_type)] = {
            "identifier": result.identifier,
            "identifier_type": result.identifier_type,
            "ticker": result.ticker,
            "mapping_status": result.mapping_status,
            "updated_at": updated_at,
        }
    distribution: dict[str, int] = {}
    for result in results:
        distribution[result.mapping_status] = distribution.get(result.mapping_status, 0) + 1
    return len(missing), requests_made, distribution


def refresh_mappings(*, force: bool = False) -> dict[str, int]:
    """이미 적재된 전체 13F의 미완료 CUSIP/CINS 매핑을 별도로 복구한다.

    SEC 원천 적재와 API rate-limit 장애를 분리하기 위한 단계다. ``force``는
    backfill 직후 not_found/ambiguous를 TTL 대기 없이 한 번 다시 조회한다.
    mapped/historical 결론은 어떤 경우에도 재조회하지 않는다.
    """
    identifiers = db.referenced_identifiers()
    cache = db.get_identifier_cache()
    universe_tickers = db.known_universe_tickers()
    checked, requests_made, statuses = _resolve_tickers(
        identifiers,
        cache,
        universe_tickers=universe_tickers,
        force=force,
    )
    metrics = {
        "identifiers_checked": checked,
        "openfigi_requests": requests_made,
        **{f"mapping_{status}": count for status, count in statuses.items()},
    }
    log.info("institutional mapping refresh done: %s", metrics)
    return metrics


def _since(backfill_from: str | None, lookback_days: int) -> str:
    if backfill_from:
        try:
            parsed = date.fromisoformat(backfill_from)
        except (TypeError, ValueError) as exc:
            raise GuruConfigurationError(
                "backfill_from must be an ISO date (YYYY-MM-DD)"
            ) from exc
        if parsed > datetime.now(timezone.utc).date():
            raise GuruConfigurationError("backfill_from cannot be in the future")
        return parsed.isoformat()
    if (
        isinstance(lookback_days, bool)
        or not isinstance(lookback_days, int)
        or lookback_days < 1
    ):
        raise GuruConfigurationError("lookback_days must be at least 1")
    return (
        datetime.now(timezone.utc).date() - timedelta(days=lookback_days - 1)
    ).isoformat()


def _run(
    backfill_from: str | None = None,
    *,
    lookback_days: int = POLL_WINDOW_DAYS,
    include_existing: bool = False,
    sec_client: Any | None,
) -> dict:
    if sec_client is None:
        raise GuruConfigurationError(
            "sec_client is required; use investment_agent.data.institutional.commands.institutional_daily"
        )
    since = _since(backfill_from, lookback_days)
    mode = (
        "reparse"
        if include_existing
        else "backfill" if backfill_from else "polling"
    )
    log.info(
        "mode=%s since=%s include_existing=%s",
        mode,
        since,
        include_existing,
    )

    manager_ciks = db.get_active_manager_ciks()
    if not manager_ciks:
        raise GuruConfigurationError("institutional.managers.MANAGER_CATALOG has no active managers")
    log.info("active managers=%d", len(manager_ciks))

    cache = db.get_identifier_cache()
    stored = db.stored_accessions()
    stored_at_start = set(stored)
    skip_accessions = set() if include_existing else stored
    shadow_on = shadow_parser_enabled()
    metrics = {
        "filings": 0,
        "positions": 0,
        "managers": len(manager_ciks),
        "existing_accessions": len(stored),
        "include_existing": include_existing,
        "new_filings": 0,
        "reprocessed_filings": 0,
        "cusips_checked": 0,
        "identifiers_checked": 0,
        "openfigi_requests": 0,
        "mapping_statuses": {},
        "shadow_enabled": shadow_on,
        "shadow_checked": 0,
        "shadow_mismatched": 0,
        "managers_failed": 0,
        "failures": [],
    }
    if shadow_on:
        log.info("edgartools shadow parser comparison enabled")
    try:
        universe_tickers: set[str] | None = db.known_universe_tickers()
    except Exception as exc:  # noqa: BLE001 - SEC 원천 적재와 mapping 운영 실패를 분리한다.
        universe_tickers = None
        log.warning("universe ticker verification unavailable: %r", exc)
        metrics["failures"].append(
            {
                "manager_cik": None,
                "step": "universe_ticker_verification",
                "error": repr(exc),
                "type": type(exc).__name__,
            }
        )

    for manager_cik in manager_ciks:
        shadow_sink = (
            _make_shadow_sink(manager_cik, metrics) if shadow_on else None
        )
        filing_error_sink = _make_filing_error_sink(manager_cik, metrics)
        try:
            for record in edgar.iter_filings(
                manager_cik,
                since,
                sec_client=sec_client,
                skip_accessions=skip_accessions,
                shadow_sink=shadow_sink,
                error_sink=filing_error_sink,
            ):
                try:
                    _validate_filing(record)
                    stored_count = db.ingest_filing(record)
                    if stored_count != len(record.positions):
                        raise RuntimeError(
                            "DB position count mismatch "
                            f"accession_no={record.accession_no} "
                            f"expected={len(record.positions)} stored={stored_count}"
                        )
                except Exception as exc:  # noqa: BLE001 - 한 공시 실패가 같은 운용사의 다른 공시를 막지 않는다.
                    log.error(
                        "accession_no=%s failed: %s", record.accession_no, exc
                    )
                    metrics["failures"].append(
                        {
                            "manager_cik": manager_cik,
                            "accession_no": record.accession_no,
                            "step": "validate_or_ingest",
                            "error": repr(exc),
                        }
                    )
                    continue

                metrics["filings"] += 1
                metrics["positions"] += stored_count
                if record.accession_no in stored_at_start:
                    metrics["reprocessed_filings"] += 1
                else:
                    metrics["new_filings"] += 1
                stored.add(record.accession_no)

                if not record.positions:
                    log.info(
                        "accession_no=%s stored as zero-holdings filing",
                        record.accession_no,
                    )
                    continue

                identifiers = {
                    (position.cusip, position.identifier_type)
                    for position in record.positions
                }
                checked, requests_made, statuses = _resolve_tickers(
                    identifiers,
                    cache,
                    universe_tickers=universe_tickers,
                )
                metrics["cusips_checked"] += checked
                metrics["identifiers_checked"] += checked
                metrics["openfigi_requests"] += requests_made
                for status, count in statuses.items():
                    metrics["mapping_statuses"][status] = (
                        metrics["mapping_statuses"].get(status, 0) + count
                    )
                if statuses.get("provider_failed"):
                    metrics["failures"].append(
                        {
                            "manager_cik": manager_cik,
                            "accession_no": record.accession_no,
                            "step": "map_identifiers",
                            "error": f"provider failed identifiers={statuses['provider_failed']}",
                            "type": "OpenFigiProviderError",
                        }
                    )
        except Exception as exc:  # noqa: BLE001 - 한 운용사 실패로 전체를 중단하지 않는다.
            provider_error = (
                exc
                if isinstance(exc, GuruEtlError)
                else GuruProviderError(manager_cik, exc)
            )
            log.error(
                "manager_cik=%s failed: %s",
                manager_cik,
                provider_error,
            )
            metrics["managers_failed"] += 1
            metrics["failures"].append(
                {
                    "manager_cik": manager_cik,
                    "step": "iter_filings",
                    "error": repr(provider_error),
                    "type": type(provider_error).__name__,
                }
            )

    if metrics["managers_failed"] == len(manager_ciks):
        raise AllGuruManagersFailedError("all active guru managers failed")
    return metrics


def run(
    backfill_from: str | None = None,
    *,
    lookback_days: int = POLL_WINDOW_DAYS,
    include_existing: bool = False,
    sec_client: Any | None = None,
) -> dict:
    t0 = time.monotonic()
    metrics = _run(
        backfill_from,
        lookback_days=lookback_days,
        include_existing=include_existing,
        sec_client=sec_client,
    )
    from investment_agent.data.institutional.application.retention import prune_history

    prune_history()
    metrics["duration_sec"] = elapsed_sec(t0)
    log.info("institutional ETL done: %s", metrics)
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.data.institutional.application.etl")
    add_backfill_from_arg(parser)
    parser.add_argument(
        "--include-existing",
        action="store_true",
        help=(
            "Reparse filings already stored in the selected window. "
            "The ingest RPC replaces each filing atomically."
        ),
    )
    parser.add_argument(
        "--reparse-since",
        metavar="YYYY-MM-DD",
        help=(
            "Reparse all discovered filings, including existing ones, "
            "from this date."
        ),
    )
    args = parser.parse_args(argv)
    if args.reparse_since and args.backfill_from:
        parser.error("--reparse-since cannot be used with --backfill-from")

    parser.error(
        "use investment_agent.data.institutional.commands.institutional_daily or "
        "investment_agent.data.institutional.commands.institutional_backfill"
    )


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    sys.exit(main())
