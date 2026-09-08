"""v1 fundamentals/universe/notifications reader for earnings flash."""
from __future__ import annotations

from typing import Any

from investment_agent.config import load_config
from investment_agent.data.universe.repository import UniverseRepository
from investment_agent.platform.db.postgres import Database
from investment_agent.notifications.outbox import Outbox

SCHEMA_REPORTING = "reporting"
SCHEMA_UNIVERSE = "universe"
V_EARNINGS_SURPRISE = "earnings_surprise"
T_ENTITIES = "entities"


class EarningsFlashStore:
    """속보 후보에 필요한 v1 읽기와 outbox 중복 상태만 소유한다."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._universe = UniverseRepository(db)

    @classmethod
    def configured(cls, config: Any | None = None) -> "EarningsFlashStore":
        return cls(Database.from_config(config or load_config()))

    @property
    def database(self) -> Database:
        return self._db

    def watchlist_members(self) -> list[dict[str, Any]]:
        return [
            {
                "ticker": member.ticker,
                "security_id": member.security_id,
                "watch_from": member.watch_from.isoformat() if member.watch_from else None,
            }
            for member in self._universe.watchlist_members("fundamentals")
            if member.is_active
        ]

    def processed_flash_keys(self) -> set[tuple[str, str]]:
        """이미 outbox에 등록된 (ticker, accession_no) 쌍."""
        result: set[tuple[str, str]] = set()
        for key in Outbox().sent_keys("fundamentals", kind="fundamentals_flash"):
            if not key.startswith("flash:"):
                continue
            _, ticker, accession_no = key.split(":", 2) if key.count(":") >= 2 else ("", "", "")
            if ticker and accession_no:
                result.add((ticker, accession_no))
        return result

    def load_names(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        securities = self._universe.securities_by_ticker(tickers)
        ciks = [security.cik for security in securities.values() if security.cik]
        if not ciks:
            return {}
        rows = self._db.select_in_chunks(
            schema=SCHEMA_UNIVERSE,
            table=T_ENTITIES,
            columns="cik,company_name,company_name_ko,sic_industry_name,sic_division_name",
            filter_column="cik",
            values=ciks,
            order_by="cik",
        )
        by_cik = {str(row["cik"]): row for row in rows}
        return {
            ticker: {
                "name": by_cik.get(str(security.cik), {}).get("company_name") or ticker,
                "name_ko": by_cik.get(str(security.cik), {}).get("company_name_ko"),
                "sic_industry": by_cik.get(str(security.cik), {}).get("sic_industry_name"),
                "sic_division": by_cik.get(str(security.cik), {}).get("sic_division_name"),
            }
            for ticker, security in securities.items()
        }

    def load_flash_rows(self, tickers: list[str], since: str) -> list[dict[str, Any]]:
        if not tickers:
            return []
        return self._db.select_in_chunks(
            schema=SCHEMA_REPORTING,
            table=V_EARNINGS_SURPRISE,
            columns=(
                "ticker,cik,fiscal_year,fiscal_period,period_end,filing_date,available_at,"
                "accession_no,revenue_actual,eps_actual,eps_estimate,revenue_estimate,"
                "estimate_snapshot_date,eps_analysts,eps_surprise_pct,revenue_surprise_pct,"
                "guidance_summary,operating_income_actual,net_income_actual,press_release_url"
            ),
            filter_column="ticker",
            values=tickers,
            configure=lambda query: query.gte("filing_date", since),
            order_by="ticker,filing_date,accession_no",
        )

    def sent_keys(self) -> set[str]:
        return Outbox().sent_keys("fundamentals", kind="fundamentals_flash")


__all__ = ["EarningsFlashStore", "SCHEMA_REPORTING", "V_EARNINGS_SURPRISE"]
