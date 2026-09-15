"""System Portfolio를 시간축으로 이어 운영한다: 평가 → 재조정 필요 판단 → 목표 생성·기록.

## 사람의 선택을 모른다

이 모듈과 저장소 인자는 실계좌 잔고·주문·Discord 승인을 읽는 메서드를 쓰지 않는다. 승인을 거절해도,
실계좌를 손으로 사고팔아도 System의 비중·NAV는 같다(테스트 강제).

## 언제 목표를 다시 만드나

- 목표가 한 번도 없었다.
- 새 factor 횡단면이 있고 마지막 목표에서 `rebalance_days`가 지났다.
- 보유 종목에 마지막 목표 뒤 논지 붕괴(THESIS_BROKEN)가 새로 기록됐다 — 주기를 기다리지 않는다.

아직 NAV에 반영되지 않은 목표가 있으면 새로 만들지 않는다. 재료가 없어 목표를 만들 수 없는 날은
이전 목표를 유지한다.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

from investment_agent.data.market.domain.calendar import bar_available_at
from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import canonical_json, parse_datetime, stable_id
from investment_agent.research.evaluation.costs import TransactionCostModel
from investment_agent.research.ml_serving import NO_FORECAST, ChampionForecast, champion_forecast
from investment_agent.trading.contracts import ContractError
from investment_agent.trading.decision.alpha import THESIS_BROKEN, AlphaPolicy, alpha_universe, is_valid_view
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL
from investment_agent.trading.portfolio.market_risk import estimate_trading_costs
from investment_agent.trading.risk.budget import BENCHMARK_SYMBOL
from investment_agent.trading.system.accounting import DailyMark, advance, first_session_after, session_price
from investment_agent.trading.system.store import SystemPortfolioStore, SystemTargetRecord
from investment_agent.trading.system.target import SystemPortfolioPolicy, build_system_target, system_model_artifact

log = get_logger(__name__)

_PRICE_ROWS = 130
# 이력이 모자라 비용을 추정할 수 없는 종목(상장폐지 직전 등)의 편도 비용. 추정 구간의 가장 비싼 값보다 크게 둔다 —
# 모른다고 비용을 0으로 두면 System 성과가 실계좌가 낼 수 없는 수익을 얻는다.
FALLBACK_COST_RATE = 0.005


@dataclass(frozen=True)
class SystemRunResult:
    marked_sessions: tuple[str, ...] = ()
    nav: float | None = None
    applied_target_id: str | None = None
    target_id: str | None = None
    is_target_approved: bool | None = None
    skipped_reason: str | None = None
    deferred: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "marked_sessions": list(self.marked_sessions), "deferred": dict(self.deferred)}


def _finalized(rows: list[dict], now: datetime) -> list[dict]:
    return sorted((row for row in rows if row.get("close") and bar_available_at(str(row["trade_date"])) <= now),
                  key=lambda row: str(row["trade_date"]))


def _cost_rates(rows_by_symbol: Mapping[str, list[dict]], symbols: set[str], *, before: str) -> dict[str, float]:
    """적용일 전날까지의 일봉으로 추정한 편도 비용(반스프레드 + 수수료)."""
    commission = TransactionCostModel().commission_rate
    rates: dict[str, float] = {}
    for symbol in sorted(symbols):
        history = [row for row in rows_by_symbol.get(symbol, []) if str(row["trade_date"]) < before]
        try:
            rates[symbol] = estimate_trading_costs({symbol: history}, symbols=(symbol,))[symbol].half_spread + commission
        except ContractError:
            rates[symbol] = FALLBACK_COST_RATE
    return rates


def mark_sessions(store: SystemPortfolioStore, repository: Any, *, now: datetime) -> tuple[list[DailyMark], dict[str, str]]:
    """마지막 평가일 뒤 확정된 거래일을 차례로 평가하고, 적용 시점이 된 목표를 반영한다."""
    calendar = _finalized(repository.market_prices(BENCHMARK_SYMBOL, now, limit=_PRICE_ROWS), now)
    previous = store.latest_mark()
    pending = store.pending_target()
    sessions = [str(row["trade_date"]) for row in calendar
                if previous is None or str(row["trade_date"]) > previous.trade_date]
    marks: list[DailyMark] = []
    deferred: dict[str, str] = {}
    rows_by_symbol: dict[str, list[dict]] = {BENCHMARK_SYMBOL: calendar}

    def rows(symbol: str) -> list[dict]:
        if symbol not in rows_by_symbol:
            rows_by_symbol[symbol] = _finalized(repository.market_prices(symbol, now, limit=_PRICE_ROWS), now)
        return rows_by_symbol[symbol]

    for trade_date in sessions:
        is_due = pending is not None and first_session_after(parse_datetime(pending.decided_at), [trade_date]) == trade_date
        target = pending if is_due else None
        if previous is None and target is None:
            continue
        after = previous.trade_date if previous else None
        symbols = set(previous.held_tickers if previous else ()) | {
            symbol for symbol, weight in (target.weights if target else {}).items() if symbol != CASH_SYMBOL and weight > 0
        }
        prices = {symbol: session_price(rows(symbol), after=after, on=trade_date) for symbol in sorted(symbols)}
        benchmark = session_price(rows(BENCHMARK_SYMBOL), after=after, on=trade_date)
        if target is not None:
            try:
                current = set(previous.weights) if previous else set()
                traded = {symbol for symbol in set(target.weights) | current if symbol != CASH_SYMBOL}
                rates = _cost_rates({symbol: rows(symbol) for symbol in traded}, traded, before=trade_date)
                mark = advance(previous, trade_date=trade_date, prices=prices, benchmark=benchmark,
                               target=target.weights, target_id=target.target_id, cost_rates=rates)
            except ContractError as exc:
                # 적용일에 목표 종목의 종가가 없으면 다음 거래일에 다시 적용한다.
                deferred[trade_date] = str(exc)
                log.warning("system target %s deferred on %s: %s", target.target_id, trade_date, exc)
                if previous is None:
                    continue
                mark = advance(previous, trade_date=trade_date, prices=prices, benchmark=benchmark)
            else:
                pending = None
        else:
            mark = advance(previous, trade_date=trade_date, prices=prices, benchmark=benchmark)
        store.record_mark(mark)
        marks.append(mark)
        previous = mark
    return marks, deferred


def _broken_thesis_since(views: Mapping[str, Any], *, held: tuple[str, ...], since: datetime, as_of_at: datetime,
                         policy: AlphaPolicy) -> list[str]:
    return sorted(
        symbol for symbol in held
        if is_valid_view(views.get(symbol), as_of_at=as_of_at, policy=policy)
        and views[symbol].thesis_state == THESIS_BROKEN and views[symbol].as_of_at > since
    )


def rebalance_skip_reason(latest: SystemTargetRecord | None, *, snapshot_as_of: str, now: datetime,
                          policy: SystemPortfolioPolicy, broken: list[str]) -> str | None:
    """목표를 다시 만들지 않을 사유. None이면 만든다."""
    if latest is None or broken:
        return None
    if latest.factor_snapshot_as_of == snapshot_as_of:
        return "factor_snapshot_already_decided"
    if now - parse_datetime(latest.decided_at) < timedelta(days=policy.rebalance_days):
        return "rebalance_not_due"
    return None


def run_system(
    store: SystemPortfolioStore,
    repository: Any,
    *,
    now: datetime,
    alpha_policy: AlphaPolicy | None = None,
    policy: SystemPortfolioPolicy | None = None,
    build_target: Callable[..., Any] = build_system_target,
    forecast: Callable[..., ChampionForecast] = champion_forecast,
) -> SystemRunResult:
    """평가 → (필요하면) 목표 생성. 실계좌·승인 원장에는 닿지 않는다.

    champion ML은 채택 파일(`active_ml_model.json`)만 읽는다. challenger 학습 결과는 이 경로에 들어오지 않는다.
    """
    alpha = alpha_policy or AlphaPolicy()
    selected = policy or SystemPortfolioPolicy()
    marks, deferred = mark_sessions(store, repository, now=now)
    latest_mark = store.latest_mark()
    base = {
        "marked_sessions": tuple(mark.trade_date for mark in marks),
        "nav": latest_mark.nav if latest_mark else None,
        "applied_target_id": next((mark.applied_target_id for mark in marks if mark.applied_target_id), None),
        "deferred": deferred,
    }
    if store.pending_target() is not None:
        return SystemRunResult(**base, skipped_reason="target_pending")
    section = repository.factor_cross_section(now)
    if section is None:
        return SystemRunResult(**base, skipped_reason="no_factor_cross_section")
    snapshot_as_of, scores = section
    current = dict(latest_mark.weights) if latest_mark else {CASH_SYMBOL: 1.0}
    held = latest_mark.held_tickers if latest_mark else ()
    universe = alpha_universe(scores, held_symbols=held, policy=alpha)
    views = repository.thesis_views(universe, as_of_at=now, valid_days=alpha.view_valid_days)
    latest = store.latest_target()
    broken = _broken_thesis_since(views, held=held, since=parse_datetime(latest.decided_at), as_of_at=now,
                                  policy=alpha) if latest else []
    skip = rebalance_skip_reason(latest, snapshot_as_of=snapshot_as_of, now=now, policy=selected, broken=broken)
    if skip is not None:
        return SystemRunResult(**base, skipped_reason=skip)
    ml = forecast(repository, universe, as_of_at=now) if alpha.use_ml else NO_FORECAST
    if not ml.is_available:
        log.info("champion ML not applied: %s", ml.reason)
    artifact = system_model_artifact(
        alpha_policy=alpha, policy=selected,
        view_artifact_ids=[view.model_artifact_id for view in views.values() if view and view.model_artifact_id],
        ml_artifact_id=ml.model_artifact_id if ml.is_available else None,
    )
    repository.save_model_artifact({
        "artifact_id": artifact["artifact_id"], "algorithm": "rule", "feature_version": selected.version,
        "train_start": None, "train_end": None, "seed": None,
        "artifact_uri": f"code://system_portfolio/{selected.version}",
        "sha256": hashlib.sha256(canonical_json(artifact["params"]).encode("utf-8")).hexdigest(),
        "params": artifact["params"], "code_commit": None,
    })
    run_id = stable_id("system_run", {"as_of_at": now.isoformat(), "snapshot": snapshot_as_of,
                                      "artifact_id": artifact["artifact_id"]})
    repository.save_decision_run({
        "run_id": run_id, "as_of_at": now.isoformat(), "stage": "shadow", "status": "running",
        "candidate_tickers": list(universe), "account_snapshot_id": None, "code_commit": None, "failure_reason": None,
    })
    try:
        target = build_target(
            repository, current_weights=current, as_of_at=now, scores=scores, snapshot_as_of=snapshot_as_of,
            run_id=run_id, model_artifact_id=artifact["artifact_id"], views=views, alpha_policy=alpha, policy=selected,
            ml_forecast=ml,
        )
    except ContractError as exc:
        repository.finish_decision_run(run_id, status="failed", failure_reason=f"inputs unavailable: {exc}"[:2000])
        log.warning("system target not built; previous target stays: %s", exc)
        return SystemRunResult(**base, skipped_reason="target_inputs_unavailable")
    risk = target.risk
    repository.save_policy({
        "policy_key": target.risk_policy.key, "policy_version": target.risk_policy.version, "stage": "shadow",
        "model_provider": "deterministic_python", "model_name": "DeterministicRiskGate", "prompt_version": "none",
        "config": target.risk_policy.to_config(),
    })
    repository.save_portfolio_proposal(target.proposal.to_dict())
    repository.save_risk_decision(risk.to_dict())
    repository.save_portfolio_decision({
        "decision_id": stable_id("decision", {"run_id": run_id, "proposal_id": target.proposal.proposal_id,
                                              "risk_decision_id": risk.risk_decision_id}),
        "run_id": run_id, "proposal_id": target.proposal.proposal_id, "risk_decision_id": risk.risk_decision_id,
        "champion_policy": {"source_type": target.proposal.source_type,
                            "source_version": target.proposal.source_version, "automatic_promotion": False},
        "status": "approved" if risk.is_approved else "rejected",
    })
    repository.finish_decision_run(run_id, status="completed")
    target_id = stable_id("system_target", {"proposal_id": target.proposal.proposal_id,
                                            "risk_decision_id": risk.risk_decision_id})
    store.record_target(
        target_id=target_id, decided_at=now, factor_snapshot_as_of=snapshot_as_of,
        proposal_id=target.proposal.proposal_id, risk_decision_id=risk.risk_decision_id,
        model_artifact_id=artifact["artifact_id"], is_approved=risk.is_approved,
        weights=dict(risk.approved_weights or {}),
        detail={"violations": list(risk.violations), "adjustments": list(risk.adjustments),
                "forced_exits": list(target.plan.forced_exits), "broken_thesis_trigger": broken,
                "rebalance_trigger": "broken_thesis" if broken else ("initial" if latest is None else "scheduled")},
    )
    log.info("system target recorded id=%s approved=%s snapshot=%s", target_id, risk.is_approved, snapshot_as_of)
    return SystemRunResult(**base, target_id=target_id, is_target_approved=risk.is_approved)


__all__ = ["FALLBACK_COST_RATE", "SystemRunResult", "mark_sessions", "rebalance_skip_reason", "run_system"]
