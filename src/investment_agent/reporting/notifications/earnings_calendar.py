"""주간 실적 캘린더를 위한 v1 fundamentals·universe reader."""
from __future__ import annotations

from typing import Any

from investment_agent.config import load_config
from investment_agent.data.fundamentals.repository import FundamentalsRepository
from investment_agent.data.universe.repository import UniverseRepository
from investment_agent.platform.db.postgres import Database

SCHEMA_UNIVERSE = "universe"
T_ENTITIES = "entities"


class EarningsCalendarStore:
    """카드에 필요한 행만 읽는다. 보낼지 말지는 알림 원장이 판단한다."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._universe = UniverseRepository(db)
        self._fundamentals = FundamentalsRepository(db)

    @classmethod
    def configured(cls, config: Any | None = None) -> "EarningsCalendarStore":
        return cls(Database.from_config(config or load_config()))

    @property
    def database(self) -> Database:
        return self._db

    def _members(self) -> list[Any]:
        return [member for member in self._universe.watchlist_members("fundamentals")
                if member.is_active]

    def watchlist_members(self) -> list[dict[str, Any]]:
        return [{"ticker": member.ticker, "security_id": member.security_id}
                for member in self._members()]

    def schedule_snapshots(self, tickers: list[str]) -> list[dict[str, Any]]:
        members = {member.ticker: member for member in self._members() if member.ticker in tickers}
        if not members:
            return []
        rows = self._fundamentals.schedule_snapshots(
            [member.security_id for member in members.values()]
        )
        by_id = {member.security_id: ticker for ticker, member in members.items()}
        return [{**row, "ticker": by_id.get(int(row["security_id"]))}
                for row in rows if by_id.get(int(row["security_id"]))]

    def prior_filings(self, tickers: list[str]) -> list[dict[str, Any]]:
        if not tickers:
            return []
        securities = self._universe.securities_by_ticker(tickers)
        ciks = [security.cik for security in securities.values() if security.cik]
        rows = self._fundamentals.filing_periods(ciks)
        ticker_by_cik = {security.cik: ticker for ticker, security in securities.items()}
        return [{**row, "ticker": ticker_by_cik.get(str(row.get("cik")))}
                for row in rows if ticker_by_cik.get(str(row.get("cik")))]

    def load_names(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        securities = self._universe.securities_by_ticker(tickers)
        ciks = [security.cik for security in securities.values() if security.cik]
        if not ciks:
            return {}
        rows = self._db.select_in_chunks(
            schema=SCHEMA_UNIVERSE,
            table=T_ENTITIES,
            columns="cik,company_name,company_name_ko,sic_industry_name",
            filter_column="cik",
            values=ciks,
            order_by="cik",
        )
        by_cik = {str(row["cik"]): row for row in rows}
        return {
            ticker: {
                "name": (by_cik.get(str(security.cik), {}).get("company_name") or ticker),
                "name_ko": by_cik.get(str(security.cik), {}).get("company_name_ko"),
                "sic_industry": by_cik.get(str(security.cik), {}).get("sic_industry_name"),
            }
            for ticker, security in securities.items()
        }


__all__ = ["EarningsCalendarStore"]
