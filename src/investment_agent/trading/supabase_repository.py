"""Trading 원장과 domain owner 사이의 저장소 경계.

판단·신호·모델·포트폴리오의 영구 원장은 v1 ``trading`` schema가 소유한다.
재계산 가능한 research 산출물은 Supabase에 저장하지 않는다.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

from investment_agent.trading.decision.candidate_ranker import (
    assemble_candidate_features,
    rank_candidate_features,
    validate_live_candidate_as_of,
)
from investment_agent.trading.contracts import parse_datetime
from investment_agent.platform.serialization import canonical_json
from investment_agent.trading.portfolio.contracts import SecurityProposal
from investment_agent.research.promotion.gate import (
    EvaluationSummary,
    PromotionDecision,
    aggregate_evaluations,
)
from investment_agent.trading.portfolio.signal_book import SignalBatch, SignalBook, SignalRecord
from investment_agent.execution.orders.snapshots import AccountSnapshot
from investment_agent.research.rl.contracts import (
    FeatureSnapshot,
    ForwardReturnLabel,
    normalize_symbols,
)
from investment_agent.trading.decision.universe import normalize_ticker
from investment_agent.platform.logging import get_logger
from investment_agent.platform.db.postgres import sb
from investment_agent.trading.decision.contracts import Event, EventFeatureSnapshot
from investment_agent.research.datasets.contracts import TrainingSample
from investment_agent.data.macro.repository import MacroRepository
from investment_agent.platform.db.postgres import Database
from investment_agent.research.storage.repository import ResearchStore
from investment_agent.data.macro.releases import db as econ_calendar_db
from investment_agent.data.institutional import persistence as institutional_persistence
from investment_agent.data.fundamentals.infrastructure.supabase import (
    expectations as fundamentals_expectations,
    segment_metrics as fundamentals_segments,
    share_class_snapshots as fundamentals_shares,
)
from investment_agent.data.market import persistence as market_db
from investment_agent.research.features import db as features_db
from investment_agent.data.universe.persistence import (
    select_security_profiles,
    select_security_ids_by_ticker,
    select_sp500_membership_snapshots,
    select_tickers_by_security_id,
    select_tracked_tickers,
)

# 매크로 최신값 탐색 창(일). 갱신이 멎은 지표도 마지막 값을 잃지 않을 만큼 넉넉히.

log = get_logger(__name__)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("as_of_at must include timezone")
    return value.astimezone(timezone.utc).isoformat()


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _security_id(ticker: str) -> int:
    symbol = normalize_ticker(ticker)
    value = select_security_ids_by_ticker([symbol]).get(symbol)
    if value is None:
        raise RuntimeError(f"unknown universe security: {symbol}")
    return value


def _security_ids(tickers: Sequence[str]) -> dict[str, int]:
    symbols = sorted({normalize_ticker(ticker) for ticker in tickers})
    result = select_security_ids_by_ticker(symbols)
    missing = [symbol for symbol in symbols if symbol not in result]
    if missing:
        raise RuntimeError(f"unknown universe securities: {missing[:10]}")
    return result


def _segment_candidate_signals(
    filings: Sequence[dict[str, Any]],
    metrics: Sequence[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    """종목별 최신 공시의 세그먼트 집중도와 검증 품질만 축약한다."""
    latest_by_ticker: dict[str, dict[str, Any]] = {}
    for row in filings:
        symbol = normalize_ticker(row.get("ticker"))
        current = latest_by_ticker.get(symbol)
        key = (str(row.get("filing_date") or ""), str(row.get("accession_no") or ""))
        current_key = (
            str(current.get("filing_date") or ""),
            str(current.get("accession_no") or ""),
        ) if current else ("", "")
        if symbol and key > current_key:
            latest_by_ticker[symbol] = row

    metrics_by_accession: dict[str, list[dict[str, Any]]] = {}
    for row in metrics:
        metrics_by_accession.setdefault(str(row.get("accession_no") or ""), []).append(row)
    result: dict[str, dict[str, float]] = {}
    for symbol, filing in latest_by_ticker.items():
        rows = metrics_by_accession.get(str(filing.get("accession_no") or ""), [])
        axis_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            revenue = _finite(row.get("revenue"))
            if revenue is None or revenue <= 0:
                continue
            key = (str(row.get("segment_type") or ""), str(row.get("axis") or ""))
            axis_groups.setdefault(key, []).append(row)
        candidates: list[tuple[float, str, float]] = []
        for key, group in axis_groups.items():
            revenues = [float(row["revenue"]) for row in group]
            total = sum(revenues)
            if total <= 0:
                continue
            coverage_values = [
                value for value in (_finite(row.get("coverage_ratio")) for row in group)
                if value is not None
            ]
            coverage = (
                sum(min(1.0, max(0.0, value)) for value in coverage_values)
                / len(coverage_values)
                if coverage_values else 0.0
            )
            verified = sum(row.get("quality_status") == "verified" for row in group) / len(group)
            quality = coverage * verified
            concentration = sum((revenue / total) ** 2 for revenue in revenues)
            candidates.append((quality, "|".join(key), concentration))
        if candidates:
            quality, _axis_key, concentration = max(
                candidates, key=lambda item: (item[0], item[1])
            )
            result[symbol] = {
                "quality": quality,
                "concentration": concentration,
            }
    return result


def _guru_candidate_signals(
    current_by_manager: Mapping[str, Mapping[str, Any]],
    previous_by_manager: Mapping[str, Mapping[str, Any]],
    holdings: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, float | str]]:
    """PIT-effective holdings에서 후보용 raw Guru feature를 만든다.

    특정 원시 filing 하나를 고르는 대신, ``effective_accession_no``별 현재/직전
    공개 포트폴리오를 비교한다. 따라서 RESTATEMENT와 NEW HOLDINGS의 공개 시각을
    넘겨보지 않고, PUT/CALL/PRN은 equity consensus에서 제외한다.
    """
    equity_by_accession: dict[str, list[Mapping[str, Any]]] = {}
    for row in holdings:
        if row.get("position_kind") != "SHARES" or row.get("quantity_type") != "SH":
            continue
        equity_by_accession.setdefault(
            str(row.get("effective_accession_no") or ""), []
        ).append(row)

    result: dict[str, dict[str, Any]] = {}
    for manager, current_event in current_by_manager.items():
        current_accession = str(current_event.get("effective_accession_no") or "")
        previous_event = previous_by_manager.get(manager)
        previous_accession = str(
            previous_event.get("effective_accession_no") or ""
        ) if previous_event else ""
        current_rows = equity_by_accession.get(current_accession, [])
        previous_rows = equity_by_accession.get(previous_accession, [])
        current_total = sum(
            float(row.get("value_usd") or 0) for row in current_rows
        )

        def by_ticker(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, float]]:
            grouped: dict[str, dict[str, float]] = {}
            for row in rows:
                symbol = normalize_ticker(row.get("ticker"))
                if not symbol or row.get("mapping_status") not in {"mapped", "historical"}:
                    continue
                item = grouped.setdefault(symbol, {"quantity": 0.0, "value_usd": 0.0})
                item["quantity"] += float(row.get("quantity") or 0)
                item["value_usd"] += float(row.get("value_usd") or 0)
            return grouped

        current_by_ticker = by_ticker(current_rows)
        previous_by_ticker = by_ticker(previous_rows)
        for symbol in sorted(current_by_ticker.keys() | previous_by_ticker.keys()):
            current = current_by_ticker.get(symbol)
            previous = previous_by_ticker.get(symbol)
            feature = result.setdefault(
                symbol,
                {
                    "holder_count": 0.0,
                    "new_buy_count": 0.0,
                    "add_count": 0.0,
                    "hold_count": 0.0,
                    "reduce_count": 0.0,
                    "exit_count": 0.0,
                    "total_value_usd": 0.0,
                    "quantity_change_values": [],
                    "max_weight_pct": 0.0,
                },
            )
            if current is not None:
                feature["holder_count"] += 1.0
                feature["total_value_usd"] += current["value_usd"]
                feature["max_weight_pct"] = max(
                    feature["max_weight_pct"],
                    100 * current["value_usd"] / current_total if current_total else 0.0,
                )
            if previous is None:
                feature["new_buy_count"] += 1.0
            elif current is None:
                feature["exit_count"] += 1.0
            elif current["quantity"] > previous["quantity"]:
                feature["add_count"] += 1.0
                if previous["quantity"]:
                    feature["quantity_change_values"].append(
                        100 * (current["quantity"] - previous["quantity"])
                        / previous["quantity"]
                    )
            elif current["quantity"] < previous["quantity"]:
                feature["reduce_count"] += 1.0
                if previous["quantity"]:
                    feature["quantity_change_values"].append(
                        100 * (current["quantity"] - previous["quantity"])
                        / previous["quantity"]
                    )
            else:
                feature["hold_count"] += 1.0

    output: dict[str, dict[str, float | str]] = {}
    for symbol, values in result.items():
        average_values = values.pop("quantity_change_values")
        accumulation = values["new_buy_count"] + values["add_count"]
        distribution = values["reduce_count"] + values["exit_count"]
        output[symbol] = {
            **{key: float(value) for key, value in values.items()},
            "avg_quantity_change_pct": (
                sum(average_values) / len(average_values) if average_values else 0.0
            ),
            "consensus": (
                "accumulating" if accumulation > distribution
                else "distributing" if accumulation < distribution
                else "holding"
            ),
        }
    return output


def _feature_snapshot(row: dict[str, Any]) -> FeatureSnapshot:
    """저장 hash까지 다시 계산해 변조·레거시 행을 fail-closed한다."""
    snapshot = FeatureSnapshot(
        feature_version=str(row["feature_version"]),
        as_of_at=str(row["as_of_at"]),
        ticker=str(row["ticker"]),
        available_at=str(row["available_at"]),
        is_available=row["is_available"],
        features=dict(row["features"]),
        source_ids=tuple(row["source_ids"]),
        provenance=dict(row["provenance"]),
    )
    if str(row.get("input_hash") or "") != snapshot.input_hash:
        raise RuntimeError("stored RL feature input_hash does not match its provenance")
    return snapshot


def _training_label(row: dict[str, Any]) -> ForwardReturnLabel:
    """label ID를 재계산해 feature와 다른 시점의 라벨 결합을 차단한다."""
    label = ForwardReturnLabel(
        feature_version=str(row["feature_version"]),
        as_of_at=str(row["as_of_at"]),
        ticker=str(row["ticker"]),
        forward_end_at=str(row["forward_end_at"]),
        label_available_at=str(row["label_available_at"]),
        forward_return=float(row["forward_return"]),
        benchmark_forward_return=float(row["benchmark_forward_return"]),
    )
    if str(row.get("label_id") or "") != label.label_id:
        raise RuntimeError("stored RL label_id does not match its payload")
    return label


ECON_MAX_ROWS_PER_KIND = 12
_ECON_RELEASE_KEYS = (
    "event_key", "series_id", "ref_period", "scheduled_at", "status", "schedule_confidence",
)
#: 예상값 출처의 우선순위. 시장 컨센서스가 있으면 그것을, 없으면 nowcast를,
#: 그것도 없으면 자체 모델을 쓴다.
_ECON_FORECAST_KEYS = (
    "closing_survey_value", "closing_nowcast_value", "closing_own_model_value",
)


def _nearest_rows(
    rows: list[dict[str, Any]], *, point: datetime, limit: int
) -> list[dict[str, Any]]:
    """cutoff에 가까운 순으로 limit개만 남기고, 다시 시간순으로 되돌린다."""
    if len(rows) <= limit:
        return rows

    def distance(row: dict[str, Any]) -> float:
        scheduled = (row.get("release") or {}).get("scheduled_at")
        if not scheduled:
            return float("inf")
        try:
            return abs((parse_datetime(str(scheduled)) - point).total_seconds())
        except (TypeError, ValueError):
            return float("inf")

    nearest = sorted(rows, key=distance)[:limit]
    return sorted(nearest, key=lambda row: str((row.get("release") or {}).get("scheduled_at") or ""))


class SupabaseRepository:
    """LLM에는 노출하지 않는 제한된 읽기 도구와 판단 저장소."""

    @staticmethod
    def _trading_repository():
        """v1 trading 원장의 domain owner를 지연 생성한다."""
        from investment_agent.trading.repository import TradingRepository

        return TradingRepository()

    def current_tracked_tickers(self) -> list[str]:
        """범용 수집 게이트 universe.securities.is_tracked의 현재 종목을 반환한다."""
        return sorted({str(ticker).upper() for ticker in select_tracked_tickers()})
    def historical_sp500_membership(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """universe 스키마의 owner에게 위임한다."""
        return select_sp500_membership_snapshots(start_date=start_date, end_date=end_date)
    def _candidate_last_analyzed(
        self,
        tickers: Sequence[str],
        *,
        as_of_at: datetime,
    ) -> dict[str, datetime]:
        """실제로 성공 판단이 저장된 case만 마지막 분석 시각으로 인정한다.

        판단 원장은 Supabase가 아니라 로컬 runtime이 소유한다. 전에는 여기서만
        Postgres `trading` 스키마를 읽고 있었는데 그 스키마는 선언에 없다 —
        Data API가 닫혀 있는 동안 모든 요청이 같은 오류로 막혀서 그 사실이
        드러나지 않았고, 열자마자 후보 선정이 PGRST106으로 죽었다.
        """
        from investment_agent.reporting.readers.runtime import read_local_rows

        members = {normalize_ticker(ticker) for ticker in tickers}
        latest: dict[str, datetime] = {}
        for row in read_local_rows("security_decisions"):
            if str(row.get("status") or "") not in {"completed", "abstained"}:
                continue
            symbol = normalize_ticker(str(row.get("ticker") or ""))
            if symbol not in members:
                continue
            raw = str(row.get("as_of_at") or "")
            if not raw:
                continue
            analyzed_at = parse_datetime(raw).astimezone(timezone.utc)
            if analyzed_at > as_of_at:
                continue  # 미래 판단은 이 as_of 기준의 coverage가 아니다.
            current = latest.get(symbol)
            if current is None or analyzed_at > current:
                latest[symbol] = analyzed_at
        return latest

    def _candidate_market_rows(
        self,
        tickers: Sequence[str],
        as_of_at: datetime,
    ) -> list[dict[str, Any]]:
        since = as_of_at.date() - timedelta(days=60)
        # 창 하나를 한 번에 읽는다. 종목마다 부르면 종목당 왕복이 네 번이고, 봉은
        # 전체 이력을 읽은 뒤 잘라 낸다 — 후보 선정은 창 안의 종가·거래량만 본다.
        return market_db.price_window_as_of(
            sorted({normalize_ticker(value) for value in tickers}),
            start=since,
            as_of_at=as_of_at,
        )

    def _candidate_technical_rows(
        self,
        tickers: Sequence[str],
        as_of_at: datetime,
    ) -> list[dict[str, Any]]:
        since = (as_of_at.date() - timedelta(days=21)).isoformat()
        wanted = {normalize_ticker(value) for value in tickers}
        until = as_of_at.date().isoformat()
        rows: list[dict[str, Any]] = []
        # 창 하나를 한 번에 읽는다. 종목마다 부르면 저장소 연결이 종목 수만큼 열린다.
        for row in features_db.features_since(since):
            if normalize_ticker(str(row.get("ticker") or "")) not in wanted:
                continue
            if str(row.get("trade_date") or "") > until:
                continue
            ingested_at = row.get("ingested_at")
            if ingested_at and parse_datetime(str(ingested_at)) > as_of_at:
                continue
            rows.append(dict(row))
        return sorted(rows, key=lambda row: (str(row.get("ticker")), str(row.get("trade_date"))))

    def _candidate_fundamental_rows(
        self,
        tickers: Sequence[str],
        as_of_at: datetime,
    ) -> list[dict[str, Any]]:
        since = as_of_at.date() - timedelta(days=1100)
        # 종목마다 부르면 종목당 왕복이 세 번이다(증권→재무→공시).
        rows = [
            row for row in fundamentals_expectations.securities_fundamentals_as_of(
                sorted({normalize_ticker(value) for value in tickers}), as_of_at, limit=520
            )
            if since.isoformat() <= str(row.get("filed_at") or "")
            and str(row.get("filed_at") or "") <= as_of_at.date().isoformat()
        ]
        return sorted(
            rows,
            key=lambda row: (
                str(row.get("ticker") or ""),
                str(row.get("filed_at") or ""),
                str(row.get("period_end") or ""),
            ),
        )

    def _candidate_segment_signals(
        self,
        tickers: Sequence[str],
        as_of_at: datetime,
    ) -> dict[str, dict[str, float]]:
        # 종목마다 부르면 종목당 왕복이 네 번 이상이다(증권→공시→처리상태→지표).
        snapshots = fundamentals_segments.segment_snapshots_as_of(
            sorted({normalize_ticker(value) for value in tickers}), as_of_at
        )
        filings: list[dict[str, Any]] = []
        metrics: list[dict[str, Any]] = []
        for snapshot in snapshots.values():
            filings.extend(snapshot.get("filings", []))
            metrics.extend(snapshot.get("metrics", []))
        return _segment_candidate_signals(filings, metrics)


    def _candidate_guru_signals(
        self,
        tickers: Sequence[str],
        as_of_at: datetime,
    ) -> dict[str, dict[str, float | str]]:
        current, previous, holdings = self._effective_guru_state(as_of_at)
        all_signals = _guru_candidate_signals(current, previous, holdings)
        wanted = {normalize_ticker(ticker) for ticker in tickers}
        return {ticker: signal for ticker, signal in all_signals.items() if ticker in wanted}

    def _effective_guru_state(
        self,
        as_of_at: datetime,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
        """institutional 스키마의 owner에게 위임한다 — 유효 신고 선택 규칙은 그쪽 domain 지식이다."""
        return institutional_persistence.effective_portfolio_state(as_of_at)
    def candidate_tickers(
        self,
        limit: int = 50,
        *,
        as_of_at: datetime,
    ) -> list[str]:
        """tracked 전체를 coverage 우선·다중 도메인 신호 순으로 결정론적 정렬한다."""
        as_of_at = validate_live_candidate_as_of(as_of_at)
        tickers = self.current_tracked_tickers()
        if not tickers:
            return []
        last_analyzed = self._candidate_last_analyzed(tickers, as_of_at=as_of_at)
        features = assemble_candidate_features(
            tickers,
            last_analyzed_at=last_analyzed,
            market_rows=self._candidate_market_rows(tickers, as_of_at),
            technical_rows=self._candidate_technical_rows(tickers, as_of_at),
            fundamental_rows=self._candidate_fundamental_rows(tickers, as_of_at),
            segment_signals=self._candidate_segment_signals(tickers, as_of_at),
            guru_signals=self._candidate_guru_signals(tickers, as_of_at),
        )
        ranking = rank_candidate_features(features, as_of_at=as_of_at, limit=limit)
        log.info(
            "ai investor candidate ranking as_of=%s universe=%d selected=%s scores=%s",
            as_of_at.isoformat(),
            len(tickers),
            [row.ticker for row in ranking],
            {row.ticker: row.score for row in ranking},
        )
        return [row.ticker for row in ranking]

    def sp500_sector_map(self, tickers: list[str] | tuple[str, ...]) -> dict[str, str]:
        symbols = sorted({str(ticker).upper() for ticker in tickers})
        if not symbols:
            return {}
        rows = select_security_profiles(symbols, tracked_only=True)
        return {
            str(row["ticker"]).upper(): str(row["sic_division"])
            for row in rows if row.get("sic_division")
        }

    def market_prices(self, ticker: str, as_of_at: datetime, limit: int = 260) -> list[dict]:
        """market 스키마의 owner에게 위임한다 — 조회 규칙을 두 곳에 두지 않는다."""
        return market_db.price_history_as_of(ticker, as_of_at, limit=limit)
    def technical_snapshot(self, ticker: str, as_of_at: datetime) -> list[dict]:
        """Research DuckDB feature store의 owner에게 위임한다."""
        return features_db.latest_signal_as_of(ticker, as_of_at)
    def fundamentals(self, ticker: str, as_of_at: datetime, limit: int = 12) -> list[dict]:
        """fundamentals 스키마의 owner에게 위임한다."""
        return fundamentals_expectations.security_fundamentals_as_of(ticker, as_of_at, limit=limit)
    def fundamentals_pit(self, ticker: str, as_of_at: datetime, limit: int = 12) -> list[dict]:
        """공시일 cutoff까지 공개된 canonical financials 행을 반환한다."""
        return fundamentals_expectations.security_fundamentals_filed_before(
            ticker, as_of_at, limit=limit
        )
    def estimates(self, ticker: str, as_of_at: datetime, limit: int = 12) -> dict[str, list[dict]]:
        """관측 컨센서스만 담아 돌려준다 — 모양은 evidence 계약이 정한다."""
        consensus = fundamentals_expectations.observed_consensus_as_of(
            ticker, as_of_at, limit=limit
        )
        return {"consensus": consensus}
    def macro_snapshot(self, as_of_at: datetime) -> dict[str, Any]:
        """macro 스키마의 owner에게 위임한다."""
        return MacroRepository(Database(sb)).observation_snapshot_as_of(as_of_at)
    def segment_snapshot(self, ticker: str, as_of_at: datetime) -> dict[str, Any]:
        """fundamentals 스키마의 owner에게 위임한다."""
        return fundamentals_segments.segment_snapshot_as_of(ticker, as_of_at)
    def segment_capability(self) -> dict[str, Any]:
        """코드에 구현된 도메인 저장소 기능을 반환한다.

        실행 성공 여부는 Discord/GitHub에서 관제하고, 투자 컨텍스트는 실제
        ``fundamentals.filing_processing``와 ``segment_metrics`` 행의 유무로 판단한다.
        """
        return {
            "availability": "available",
            "source": "fundamentals.filing_processing+segment_metrics",
        }

    def guru_snapshot(self, ticker: str, as_of_at: datetime) -> dict[str, Any]:
        symbol = normalize_ticker(ticker)
        current, previous, holdings = self._effective_guru_state(as_of_at)
        signals = _guru_candidate_signals(current, previous, holdings)
        relevant_accessions = {
            str(event["effective_accession_no"])
            for event in [*current.values(), *previous.values()]
        }
        positions = [
            row for row in holdings
            if str(row.get("effective_accession_no") or "") in relevant_accessions
            and normalize_ticker(row.get("ticker")) == symbol
        ]
        filings = [
            {
                "accession_no": event["effective_accession_no"],
                "manager_cik": event["manager_cik"],
                "period_end": event["period_end"],
                "filing_date": event["effective_filing_date"],
                "accepted_at": event["effective_accepted_at"],
                "form_type": event["effective_form_type"],
                "report_type": event["effective_report_type"],
                "amendment_type": event["effective_amendment_type"],
                "amendment_no": event["effective_amendment_no"],
                "source_url": event["effective_source_url"],
            }
            for event in current.values()
        ]
        return {
            "filings": sorted(filings, key=lambda row: str(row["accepted_at"]), reverse=True),
            "positions": positions,
            "features": signals.get(symbol, {}),
        }

    def econ_snapshot(
        self,
        as_of_at: datetime,
        lookback_days: int = 14,
        max_rows_per_kind: int = ECON_MAX_ROWS_PER_KIND,
    ) -> dict[str, Any]:
        """관련 발표를 먼저 선택하고, 같은 cutoff 이전의 마지막 상태를 읽는다.

        이 결과는 LLM 프롬프트에 통째로 들어간다. 같은 값을 평면 키와 중첩 그룹에
        두 번 담거나 창 안의 모든 행을 그대로 넘기면 프롬프트가 provider 한도를
        넘어 판단 자체가 시작되지 않는다 — 실측(2026-09-03)으로 번들의 69%가
        여기였다. 그래서 중복을 걷어내고 cutoff에 가까운 행만 남긴다.
        """
        if int(max_rows_per_kind) < 1:
            raise ValueError("max_rows_per_kind must be positive")
        # 조회는 macro owner가, 프롬프트에 무엇을 남길지는 여기가 정한다.
        rows = econ_calendar_db.select_snapshot_rows(
            as_of_at=as_of_at, lookback_days=lookback_days, lookahead_days=30
        )
        point = parse_datetime(_iso(as_of_at))
        result: dict[str, list[dict[str, Any]]] = {"events": [], "results": [], "forecasts": []}
        for row in rows:
            release = {key: row.get(key) for key in _ECON_RELEASE_KEYS}
            actual = row.get("latest_actual_value")
            forecast = next(
                (row.get(key) for key in _ECON_FORECAST_KEYS if row.get(key) is not None), None
            )
            base = {
                "release": release,
                "series_name_ko": row.get("series_name_ko"),
                "unit": row.get("unit"),
                # owner가 cutoff 이전 버전만 조립한다. 발표 예정시각은 자료를
                # 알게 된 시각이 아니므로 이 스냅샷의 cutoff를 보수적 상한으로 쓴다.
                "collected_at": point.isoformat(),
            }
            # 발표 하나가 여러 목록에 들어간다 — 예정된 사건이면서 값이 나온 것이고
            # 예상도 있었던 것이다. 어느 목록에 넣을지는 그 행이 실제로 무엇을
            # 들고 있는지가 정한다.
            result["events"].append({**base, "scheduled_at": row.get("scheduled_at"),
                                     "status": row.get("status")})
            if actual is not None:
                result["results"].append({**base, "actual": actual,
                                          "first_actual_value": row.get("first_actual_value"),
                                          "revision": row.get("revision")})
            if forecast is not None:
                result["forecasts"].append({**base, "forecast": forecast,
                                            "market_surprise": row.get("market_surprise"),
                                            "model_error": row.get("model_error")})
        for kind, entries in result.items():
            result[kind] = _nearest_rows(entries, point=point, limit=int(max_rows_per_kind))
        return result


    def save_policy(self, row: dict) -> None:
        self._trading_repository().record_policy(row)

    def case_exists(self, case_key: str) -> bool:
        return self._trading_repository().decision_exists(case_key)

    def save_case(self, row: dict) -> None:
        payload = dict(row)
        ticker = payload.pop("ticker", None)
        evidence_bundle = payload.pop("evidence_bundle", None)
        payload.pop("role_analyses", None)
        evidence_meta = dict(evidence_bundle or {})
        final_decision = payload.get("final_decision")
        if isinstance(final_decision, dict):
            final_decision = dict(final_decision)
            if isinstance(evidence_meta.get("_digest"), dict):
                final_decision["evidence_digest"] = evidence_meta["_digest"]
            if evidence_meta.get("_artifact_error"):
                final_decision["evidence_artifact_error"] = str(
                    evidence_meta["_artifact_error"]
                )[:500]
            payload["final_decision"] = final_decision
        payload["security_id"] = _security_id(str(ticker))
        repository = self._trading_repository()
        repository.record_decision(payload)
        artifact = dict(evidence_meta.get("_artifact") or {})
        if artifact:
            repository.record_evidence([{
                "case_key": payload["case_key"],
                "evidence_kind": "bundle",
                "artifact_uri": artifact.get("uri") or artifact.get("artifact_uri"),
                "sha256": artifact["sha256"],
                "byte_size": int(artifact["byte_size"]),
                "schema_version": str(artifact["schema_version"]),
            }])

    def save_decision_run(self, row: dict) -> None:
        self._trading_repository().record_run(row)

    def finish_decision_run(
        self,
        run_id: str,
        *,
        status: str,
        failure_reason: str | None = None,
    ) -> None:
        self._trading_repository().finish_run(
            run_id,
            status=status,
            failure_reason=failure_reason,
        )

    def save_portfolio_snapshot(self, snapshot: AccountSnapshot) -> str:
        """execution owner의 불변 계좌 원장에 snapshot을 기록한다.

        ``trading``은 계좌 상태를 소유하지 않지만, 판단이 사용한 snapshot을
        가리킬 수 있어야 한다. 따라서 이 writer는 execution repository의
        공개 계약만 호출하고, trading 테이블에는 snapshot 자체를 복제하지 않는다.
        실제 계좌번호는 execution 원장에도 평문으로 남기지 않고 hash만 기록한다.
        """
        from investment_agent.execution.db import ExecutionRepository

        execution = ExecutionRepository()
        account_ref = hashlib.sha256(
            f"{snapshot.broker}|{snapshot.account_id}".encode("utf-8")
        ).hexdigest()
        snapshot_id = execution.save_account_snapshot({
            "execution_mode": "live",
            "broker_account_hash": account_ref,
            "equity": snapshot.total_value,
            "cash": snapshot.cash_value,
            "buying_power": snapshot.cash_value,
            "captured_at": snapshot.captured_at,
            "raw_snapshot": {
                "source": "portfolio_construction",
                "broker": snapshot.broker,
                "base_currency": snapshot.base_currency,
                "open_order_count": len(snapshot.open_order_ids),
            },
        })
        if snapshot.positions:
            security_ids = _security_ids([position.ticker for position in snapshot.positions])
            execution.save_position_snapshots([
                {
                    "account_snapshot_id": snapshot_id,
                    "ticker": normalize_ticker(position.ticker),
                    "security_id": security_ids[normalize_ticker(position.ticker)],
                    "quantity": position.quantity,
                    "market_price": position.market_price,
                    "market_value": position.market_value,
                    "weight": position.market_value / snapshot.total_value,
                }
                for position in snapshot.positions
            ])
        return str(snapshot_id)

    def save_signal_batch(
        self,
        *,
        run_id: str,
        batch: SignalBatch,
        records: tuple[SignalRecord, ...],
    ) -> None:
        """배치 행을 먼저 저장한 뒤 종목 의견을 immutable ID로 저장한다."""
        if any(record.batch_id != batch.batch_id for record in records):
            raise ValueError("signal records do not belong to the supplied batch")
        batch_row = {
            "batch_id": batch.batch_id,
            "run_id": run_id,
            "as_of_at": batch.as_of_at,
            "completed_at": batch.completed_at,
            "requested_symbols": list(batch.requested_symbols),
            "successful_symbols": list(batch.successful_symbols),
            "failed_symbols": list(batch.failed_symbols),
            "is_complete": batch.is_complete,
            "model_artifact_id": batch.model_artifact_id,
        }
        security_ids = _security_ids([record.proposal.ticker for record in records]) if records else {}
        signal_rows = [{
            "signal_id": record.signal_id,
            "batch_id": record.batch_id,
            "case_key": record.case_key,
            "security_id": security_ids[normalize_ticker(record.proposal.ticker)],
            "proposal": record.proposal.to_dict(),
            "recorded_at": record.recorded_at,
            "expires_at": record.expires_at,
        } for record in records]
        self._trading_repository().record_signal_batch(batch=batch_row, signals=signal_rows)

    def latest_signal_batch_id(self, *, as_of_at: datetime) -> str | None:
        return self._trading_repository().latest_signal_batch_id(as_of_at=as_of_at)

    def latest_execution_ready_batch_id(self, *, as_of_at: datetime) -> str | None:
        """is_complete=True이고 만료되지 않은 종목 의견이 존재하는 최신 배치만 반환한다."""
        return self._trading_repository().latest_execution_ready_batch_id(as_of_at=as_of_at)

    def has_live_execution_for_batch(self, batch_id: str) -> bool:
        """이미 해당 signal batch로 live 포트폴리오 제안/승인이 생성되었는지 확인한다."""
        return self._trading_repository().has_live_execution_for_batch(batch_id)

    def signal_batch_id_for_as_of(self, as_of_at: str | datetime) -> str:
        """Shadow 입력 시각과 정확히 같은 단일 batch만 반환해 완료시각 경합을 없앤다."""
        point = parse_datetime(as_of_at)
        return self._trading_repository().signal_batch_id_for_as_of(point)

    def load_signal_book(
        self,
        *,
        as_of_at: datetime,
        lookback_days: int = 60,
    ) -> SignalBook:
        """결정 시점 이전 배치와 그 시점에 유효한 종목 의견만 복원한다."""
        batches_rows = self._trading_repository().signal_batches(
            as_of_at=as_of_at,
            lookback_days=lookback_days,
        )
        batches = tuple(
            SignalBatch(
                batch_id=str(row["batch_id"]),
                as_of_at=str(row["as_of_at"]),
                completed_at=str(row["completed_at"]),
                requested_symbols=tuple(row.get("requested_symbols") or ()),
                successful_symbols=tuple(row.get("successful_symbols") or ()),
                failed_symbols=tuple(row.get("failed_symbols") or ()),
                model_artifact_id=(
                    str(row["model_artifact_id"])
                    if row.get("model_artifact_id") else None
                ),
            )
            for row in batches_rows
        )
        if not batches:
            return SignalBook()
        batch_ids = [batch.batch_id for batch in batches]
        record_rows = self._trading_repository().signal_records(
            batch_ids=batch_ids,
            as_of_at=as_of_at,
        )
        tickers_by_id = select_tickers_by_security_id(
            [int(row["security_id"]) for row in record_rows]
        )
        records: list[SignalRecord] = []
        for row in record_rows:
            value = dict(row["proposal"])
            value["ticker"] = tickers_by_id[int(row["security_id"])]
            proposal = SecurityProposal(
                ticker=str(value["ticker"]),
                as_of_at=str(value["as_of_at"]),
                signal=str(value["signal"]),
                probability_up=float(value["probability_up"]),
                confidence=float(value["confidence"]),
                expected_excess_return=float(value["expected_excess_return"]),
                target_weight=float(value["target_weight"]),
                reasoning=tuple(value["reasoning"]),
                evidence_ids=tuple(value["evidence_ids"]),
                missing_data=tuple(value.get("missing_data") or ()),
            )
            record = SignalRecord(
                batch_id=str(row["batch_id"]),
                proposal=proposal,
                recorded_at=str(row["recorded_at"]),
                expires_at=str(row["expires_at"]),
                case_key=str(row["case_key"]) if row.get("case_key") else None,
            )
            if record.signal_id != str(row["signal_id"]):
                raise RuntimeError("stored signal record hash does not match its payload")
            records.append(record)
        return SignalBook(batches=batches, records=tuple(records))

    def save_portfolio_proposal(self, row: dict) -> None:
        self._trading_repository().record_proposal(dict(row))

    def save_risk_decision(self, row: dict) -> None:
        self._trading_repository().record_risk_decision(dict(row))

    def save_portfolio_decision(self, row: dict) -> None:
        self._trading_repository().adopt_portfolio(row)

    def save_model_artifact(self, row: dict) -> None:
        self._trading_repository().record_model_version(row)

    def save_events(self, events: Sequence[Event]) -> None:
        """Research event는 production DB가 아닌 local artifact store에 저장한다."""
        if not events:
            return
        rows: list[dict[str, Any]] = []
        for event in events:
            payload = event.to_dict()
            rows.append({
                **payload,
                "record_key": hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest(),
            })
        ResearchStore().upsert_records("events", rows, key="record_key")

    def save_event_features(self, snapshots: Sequence[EventFeatureSnapshot]) -> None:
        """Research event feature는 local artifact store에 저장한다."""
        if not snapshots:
            return
        rows: list[dict[str, Any]] = []
        for snapshot in snapshots:
            payload = snapshot.to_dict()
            rows.append({
                "record_key": f"event_features_{snapshot.input_hash[:24]}",
                **payload,
            })
        ResearchStore().upsert_records("event_feature_snapshots", rows, key="record_key")

    def save_training_samples(self, samples: Sequence[TrainingSample]) -> None:
        if not samples:
            return
        rows = [sample.to_dict() for sample in samples]
        for row in rows:
            row["record_key"] = row["sample_id"]
        ResearchStore().upsert_records("training_samples", rows, key="record_key")

    def save_rl_feature_snapshots(self, rows: list[dict]) -> None:
        if not rows:
            return
        snapshots = [_feature_snapshot(dict(row)) for row in rows]
        identities = [
            (item.feature_version, item.as_of_at, item.ticker) for item in snapshots
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("RL feature batch contains duplicate snapshot identities")
        stored = [item.to_storage_row() for item in snapshots]
        for row in stored:
            row["record_key"] = f"{row['feature_version']}:{row['as_of_at']}:{row['ticker']}"
        ResearchStore().upsert_records("rl_feature_snapshots", stored, key="record_key")

    def save_rl_training_labels(self, rows: list[dict]) -> None:
        if not rows:
            return
        labels = [_training_label(dict(row)) for row in rows]
        identities = [(item.feature_version, item.as_of_at, item.ticker) for item in labels]
        if len(identities) != len(set(identities)):
            raise ValueError("RL label batch contains duplicate label identities")
        stored = [item.to_storage_row() for item in labels]
        for row in stored:
            row["record_key"] = f"{row['feature_version']}:{row['as_of_at']}:{row['ticker']}"
        ResearchStore().upsert_records("rl_training_labels", stored, key="record_key")

    def share_class_snapshots_pit(
        self,
        ticker: str,
        as_of_at: datetime,
        limit: int = 24,
    ) -> list[dict[str, Any]]:
        """공시 수리 시각이 cutoff 이전인 발행주식수 snapshot만 반환한다."""
        return fundamentals_shares.share_class_snapshots_filed_before(
            ticker, as_of_at, limit=limit
        )
    def save_valuation_observations(self, rows: list[dict]) -> None:
        """같은 (ticker, as_of, source_kind)는 재실행해도 한 행으로 수렴한다."""
        if not rows:
            return
        identities = [
            (str(row["ticker"]), str(row["as_of_at"]), str(row["source_kind"]))
            for row in rows
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("valuation batch contains duplicate observation identities")
        stored = [dict(row) for row in rows]
        for row in stored:
            row["record_key"] = f"{row['ticker']}:{row['as_of_at']}:{row['source_kind']}"
        ResearchStore().upsert_records("valuation_observations", stored, key="record_key")

    def valuation_observation_rows(
        self,
        symbols: tuple[str, ...],
        *,
        start_as_of: str,
        end_as_of: str,
        source_kind: str = "live_shadow",
    ) -> list[dict[str, Any]]:
        """서류철·feature가 읽는 point-in-time 밸류에이션 관측값이다."""
        normalized = normalize_symbols(symbols)
        start = parse_datetime(start_as_of)
        end = parse_datetime(end_as_of)
        if end < start:
            raise ValueError("valuation end_as_of must not precede start_as_of")
        rows = ResearchStore(read_only=True).records(
            "valuation_observations",
            start_as_of=start.isoformat(),
            end_as_of=end.isoformat(),
        )
        return [
            row for row in rows
            if str(row.get("source_kind")) == source_kind
            and normalize_ticker(str(row.get("ticker"))) in normalized
        ]

    def forward_prices_for_labels(
        self,
        ticker: str,
        *,
        after_date: str,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        """label 전용 미래 종가다 — evidence/feature 경로에서 절대 부르지 않는다."""
        return market_db.forward_closes_after(ticker, after_date=after_date, limit=limit)
    def rl_feature_snapshot_rows(
        self,
        symbols: tuple[str, ...],
        *,
        start_as_of: str,
        end_as_of: str,
        feature_version: str,
    ) -> list[dict[str, Any]]:
        """미래 라벨 컬럼을 전혀 조회하지 않는 point-in-time feature 경계다."""
        normalized = normalize_symbols(symbols)
        start = parse_datetime(start_as_of)
        end = parse_datetime(end_as_of)
        if end < start:
            raise ValueError("RL feature end_as_of must not precede start_as_of")
        if not str(feature_version).strip():
            raise ValueError("feature_version is required")
        rows = ResearchStore(read_only=True).records(
            "rl_feature_snapshots",
            start_as_of=start.isoformat(),
            end_as_of=end.isoformat(),
        )
        rows = [
            row for row in rows
            if row.get("feature_version") == feature_version
            and normalize_ticker(str(row.get("ticker"))) in normalized
            and parse_datetime(str(row["available_at"])) <= end
        ]
        return [_feature_snapshot(dict(row)).to_storage_row() for row in rows]

    def rl_training_label_rows(
        self,
        symbols: tuple[str, ...],
        *,
        start_as_of: str,
        end_as_of: str,
        feature_version: str,
        label_cutoff_at: str,
    ) -> list[dict[str, Any]]:
        """학습 cutoff 전에 실제 생성된 미래 label만 별도로 반환한다."""
        normalized = normalize_symbols(symbols)
        start = parse_datetime(start_as_of)
        end = parse_datetime(end_as_of)
        cutoff = parse_datetime(label_cutoff_at)
        if end < start:
            raise ValueError("RL label end_as_of must not precede start_as_of")
        if cutoff < end:
            raise ValueError("label_cutoff_at must not precede the feature window end")
        if not str(feature_version).strip():
            raise ValueError("feature_version is required")
        rows = ResearchStore(read_only=True).records(
            "rl_training_labels",
            start_as_of=start.isoformat(),
            end_as_of=end.isoformat(),
        )
        rows = [
            row for row in rows
            if row.get("feature_version") == feature_version
            and normalize_ticker(str(row.get("ticker"))) in normalized
            and parse_datetime(str(row["label_available_at"])) <= cutoff
        ]
        return [_training_label(dict(row)).to_storage_row() for row in rows]

    def rl_historical_membership_rows(
        self,
        *,
        start_as_of: str,
        end_as_of: str,
    ) -> list[dict[str, Any]]:
        """현재 tracked를 과거에 대입하지 않는 MembershipTimeline 입력 행이다."""
        start = parse_datetime(start_as_of)
        end = parse_datetime(end_as_of)
        if end < start:
            raise ValueError("membership end_as_of must not precede start_as_of")
        snapshots = self.historical_sp500_membership(
            start_date=start.date(),
            end_date=end.date(),
        )
        return [
            {
                "effective_at": f"{row['effective_date']}T00:00:00+00:00",
                "symbols": list(row["symbols"]),
                "source_id": str(row.get("source_hash") or row.get("source") or ""),
                "source_kind": "historical_point_in_time",
            }
            for row in snapshots
        ]

    def save_promotion(self, row: dict) -> None:
        self._trading_repository().record_model_promotion(row)

    def model_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        return self._trading_repository().model_version(artifact_id)

    def model_stage(self, artifact_id: str) -> str | None:
        return self._trading_repository().current_model_stage(artifact_id)

    def model_evaluation_rows(self, artifact_id: str) -> list[dict[str, Any]]:
        """artifact에 연결된 local Research 평가를 안전 증명 컬럼까지 포함해 조회한다."""
        artifact_id = str(artifact_id).strip()
        if not artifact_id:
            raise ValueError("artifact_id is required")
        return [
            {**row, "artifact_id": artifact_id}
            for row in ResearchStore(read_only=True).records("portfolio_evaluations")
            if str(row.get("model_artifact_id") or "") == artifact_id
        ]

    def model_evaluation_summary(self, artifact_id: str) -> EvaluationSummary:
        """평가 원장 전체를 보수적인 승격 요약으로 집계한다."""
        if self.model_artifact(artifact_id) is None:
            raise LookupError(f"model artifact not found: {artifact_id}")
        return aggregate_evaluations(self.model_evaluation_rows(artifact_id))

    def approve_model_promotion(
        self,
        decision: PromotionDecision,
        *,
        confirmation: str,
    ) -> dict[str, Any]:
        """평가 재검증 뒤 현재 단계를 잠그고 승인 audit만 기록한다."""
        if decision.status != "approved" or decision.violations:
            raise ValueError("only a manually is_approved clean decision can be persisted")
        if self.model_artifact(decision.artifact_id) is None:
            raise RuntimeError("model promotion failed closed: artifact not found")
        if self.model_stage(decision.artifact_id) != decision.from_stage:
            raise RuntimeError("model promotion failed closed: artifact stage changed")
        expected = f"PROMOTE {decision.artifact_id} {decision.from_stage}->{decision.to_stage}"
        if confirmation != expected:
            raise ValueError(f"confirmation must exactly match: {expected}")
        return self._trading_repository().approve_model_promotion(
            audit_row={
                "artifact_id": decision.artifact_id,
                "from_stage": decision.from_stage,
                "to_stage": decision.to_stage,
                "status": "approved",
                "evidence": decision.to_record()["evidence"],
                "approved_by": decision.approved_by,
                "approved_at": decision.approved_at,
                "confirmation_text": confirmation,
            },
            artifact_id=decision.artifact_id,
            from_stage=decision.from_stage,
            to_stage=decision.to_stage,
        )

    def risk_decision(self, risk_decision_id: str) -> dict | None:
        from investment_agent.execution.db import ExecutionRepository

        return ExecutionRepository().risk_decision(risk_decision_id)

    def portfolio_proposal(self, proposal_id: str) -> dict | None:
        from investment_agent.execution.db import ExecutionRepository
        return ExecutionRepository().portfolio_proposal(proposal_id)

    def has_approved_promotion(self, artifact_id: str, to_stage: str) -> bool:
        if to_stage not in {"paper", "live"}:
            return False
        stage = self.model_stage(artifact_id)
        if stage is None:
            return False
        if {"shadow": 0, "backtest": 1, "out_of_sample": 2, "walk_forward": 3, "paper": 4, "live": 5}.get(stage, -1) < {
            "paper": 4,
            "live": 5,
        }[to_stage]:
            return False
        rows = [
            row for row in self._trading_repository().model_promotions(artifact_id)
            if row.get("status") == "approved"
        ]
        approved_transitions = {
            (str(row.get("from_stage")), str(row.get("to_stage")))
            for row in rows
            if row.get("confirmation_text")
            == (
                f"PROMOTE {artifact_id} {row.get('from_stage')}"
                f"->{row.get('to_stage')}"
            )
        }
        required = {
            ("shadow", "backtest"),
            ("backtest", "out_of_sample"),
            ("out_of_sample", "walk_forward"),
            ("walk_forward", "paper"),
        }
        if to_stage == "live":
            required.add(("paper", "live"))
        return required.issubset(approved_transitions)

    def cases_for_evaluation(self, limit: int = 200) -> list[dict]:
        rows = self._trading_repository().evaluation_candidates(limit=limit)
        tickers = select_tickers_by_security_id([int(row["security_id"]) for row in rows])
        return [
            {**row, "ticker": tickers[int(row["security_id"])]}
            for row in rows if int(row["security_id"]) in tickers
        ]

    def existing_evaluation_horizons(self, case_key: str) -> set[int]:
        return self._trading_repository().evaluation_horizons(case_key)

    def price_path(self, ticker: str, start_date: date, limit: int = 80) -> list[dict]:
        """사후 평가용 경로. PIT 조회가 아니다."""
        return market_db.price_path_from(ticker, start_date, limit=limit)
    def save_evaluation(self, row: dict) -> None:
        self._trading_repository().record_evaluation(row)

    def evaluated_memories(
        self,
        ticker: str,
        limit: int = 5,
        as_of_at: datetime | None = None,
    ) -> list[dict]:
        cases = self._trading_repository().evaluated_memory_rows(
            security_id=_security_id(ticker),
            limit=limit,
            as_of_at=as_of_at,
        )
        return [
            {
                **row,
                "ticker": normalize_ticker(ticker),
                "evaluations": row["evaluations"],
            }
            for row in cases
        ][:limit]


# ── 운영 scorecard용 최신 1행 읽기 ─────────────────────────────────────────
# ops가 이 스키마를 직접 조회하면 테이블·컬럼 이름이 저장소 경계 밖으로 새어 나가고,
# 오타가 import 에러가 아니라 런타임 PGRST 404로만 드러난다. 계약은 여기서 소유한다.


def latest_decision_run() -> dict | None:
    return SupabaseRepository._trading_repository().latest_run()


def latest_model_artifact() -> dict | None:
    return SupabaseRepository._trading_repository().latest_model_version()


def latest_backtest_evaluation() -> dict | None:
    rows = [
        row for row in ResearchStore(read_only=True).records("portfolio_evaluations")
        if str(row.get("evaluation_kind") or "") == "backtest"
    ]
    rows.sort(key=lambda row: str(row.get("evaluated_at") or ""), reverse=True)
    return rows[0] if rows else None


def latest_risk_decision() -> dict | None:
    return SupabaseRepository._trading_repository().latest_risk_decision()
