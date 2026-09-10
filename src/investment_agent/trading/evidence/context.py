"""기존 데이터에서 미래정보를 차단한 근거 묶음을 만든다."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from typing import Any, Protocol

from investment_agent.trading.contracts import EvidenceBundle, EvidenceItem, parse_datetime
from investment_agent.platform.serialization import canonical_json
from investment_agent.platform.clock import US_DAILY_BAR_FINALIZATION_TIME, US_MARKET_TIMEZONE
from investment_agent.research.features.layer import REQUIRED_BARS
from investment_agent.trading.evidence.tools import (
    estimate_statistics,
    fundamental_statistics,
    price_statistics,
)


class ContextRepository(Protocol):
    def market_prices(self, ticker: str, as_of_at: datetime, limit: int = 260) -> list[dict]: ...
    def technical_snapshot(self, ticker: str, as_of_at: datetime) -> list[dict]: ...
    def fundamentals(self, ticker: str, as_of_at: datetime, limit: int = 12) -> list[dict]: ...
    def fundamentals_pit(self, ticker: str, as_of_at: datetime, limit: int = 12) -> list[dict]: ...
    def estimates(self, ticker: str, as_of_at: datetime, limit: int = 12) -> dict[str, list[dict]]: ...
    def macro_snapshot(self, as_of_at: datetime) -> dict[str, Any]: ...
    def segment_snapshot(self, ticker: str, as_of_at: datetime) -> dict[str, Any]: ...
    def segment_capability(self) -> dict[str, Any]: ...
    def guru_snapshot(self, ticker: str, as_of_at: datetime) -> dict[str, Any]: ...
    def econ_snapshot(self, as_of_at: datetime, lookback_days: int = 14) -> dict[str, Any]: ...


def _latest_iso(rows: list[dict], column: str) -> str | None:
    values = [str(row[column]) for row in rows if row.get(column)]
    return max(values) if values else None


def _price_available_at(row: dict) -> datetime:
    """수집시각 없는 canonical 봉도 미국 일봉 확정시각 이후에만 사용한다."""
    finalized = datetime.combine(
        date.fromisoformat(str(row["trade_date"])[:10]),
        US_DAILY_BAR_FINALIZATION_TIME, tzinfo=US_MARKET_TIMEZONE,
    ).astimezone(timezone.utc)
    ingested = row.get("ingested_at")
    return max(finalized, parse_datetime(str(ingested))) if ingested else finalized


def _fundamentals_available_at(rows: list[dict], historical: bool) -> str | None:
    """재무 wide 행의 근거 시각을 Context 계약에 맞는 UTC 시각으로 만든다."""
    if not historical:
        return _latest_iso(rows, "available_at") or _latest_iso(rows, "ingested_at")
    values = [
        f"{str(row['filed_at'])}T00:00:00+00:00"
        for row in rows
        if row.get("filed_at")
    ]
    return max(values) if values else None


def _id(domain: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:12]
    return f"EV-{domain.upper()}-{digest}"


def _item(
    domain: str,
    source: str,
    observed_at: str,
    available_at: str,
    payload: dict[str, Any],
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=_id(domain, payload),
        domain=domain,
        source=source,
        observed_at=observed_at,
        available_at=parse_datetime(available_at).isoformat(),
        timing_status="known",
        payload=payload,
    )


# 프롬프트에 싣는 공시 원자료 행 수. 실측(2026-09-03)으로 12행이 30,717자였고
# 그대로 실으면 Azure 배포의 50,000토큰/분 한도에서 종목 하나를 못 끝낸다.
FILING_ROWS_IN_PROMPT = 4


class ContextBuilder:
    def __init__(self, repository: ContextRepository):
        self.repository = repository

    def build(
        self,
        ticker: str,
        as_of_at: datetime,
        *,
        source_kind: str = "live_shadow",
    ) -> EvidenceBundle:
        if as_of_at.tzinfo is None:
            raise ValueError("as_of_at must include timezone")
        as_of_at = as_of_at.astimezone(timezone.utc)
        items: list[EvidenceItem] = []
        missing: list[str] = []
        warnings: list[str] = []

        prices = self.repository.market_prices(ticker, as_of_at)
        prices = sorted(
            (row for row in prices if _price_available_at(row) <= as_of_at),
            key=lambda row: str(row["trade_date"]), reverse=True,
        )
        if prices:
            items.append(_item(
                "market", "market.prices_daily", str(prices[0]["trade_date"]),
                max(_price_available_at(row) for row in prices).isoformat(),
                # FeatureLayer가 20거래일 수익률을 계산하려면 21개 봉이 필요하다.
                # 상수를 공유하지 않으면 그 feature가 조용히 영구 결측이 된다.
                {"statistics": price_statistics(prices), "latest_bars": prices[:REQUIRED_BARS]},
            ))
        else:
            missing.append("market: 시점 기준 사용 가능한 가격 없음")

        technical = self.repository.technical_snapshot(ticker, as_of_at)
        if technical:
            items.append(_item(
                "technical", "Research DuckDB feature_signals_daily",
                str(technical[0]["trade_date"]), str(technical[0]["ingested_at"]),
                {key: value for key, value in technical[0].items() if key != "ingested_at"},
            ))
            warnings.append(
                "technical 비재귀 지표는 사후 가격 보정 누출 가능성이 있어 RSI/MACD 고정 행만 사용"
            )
        else:
            missing.append("technical: 시점 기준 기술지표 없음")

        fundamentals = (
            self.repository.fundamentals_pit(ticker, as_of_at)
            if source_kind == "historical_replay" and hasattr(self.repository, "fundamentals_pit")
            else self.repository.fundamentals(ticker, as_of_at)
        )
        if fundamentals:
            items.append(_item(
                "fundamentals",
                "SEC EDGAR/FSDS via fundamentals.financials",
                str(fundamentals[0]["filed_at"]),
                str(_fundamentals_available_at(
                    fundamentals, source_kind == "historical_replay",
                )),
                # 통계는 전체 이력으로 계산하고, 원자료는 최근 분기만 싣는다.
                # 프롬프트가 provider의 분당 토큰 한도를 넘으면 판단이 시작조차 못 한다.
                {
                    "statistics": fundamental_statistics(fundamentals),
                    "filings": fundamentals[:FILING_ROWS_IN_PROMPT],
                    "filings_total": len(fundamentals),
                },
            ))
        else:
            missing.append(
                "fundamentals: cutoff 이전 canonical financials 재무 없음"
                if source_kind == "historical_replay"
                else "fundamentals: 시점 기준 공시 재무 없음"
            )

        estimates = self.repository.estimates(ticker, as_of_at)
        consensus = estimates.get("consensus", [])
        if consensus:
            items.append(_item(
                "estimates", "yfinance observed snapshots",
                str(max(str(row.get("snapshot_date") or "") for row in consensus)),
                str(_latest_iso(consensus, "collected_at")),
                {
                    "consensus_statistics": estimate_statistics(consensus),
                    "observed_consensus": consensus,
                    "reconstructed_rows_excluded": True,
                },
            ))
        else:
            missing.append("estimates: 시점 기준 실제 관측 컨센서스 없음")

        if source_kind == "historical_replay":
            missing.append(
                "macro: 시장 상태 관측의 point-in-time 이력이 없어 historical replay에서 제외"
            )
        else:
            macro = self.repository.macro_snapshot(as_of_at)
            if macro.get("run") and macro.get("observations"):
                run = macro["run"]
                collected = [row.get("created_at") for row in macro["observations"]]
                if all(collected):
                    available_at = max(str(value) for value in collected)
                else:
                    available_at = str(run["finished_at"])
                    warnings.append(
                        "macro 관측값 일부에 수집시각(created_at)이 없어 그 실행의 완료 시각을 가용시각으로 사용"
                    )
                items.append(_item(
                    "macro", "macro.series+observations",
                    str(max(str(row["obs_date"]) for row in macro["observations"])),
                    available_at,
                    {"collection_run": run, "latest_observations": macro["observations"]},
                ))
            else:
                missing.append("macro: 시점 기준 완료된 수집 실행 또는 관측값 없음")

        segments = self.repository.segment_snapshot(ticker, as_of_at)
        if segments.get("filings") and segments.get("metrics"):
            filings = segments["filings"]
            items.append(_item(
                "segments", "SEC XBRL via fundamentals.segment_metrics",
                str(filings[0]["filing_date"]), str(_latest_iso(filings, "updated_at")), segments,
            ))
        else:
            capability = (
                self.repository.segment_capability()
                if hasattr(self.repository, "segment_capability") else {}
            )
            if capability.get("availability") == "unavailable":
                missing.append(
                    "segments: provider unavailable - "
                    + str(capability.get("unavailable_reason") or "trusted source 없음")
                )
            else:
                missing.append("segments: 시점 기준 검증된 세그먼트 없음")

        gurus = self.repository.guru_snapshot(ticker, as_of_at)
        if gurus.get("filings") and gurus.get("positions"):
            filings = gurus["filings"]
            items.append(_item(
                "gurus", "SEC 13F via gurus",
                str(filings[0]["period_end"]), str(_latest_iso(filings, "accepted_at")), gurus,
            ))
        else:
            missing.append("gurus: 추적 매니저의 매핑된 보유 근거 없음")

        econ = self.repository.econ_snapshot(as_of_at)
        econ_rows = econ.get("events", []) + econ.get("results", []) + econ.get("forecasts", [])
        if econ_rows:
            items.append(_item(
                "economic_calendar", "econ_calendar release measures + forecasts",
                as_of_at.date().isoformat(), str(_latest_iso(econ_rows, "collected_at")), econ,
            ))
        else:
            missing.append("economic_calendar: 시점 기준 관련 발표 일정·관측값 없음")

        missing.append(
            "news_archive: Supabase 시점 저장소 없음; live 외부 provider 사용 여부는 Agent 정책에 따름"
        )
        return EvidenceBundle(
            ticker=ticker.upper(),
            as_of_at=as_of_at.isoformat(),
            source_kind=source_kind,
            evidence=tuple(items),
            missing_data=tuple(dict.fromkeys(missing)),
            warnings=tuple(dict.fromkeys(warnings)),
        )
