"""v1 universe·market 원천 재수집 진입점."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, timedelta

from investment_agent.config import load_config
from investment_agent.data.universe.infrastructure.sources import sec
from investment_agent.data.fundamentals.infrastructure.sec.companyfacts import (
    all_financial_filings,
    companyfacts,
    companyfacts_to_facts,
)
from investment_agent.data.fundamentals.domain.normalization import build_company_financials
from investment_agent.data.fundamentals.service import refresh_fundamentals
from investment_agent.data.institutional.application.service import refresh_institutional
from investment_agent.data.market.application.refresh_market import refresh_market
from investment_agent.data.universe.repository import UniverseRepository
from investment_agent.data.universe.application.refresh_universe import refresh_universe
from investment_agent.platform.db.postgres import Database
from investment_agent.platform.logging import get_logger

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.operations.refresh")
    parser.add_argument(
        "--scope", choices=("universe", "fundamentals", "market", "institutional", "all"), default="all",
        help="universe는 identity gate이고, 나머지 데이터 영역은 FK·원천 순서로 실행한다.",
    )
    parser.add_argument(
        "--market-lookback-days", type=int, default=14,
        help="완결된 Yahoo 일봉의 재수집 기간(양수).",
    )
    parser.add_argument(
        "--fundamentals-years", type=int, default=10,
        help="SEC CompanyFacts 재수집 이력 연수(양수, 정정공시 포함).",
    )
    parser.add_argument(
        "--institutional-years", type=int, default=10,
        help="SEC 13F 재수집 이력 연수(양수, 정정신고 포함).",
    )
    args = parser.parse_args(argv)
    if args.market_lookback_days < 1:
        parser.error("--market-lookback-days must be positive")
    if args.fundamentals_years < 1:
        parser.error("--fundamentals-years must be positive")
    if args.institutional_years < 1:
        parser.error("--institutional-years must be positive")
    config = load_config()
    db = Database.from_config(config)
    if args.scope in {"universe", "all"}:
        result = refresh_universe(db, sec_get_json=sec.get_json)
        log.info("v1_universe_complete %s", asdict(result))
        if result.sec_failures:
            log.error("v1_universe_sec_metadata_incomplete ciks=%s", list(result.sec_failures))
            return 2
    if args.scope in {"fundamentals", "all"}:
        ciks = sorted({
            security.cik
            for security in UniverseRepository(db).tracked_securities()
            if security.cik is not None
        })
        if not ciks:
            log.error("v1_fundamentals_requires_tracked_universe")
            return 2
        floor = date.today() - timedelta(days=365 * args.fundamentals_years)
        result = refresh_fundamentals(
            db,
            ciks=ciks,
            floor=floor,
            filing_source=lambda cik, cutoff: all_financial_filings(cik, cutoff=cutoff),
            companyfacts_source=companyfacts,
            facts_normalizer=companyfacts_to_facts,
            wide_builder=build_company_financials,
        )
        log.info("v1_fundamentals_complete %s", asdict(result))
        if result.failures:
            log.error("v1_fundamentals_incomplete failures=%s", list(result.failures))
            return 2
    if args.scope in {"market", "all"}:
        result = refresh_market(db, lookback_days=args.market_lookback_days)
        log.info("v1_market_complete %s", asdict(result))
    if args.scope in {"institutional", "all"}:
        from investment_agent.data.institutional.infrastructure.sources.sec13f import iter_filings

        result = refresh_institutional(
            db,
            since=date.today() - timedelta(days=365 * args.institutional_years),
            filing_source=lambda manager_cik, since: iter_filings(
                manager_cik, since.isoformat(), sec_client=sec
            ),
        )
        log.info("v1_institutional_complete %s", asdict(result))
        if result.failures:
            log.error("v1_institutional_incomplete failures=%s", list(result.failures))
            return 2
    return 0


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
