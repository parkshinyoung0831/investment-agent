"""분석할 종목을 고르는 후보 선정. Trading 판단 로직이다.

새 정보가 생긴 종목과 factor 상위 보유 후보를 고르고, System Portfolio 목표가 쓰는 factor 횡단면·논지
조회를 함께 둔다. 데이터 읽기(`PitReader`)와 Trading 판단 원장 위에서 동작한다.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
import investment_agent.research.adapters.trading as research_adapter
from investment_agent.trading.decision.candidate_ranker import (
    FACTOR_SNAPSHOT_MAX_AGE_DAYS,
    select_factor_candidates,
    PriorityCandidate,
    assemble_candidate_features,
    merge_priority_lane,
    priority_candidates,
    rank_candidate_features,
    validate_live_candidate_as_of,
)
from investment_agent.trading.contracts import ContractError, parse_datetime
from investment_agent.trading.repository import LedgerAccess
from investment_agent.research.adapters.trading import (FEATURE_VERSION, guru_candidate_signals, latest_cross_section, score_cross_section, technical_features_since)
from investment_agent.trading.decision.universe import normalize_ticker
from investment_agent.trading.decision.event_impact import PROXY_BY_THEME, global_event_priorities
from investment_agent.trading.portfolio.market_risk import estimate_betas
from investment_agent.platform.logging import get_logger
from investment_agent.data.fundamentals.infrastructure.supabase import expectations as fundamentals_expectations, segment_metrics as fundamentals_segments
from investment_agent.data.market import persistence as market_db
from investment_agent.data.universe.persistence import select_tickers_by_security_id

log = get_logger(__name__)


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


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


class CandidateSelection(LedgerAccess):
    """PIT reader와 Trading 원장 위에서 후보를 고르는 판단 로직. `SupabaseRepository`가 합성한다."""

    def _decision_attempts(self) -> list[dict[str, Any]]:
        """Trading 판단 원장의 시도 행에 Data owner의 ticker를 붙인다.

        원장은 security_id를 저장한다. 신원을 못 찾는 행을 조용히 버리면 coverage가 어긋나
        후보 선정이 엉뚱한 종목을 고르므로 실패로 드러낸다.
        """
        rows = self._trading_repository().security_decision_attempts()
        security_ids = sorted({int(row["security_id"]) for row in rows})
        if not security_ids:
            return []
        tickers = select_tickers_by_security_id(security_ids)
        if set(security_ids) - set(tickers):
            raise RuntimeError("local decisions reference unknown securities")
        return [{**row, "ticker": tickers[int(row["security_id"])]} for row in rows]

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
        members = {normalize_ticker(ticker) for ticker in tickers}
        latest: dict[str, datetime] = {}
        for row in self._decision_attempts():
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
        for row in technical_features_since(since):
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
        all_signals = guru_candidate_signals(current, previous, holdings)
        wanted = {normalize_ticker(ticker) for ticker in tickers}
        return {ticker: signal for ticker, signal in all_signals.items() if ticker in wanted}

    def candidate_tickers(
        self,
        limit: int = 50,
        *,
        as_of_at: datetime,
    ) -> list[str]:
        """분석할 종목: 새 정보가 생긴 종목 먼저, 그다음 factor 상위 보유 후보.

        factor 횡단면이 없으면(feature 적재 전·중단) 예전 다중 도메인 순환 랭커로 고른다. 분석 대상 선정은
        주문이 아니므로 fail-open이고, 어느 경로로 골랐는지 로그에 남긴다.
        """
        as_of_at = validate_live_candidate_as_of(as_of_at)
        tickers = self.current_tracked_tickers()
        if not tickers:
            return []
        last_analyzed = self._last_attempted(tickers, as_of_at=as_of_at)
        fundamental_rows = self._candidate_fundamental_rows(tickers, as_of_at)
        latest_filed: dict[str, str] = {}
        for row in fundamental_rows:
            ticker = normalize_ticker(row.get("ticker"))
            filed = str(row.get("filed_at") or "")
            if ticker and filed > latest_filed.get(ticker, ""):
                latest_filed[ticker] = filed
        held = self._candidate_held_tickers()
        priority = priority_candidates(
            tickers=tickers,
            held_tickers=held,
            last_analyzed_at=last_analyzed,
            latest_filed_at=latest_filed,
            event_features=self._candidate_event_features(as_of_at),
            as_of_at=as_of_at,
        )
        factor_scores = self._candidate_factor_scores(tickers, as_of_at)
        if factor_scores is not None:
            snapshot_as_of, scores = factor_scores
            factor_ranked = select_factor_candidates(
                {ticker: score for ticker, score in scores.items() if ticker in set(tickers)},
                held_tickers=held, last_analyzed_at=last_analyzed, as_of_at=as_of_at,
            )
            selected = merge_priority_lane(priority, [row.ticker for row in factor_ranked], limit=limit)
            log.info(
                "ai investor candidate ranking path=factor as_of=%s snapshot=%s universe=%d selected=%s "
                "priority=%s factor=%s",
                as_of_at.isoformat(), snapshot_as_of, len(tickers), selected,
                {item.ticker: item.reason for item in priority},
                {row.ticker: [row.reason, None if row.composite is None else round(row.composite, 4)]
                 for row in factor_ranked if row.ticker in selected},
            )
            return selected
        features = assemble_candidate_features(
            tickers,
            last_analyzed_at=last_analyzed,
            market_rows=self._candidate_market_rows(tickers, as_of_at),
            technical_rows=self._candidate_technical_rows(tickers, as_of_at),
            fundamental_rows=fundamental_rows,
            segment_signals=self._candidate_segment_signals(tickers, as_of_at),
            guru_signals=self._candidate_guru_signals(tickers, as_of_at),
        )
        ranking = rank_candidate_features(features, as_of_at=as_of_at, limit=limit + len(priority))
        selected = merge_priority_lane(priority, [row.ticker for row in ranking], limit=limit)
        log.warning(
            "ai investor candidate ranking path=legacy_rotation (factor cross-section unavailable) "
            "as_of=%s universe=%d selected=%s priority=%s scores=%s",
            as_of_at.isoformat(),
            len(tickers),
            selected,
            {item.ticker: item.reason for item in priority},
            {row.ticker: row.score for row in ranking},
        )
        return selected

    def _last_attempted(self, tickers: list[str], *, as_of_at: datetime) -> dict[str, datetime]:
        """마지막 분석 시각. 실패한 시도도 포함한다 — 한 종목의 장애가 순환·재분석을 막지 않게."""
        last_analyzed = self._candidate_last_analyzed(tickers, as_of_at=as_of_at)
        for row in self._decision_attempts():
            ticker=normalize_ticker(row.get('ticker'))
            if ticker in tickers and row.get('status')=='failed' and row.get('as_of_at'):
                attempted=parse_datetime(row['as_of_at'])
                if attempted <= as_of_at and (ticker not in last_analyzed or attempted > last_analyzed[ticker]):
                    last_analyzed[ticker]=attempted
        return last_analyzed

    def event_reanalysis_priorities(
        self,
        *,
        as_of_at: datetime,
        global_event_hours: int = 48,
    ) -> tuple[PriorityCandidate, ...]:
        """정기 순환을 기다리지 않고 지금 다시 볼 종목.

        보유 종목의 새 공시·고영향 사건(`priority_candidates`)과, 검증을 통과한 글로벌 사건에 민감한
        보유 종목(`global_event_priorities`)을 합친다. 공시 조회는 보유 종목으로 좁힌다 — 이 경로는
        몇 분마다 돌기 때문에 500종목 재무를 매번 읽을 이유가 없다.
        """
        as_of_at = validate_live_candidate_as_of(as_of_at)
        tickers = self.current_tracked_tickers()
        if not tickers:
            return ()
        held = [ticker for ticker in self._candidate_held_tickers() if ticker in set(tickers)]
        last_analyzed = self._last_attempted(tickers, as_of_at=as_of_at)
        latest_filed: dict[str, str] = {}
        for row in (self._candidate_fundamental_rows(held, as_of_at) if held else []):
            ticker = normalize_ticker(row.get("ticker"))
            filed = str(row.get("filed_at") or "")
            if ticker and filed > latest_filed.get(ticker, ""):
                latest_filed[ticker] = filed
        local = priority_candidates(
            tickers=tickers, held_tickers=held, last_analyzed_at=last_analyzed,
            latest_filed_at=latest_filed, event_features=self._candidate_event_features(as_of_at),
            as_of_at=as_of_at,
        )
        global_events = self._recent_global_events(as_of_at, hours=global_event_hours) if held else []
        themes = {theme for event in global_events for theme in (event.get("metadata") or {}).get("themes") or ()}
        proxies = sorted({PROXY_BY_THEME[name] for name in themes if name in PROXY_BY_THEME})
        sensitivities: dict[str, dict[str, float]] = {}
        proxy_rows: dict[str, list[dict]] = {}
        if proxies:
            rows = {symbol: self.market_prices(symbol, as_of_at, limit=260) for symbol in (*held, *proxies)}
            for proxy in proxies:
                proxy_rows[proxy] = rows[proxy]
                try:
                    sensitivities[proxy] = estimate_betas(rows, symbols=held, benchmark_symbol=proxy)
                except ContractError as exc:
                    log.warning("global event sensitivity unavailable proxy=%s: %s", proxy, exc)
        global_priority = global_event_priorities(
            global_events, held_tickers=held, last_analyzed_at=last_analyzed,
            sensitivities=sensitivities, proxy_rows=proxy_rows, as_of_at=as_of_at,
        )
        merged: dict[str, PriorityCandidate] = {}
        for candidate in (*local, *global_priority):
            current = merged.get(candidate.ticker)
            if current is None or (candidate.tier, -candidate.importance) < (current.tier, -current.importance):
                merged[candidate.ticker] = candidate
        return tuple(sorted(merged.values(), key=lambda item: (item.tier, -item.importance, item.ticker)))

    def _recent_global_events(self, as_of_at: datetime, *, hours: int) -> list[dict[str, Any]]:
        try:
            rows = research_adapter.open_research_store(read_only=True).records(
                "events",
                start_as_of=None,
                end_as_of=None,
            )
        except Exception as exc:  # noqa: BLE001 - 사건 저장소 부재가 재분석 판단을 멈추게 두지 않는다
            log.warning("global events unavailable: %s", type(exc).__name__)
            return []
        floor = as_of_at - timedelta(hours=hours)
        return [
            row for row in rows
            if not row.get("ticker") and row.get("available_at")
            and floor <= parse_datetime(str(row["available_at"])) <= as_of_at
        ]

    def _candidate_factor_scores(
        self, tickers: Sequence[str], as_of_at: datetime,
    ) -> tuple[str, dict[str, Any]] | None:
        return self.factor_cross_section(as_of_at, universe_size=len(tickers))

    def factor_cross_section(
        self, as_of_at: datetime, *, universe_size: int | None = None,
    ) -> tuple[str, dict[str, Any]] | None:
        """최근 온전한 live feature 횡단면의 factor 점수. 없거나 오래됐으면 None.

        후보 선정과 System 목표가 같은 횡단면을 읽는다 — 둘이 다른 날의 점수를 보면 분석한 종목과
        담는 종목이 어긋난다.
        """
        tickers_count = universe_size if universe_size is not None else len(self.current_tracked_tickers())
        try:
            rows = research_adapter.open_research_store(read_only=True).records(
                "rl_feature_snapshots",
                start_as_of=(as_of_at - timedelta(days=FACTOR_SNAPSHOT_MAX_AGE_DAYS)).isoformat(),
                end_as_of=as_of_at.isoformat(),
            )
        except Exception as exc:  # noqa: BLE001 - feature 저장소 부재가 정기 분석을 멈추게 두지 않는다
            log.warning("factor snapshots unavailable for candidate selection: %s", type(exc).__name__)
            return None
        # 과거 재현 행은 판단 시각이 과거라 이 창에 거의 없지만, 섞이지 않게 live 행만 쓴다.
        live_rows = [row for row in rows if (row.get("provenance") or {}).get("source_kind") != "historical_replay"]
        section = latest_cross_section(
            live_rows, feature_version=FEATURE_VERSION, min_coverage=max(1, tickers_count // 2),
        )
        if section is None:
            return None
        snapshot_as_of, features = section
        return snapshot_as_of, score_cross_section(features, groups=self.sp500_sector_map(list(features)))

    def _candidate_held_tickers(self) -> list[str]:
        """System Portfolio가 지금 보유한 종목. 실계좌 보유는 분석 대상 선정에 들어오지 않는다.

        보유가 없는 것(빈 목록)과 원장을 못 읽은 것은 다르다. 후자를 빈 목록으로 접으면 보유 종목의 재분석
        우선순위가 조용히 사라지므로 읽기 실패는 그대로 올린다.
        """
        from investment_agent.trading.system.store import SystemPortfolioStore
        return SystemPortfolioStore().held_tickers()

    def thesis_views(self, tickers: Sequence[str], *, as_of_at: datetime, valid_days: int) -> dict[str, Any]:
        """종목별 최신 TradingAgents 논지(채택된 ML 보정 반영). 판단 시점 이전에 기록된 것만 읽는다."""
        from investment_agent.trading.decision.alpha import ThesisView

        wanted = {normalize_ticker(ticker) for ticker in tickers}
        repository = self._trading_repository()
        rows = repository.signal_rows_recorded_between(start=as_of_at - timedelta(days=valid_days), end=as_of_at)
        if not rows:
            return {}
        artifacts = {
            str(row["batch_id"]): row.get("model_artifact_id")
            for row in repository.signal_batches(as_of_at=as_of_at, lookback_days=min(365, valid_days + 1))
        }
        tickers_by_id = select_tickers_by_security_id([int(row["security_id"]) for row in rows])
        views: dict[str, Any] = {}
        for row in rows:
            ticker = normalize_ticker(tickers_by_id.get(int(row["security_id"])))
            if ticker not in wanted:
                continue
            view = ThesisView.from_proposal({**dict(row["proposal"]), "ticker": ticker},
                                            model_artifact_id=artifacts.get(str(row["batch_id"])))
            if view is not None and view.as_of_at <= as_of_at and (ticker not in views or view.as_of_at >= views[ticker].as_of_at):
                views[ticker] = view
        return views

    def _candidate_event_features(self, as_of_at: datetime) -> list[dict[str, Any]]:
        """최근 7일 사건 요약. 로컬 research 저장소가 없으면 빈 목록이다."""
        try:
            return research_adapter.open_research_store(read_only=True).records(
                "event_feature_snapshots",
                start_as_of=(as_of_at - timedelta(days=7)).isoformat(),
                end_as_of=as_of_at.isoformat(),
            )
        except Exception as exc:  # noqa: BLE001 - 사건 저장소 부재가 정기 분석을 멈추게 두지 않는다
            log.warning("event features unavailable for candidate priority: %s", type(exc).__name__)
            return []

__all__ = ["CandidateSelection"]
