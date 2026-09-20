"""주간 실적 캘린더를 위한 v1 fundamentals·universe reader."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from investment_agent.config import load_config
from investment_agent.data.fundamentals.repository import FundamentalsRepository
from investment_agent.data.universe.repository import UniverseRepository
from investment_agent.platform.clock import kst_today
from investment_agent.platform.db.postgres import Database

SCHEMA_UNIVERSE = "universe"
T_ENTITIES = "entities"

# 컨센서스가 이 기간 안에 다시 관측됐어야 "지금의 값"으로 싣는다. 수집이 매일 돌아
# 유효한 값은 며칠 안에 다시 보이므로, 이보다 오래 안 보였으면 끊긴 것이다.
CONSENSUS_SEEN_WITHIN_DAYS = 14
_CONSENSUS_FIELDS = ("eps_avg", "eps_analysts", "revenue_avg")


def attach_consensus(
    snapshots: Sequence[Mapping[str, Any]],
    consensus: Mapping[tuple[int, int, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """일정 행에 같은 대상 분기의 컨센서스를 붙인다.

    일정은 상태 버전마다 행이 있지만 컨센서스는 대상 분기에 하나라서, 같은 분기의 모든
    버전이 같은 값을 받는다. 그래야 예정일이 바뀐 이력(shifted 판정)이 컨센서스
    때문에 갈라지지 않는다. 컨센서스가 없는 분기는 손대지 않는다 — 카드가 그 칸을 빈 채로
    두는 것이 없는 숫자를 채우는 것보다 낫다.
    """
    out: list[dict[str, Any]] = []
    for row in snapshots:
        key = (int(row["security_id"]), int(row["target_fiscal_year"]),
               str(row["target_fiscal_period"]))
        found = consensus.get(key)
        out.append({**row, **{name: found.get(name) for name in _CONSENSUS_FIELDS}}
                   if found else dict(row))
    return out


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

    def schedule_snapshots(
        self, tickers: list[str], *, today: date | None = None
    ) -> list[dict[str, Any]]:
        """일정 스냅샷에 대상 분기의 컨센서스를 붙여 돌려준다. today는 컨센서스 조회 창의 기준이다."""
        members = {member.ticker: member for member in self._members() if member.ticker in tickers}
        if not members:
            return []
        security_ids = [member.security_id for member in members.values()]
        rows = self._fundamentals.schedule_snapshots(security_ids)
        consensus = self._fundamentals.latest_consensus(
            security_ids,
            seen_since=(today or kst_today()) - timedelta(days=CONSENSUS_SEEN_WITHIN_DAYS),
        )
        by_id = {member.security_id: ticker for ticker, member in members.items()}
        return [{**row, "ticker": by_id[int(row["security_id"])]}
                for row in attach_consensus(rows, consensus) if int(row["security_id"]) in by_id]

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


__all__ = ["CONSENSUS_SEEN_WITHIN_DAYS", "EarningsCalendarStore", "attach_consensus"]
