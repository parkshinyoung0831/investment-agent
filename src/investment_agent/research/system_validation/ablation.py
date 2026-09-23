"""System validation: 운영 Trading 엔진을 그대로 재생해 ablation을 비교한다.

```
같은 기간 · 같은 PIT 데이터 · 같은 비용 · 같은 유니버스
  ├ factor_only             factor 사전값만
  ├ factor_ml               + champion ML
  ├ factor_ml_thesis        + TradingAgents 논지(운영 구성)
  ├ no_tail_risk            운영 구성에서 CVaR 축소만 끔
  ├ no_market_risk          운영 구성에서 시장위험 예산만 끔
  ├ absolute_risk           위험을 절대 분산으로 잼(이전 운영 구성, 현금 편향)
  └ cvar_5 / cvar_12        CVaR 한도만 바꿈(운영 기본 8%)
→ 변형마다 System 엔진을 그대로 돌려 NAV·초과수익·낙폭·회전율을 기록
```

## 무엇을 지키나

- **운영 엔진을 그대로 쓴다.** 변형은 `AlphaPolicy`·`SystemPortfolioPolicy`의 스위치·정책값만 바꾼다. 재현용 엔진을
  따로 두면 비교 대상이 운영 판단이 아니게 된다.
- **판단 시각 이후를 보지 않는다.** factor 횡단면은 그 시각까지 공개된(`available_at`) 행만, 종목은 그 시각의
  S&P 500 멤버만, 가격은 저장소의 as-of 조회만 쓴다.
- **ML은 재현 기간보다 먼저 끝난 학습만 쓴다.** artifact의 검증 구간이 재현 시작 뒤까지 이어지면 그 변형을
  돌리지 않는다 — 미래를 보고 학습한 모델로 과거를 채점하면 ML이 좋아 보이는 것은 당연하다.
- **운영 원장에 쓰지 않는다.** 판단 기록 저장은 버리고, System 원장은 변형마다 임시 SQLite에 둔다.
- **TradingAgents 논지는 그 시각까지 기록된 것만 있다.** 과거에 분석하지 않은 날은 논지가 없으므로, 논지 변형의
  차이는 분석 기록이 쌓인 기간에서만 의미가 있다(결과에 논지 수를 함께 남긴다).
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from investment_agent.data.market.domain.calendar import bar_available_at
from investment_agent.platform.logging import get_logger
from investment_agent.platform.serialization import parse_datetime
from investment_agent.research.datasets.universe import research_universe
from investment_agent.research.ml_serving import NO_FORECAST, champion_forecast
from investment_agent.trading.decision.alpha import AlphaPolicy
from investment_agent.trading.risk.budget import BENCHMARK_SYMBOL
from investment_agent.trading.performance.stage_diagnosis import DIAGNOSIS_HORIZONS, PricePaths, diagnose
from investment_agent.trading.system.accounting import INITIAL_NAV, active_risk_summary, performance_summary
from investment_agent.trading.system.engine import run_system
from investment_agent.trading.system.store import SystemPortfolioStore
from investment_agent.trading.system.target import SystemPortfolioPolicy
from investment_agent.portfolio_weights import CASH_SYMBOL

log = get_logger(__name__)

ABLATION_VERSION = "system-ablation-v1"
# factor 횡단면을 찾을 창. 운영 후보 선정과 같은 기준이다.
_CROSS_SECTION_WINDOW_DAYS = 4
_LEDGER_WRITES = frozenset({
    "save_model_artifact", "save_decision_run", "finish_decision_run", "save_policy",
    "save_portfolio_proposal", "save_risk_decision", "save_portfolio_decision",
})


@dataclass(frozen=True)
class AblationVariant:
    name: str
    alpha: AlphaPolicy
    system: SystemPortfolioPolicy
    description: str


def default_variants(*, cvar_limits: Sequence[float] = (0.05, 0.12)) -> tuple[AblationVariant, ...]:
    base_alpha, base_system = AlphaPolicy(), SystemPortfolioPolicy()
    risk_alpha = replace(base_alpha, use_ml=False, use_thesis=False)
    variants = [
        AblationVariant("factor_only", replace(base_alpha, use_ml=False, use_thesis=False), base_system, "factor 사전값만"),
        AblationVariant("factor_ml", replace(base_alpha, use_thesis=False), base_system, "factor + champion ML"),
        AblationVariant("factor_ml_thesis", base_alpha, base_system, "factor + ML + TradingAgents(운영 구성)"),
        AblationVariant("no_tail_risk", risk_alpha, replace(base_system, use_tail_risk=False), "factor 입력에서 CVaR 축소만 끔"),
        AblationVariant("no_market_risk", risk_alpha, replace(base_system, use_market_risk=False), "factor 입력에서 시장위험 예산만 끔"),
        AblationVariant("absolute_risk", risk_alpha, replace(base_system, benchmark_relative_risk=False),
                        "factor 입력에서 위험을 절대 분산으로 잼(현금 편향이 있던 이전 운영 구성)"),
        AblationVariant("blom_z", replace(risk_alpha, z_score_method="blom"), base_system,
                        "factor 입력 + Blom z(상위 종목 동률 해소)"),
        AblationVariant("continuous_exposure", risk_alpha,
                        replace(base_system,
                                market_risk_policy=replace(base_system.market_risk_policy, continuous_exposure=True)),
                        "factor 입력 + 연속 노출(현금 계단 대신 변동성·낙폭 함수)"),
        AblationVariant("ic_02", replace(risk_alpha, information_coefficient=0.02), base_system,
                        "factor 입력 + 측정 IC 0.02(gated composite 20일 IC 0.027, t<2)"),
    ]
    variants += [
        AblationVariant(f"cvar_{round(limit * 100)}", risk_alpha, replace(base_system, max_cvar_95_5d=limit),
                        f"factor 입력에서 CVaR 한도 {limit:.0%}")
        for limit in cvar_limits
    ]
    return tuple(variants)


def _default_feature_rows(start: datetime, end: datetime) -> list[dict[str, Any]]:
    from investment_agent.research.storage.repository import ResearchStore

    return ResearchStore(read_only=True).records("rl_feature_snapshots", start_as_of=start.isoformat(),
                                                 end_as_of=end.isoformat())


class ReplayRepository:
    """운영 repository를 감싸 판단 시각 기준으로 읽고, 판단 기록 저장은 버린다."""

    def __init__(
        self,
        base: Any,
        *,
        feature_rows: Callable[[datetime, datetime], list[dict[str, Any]]] = _default_feature_rows,
        cross_section: Callable[[datetime], Any] | None = None,
    ) -> None:
        self._base = base
        self._feature_rows = feature_rows
        self._cross_section = cross_section
        self.now: datetime | None = None
        self.thesis_view_count = 0
        self.factor_category_periods: dict[str, set[str]] = {}
        self.proposals: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        if name in _LEDGER_WRITES:
            return lambda *args, **kwargs: None
        return getattr(self._base, name)

    def current_tracked_tickers(self) -> list[str]:
        """판단 시각의 S&P 500 멤버. 지금 추적 중인 목록을 과거에 대입하면 생존 편향이 생긴다."""
        if self.now is None:
            raise RuntimeError("replay time is not set")
        return research_universe(self._base, as_of_at=self.now, source_kind="historical_replay")

    def factor_cross_section(self, as_of_at: datetime, *, universe_size: int | None = None):
        if self._cross_section is not None:
            result = self._cross_section(as_of_at)
            self._record_factor_categories(result)
            return result
        from investment_agent.research.factors import latest_cross_section, score_cross_section

        members = set(self.current_tracked_tickers())
        rows = [
            row for row in self._feature_rows(as_of_at - timedelta(days=_CROSS_SECTION_WINDOW_DAYS), as_of_at)
            if parse_datetime(str(row["available_at"])) <= as_of_at and str(row["ticker"]).upper() in members
        ]
        section = latest_cross_section(rows, min_coverage=max(1, len(members) // 2))
        if section is None:
            return None
        snapshot_as_of, features = section
        result = snapshot_as_of, score_cross_section(features, groups=self._base.sp500_sector_map(list(features)))
        self._record_factor_categories(result)
        return result

    def _record_factor_categories(self, result: Any) -> None:
        if result is None:
            return
        snapshot_as_of, scores = result
        for score in scores.values():
            for category in score.category_scores:
                self.factor_category_periods.setdefault(str(category), set()).add(str(snapshot_as_of))

    def save_portfolio_proposal(self, payload: Mapping[str, Any]) -> None:
        """운영 원장에는 쓰지 않고 어블레이션 입력 활성도 계측에만 보관한다."""
        self.proposals.append(dict(payload))

    def thesis_views(self, tickers: Sequence[str], *, as_of_at: datetime, valid_days: int) -> dict[str, Any]:
        views = self._base.thesis_views(tickers, as_of_at=as_of_at, valid_days=valid_days)
        self.thesis_view_count += len(views)
        return views


def ml_artifact_lookahead(payload: Mapping[str, Any], *, replay_start: datetime) -> str | None:
    """모델의 학습·검증 구간이 재현 시작 이후까지 이어지면 그 이유를 돌려준다."""
    artifact = payload.get("artifact") or {}
    ends = [period[1] for period in (artifact.get("train_period"), artifact.get("validation_period"),
                                     artifact.get("oos_period")) if isinstance(period, (list, tuple)) and len(period) == 2]
    if not ends:
        return "ML artifact does not state its training periods"
    latest = max(parse_datetime(str(value)) for value in ends)
    if latest >= replay_start:
        return f"ML artifact was fit on data through {latest.isoformat()}, after the replay start"
    return None


def replay_sessions(base: Any, *, start: date, end: date) -> list[datetime]:
    """재현 기간의 정규장 마감 뒤 확정 시각. SPY 일봉이 거래일 달력이다."""
    horizon = datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
    rows = base.market_prices(BENCHMARK_SYMBOL, horizon, limit=max(300, (end - start).days + 30))
    dates = sorted({str(row["trade_date"])[:10] for row in rows if start.isoformat() <= str(row["trade_date"])[:10] <= end.isoformat()})
    return [bar_available_at(value) for value in dates]


def _variant_result(store: SystemPortfolioStore, repository: ReplayRepository, *, variant: AblationVariant,
                    targets: int, skipped: Mapping[str, int], ml_forecasts_applied: int) -> dict[str, Any]:
    history = store.history()
    target_rows = store.targets(limit=max(50, targets + 1))
    risky = sum(
        any(symbol != CASH_SYMBOL and float(weight) > 0 for symbol, weight in target.weights.items())
        for target in target_rows if target.is_approved
    )
    adjustments = sum(len(target.detail.get("adjustments") or ()) for target in target_rows)
    metadata = [dict(proposal.get("metadata") or {}) for proposal in repository.proposals]
    tail = [dict(item.get("tail_risk") or {}) for item in metadata]
    regimes = [item.get("market_regime") for item in metadata]
    return {
        "name": variant.name,
        "description": variant.description,
        "alpha_policy": variant.alpha.to_dict(),
        "system_policy": variant.system.to_dict(),
        "summary": performance_summary(history),
        "targets": targets,
        "skipped": dict(skipped),
        "thesis_views_seen": repository.thesis_view_count,
        "coverage": {
            "factor_snapshot_periods": len({target.factor_snapshot_as_of for target in target_rows}),
            "ml_forecasts_applied": ml_forecasts_applied,
            "thesis_views_seen": repository.thesis_view_count,
            "risky_target_count": risky,
            "risk_adjustment_count": adjustments,
            "factor_category_periods": {
                category: len(periods) for category, periods in sorted(repository.factor_category_periods.items())
            },
            "tail_risk_enabled_periods": sum(bool(item.get("enabled")) for item in tail),
            "tail_risk_bound_periods": sum(float(item.get("scale", 1.0)) < 1.0 - 1e-9 for item in tail),
            "market_risk_input_periods": sum(regime is not None for regime in regimes),
            "nav_unexplained_days": unexplained_nav_days(history)[:20],
            "turnover_breaches": turnover_breaches(history, {target.target_id: target for target in target_rows}),
            # RISK_ON은 한도를 조이지 않는다(배율 1.0, 현금 하한 0) — 조인 것은 RISK_OFF·CRISIS뿐이다.
            "market_risk_tightened_periods": sum(
                isinstance(regime, Mapping) and regime.get("risk_state") in {"RISK_OFF", "CRISIS"}
                for regime in regimes
            ),
            "market_regime_periods": {
                state: sum(isinstance(regime, Mapping) and regime.get("risk_state") == state for regime in regimes)
                for state in ("RISK_ON", "NORMAL", "RISK_OFF", "CRISIS")
            },
        },
        "_history": history,
    }


# 게이트는 재량 매매에만 turnover 한도를 걸고, 위험을 줄이는 조정(현금 하한 상향·종목/섹터 상한·최소 비중
# 정리·강제 청산)은 그 뒤에 둔다. 이 조정이 있었던 재조정의 한도 초과는 위반이 아니라 설계다.
_RISK_REDUCING_ADJUSTMENTS = ("CASH raised", "capped at", "below minimum position")
_REBALANCE_TURNOVER_LIMIT = 0.25


def turnover_breaches(history: Sequence[Any], targets: Mapping[str, Any]) -> list[dict[str, Any]]:
    """첫 편입 뒤 재조정 turnover가 한도를 넘은 날과, 그날 목표에 위험 축소 조정이 있었는지."""
    breaches: list[dict[str, Any]] = []
    seen_first = False
    for mark in history:
        if mark.turnover <= 0:
            continue
        if not seen_first:
            seen_first = True
            continue
        if mark.turnover <= _REBALANCE_TURNOVER_LIMIT + 1e-9:
            continue
        target = targets.get(mark.applied_target_id)
        detail = target.detail if target is not None else {}
        adjustments = [str(item) for item in detail.get("adjustments") or ()]
        risk_reducing = bool(detail.get("forced_exits")) or any(
            marker in item for item in adjustments for marker in _RISK_REDUCING_ADJUSTMENTS)
        breaches.append({"trade_date": mark.trade_date, "turnover": mark.turnover, "risk_reducing": risk_reducing})
    return breaches


# 하루 NAV 수익률과 보유 비중 × 가격 변화의 차이가 이보다 크면 가격으로 설명되지 않는 날이다. 배당(하루
# 수 bp)과 재조정 비용은 이보다 훨씬 작다.
_NAV_RECONCILIATION_TOLERANCE = 0.01


def unexplained_nav_days(history: Sequence[Any]) -> list[dict[str, Any]]:
    """NAV 수익률을 가격표로 독립 재계산해 설명되지 않는 날을 돌려준다.

    분할을 이중 반영하던 회계 결함은 5년 재현에서 +553%를 만들었는데 아무 검사도 걸리지 않았다.
    원장의 NAV를 원장 자신과 비교하면 같은 결함을 공유한다 — 가격 변화로 따로 계산해 대조한다.
    """
    offenders: list[dict[str, Any]] = []
    for previous, mark in zip(history, history[1:]):
        independent = 0.0
        for symbol, weight in previous.weights.items():
            if symbol == CASH_SYMBOL or weight <= 0:
                continue
            before, after = previous.closes.get(symbol), mark.closes.get(symbol)
            if before and after:
                independent += float(weight) * (float(after) / float(before) - 1.0)
        gap = float(mark.daily_return) - independent
        if abs(gap) > _NAV_RECONCILIATION_TOLERANCE:
            offenders.append({"trade_date": mark.trade_date, "daily_return": mark.daily_return,
                              "price_explained": independent, "gap": gap})
    return offenders


def _rebased(history: Sequence[Any]) -> list[dict[str, Any]]:
    """공통 평가 구간의 첫날을 NAV·벤치마크 모두 `INITIAL_NAV`로 다시 맞춘다.

    변형마다 원장은 자기 첫 기록일부터 NAV를 쌓는다. 공통 날짜만 잘라도 다시 맞추지 않으면 변형마다 다른
    출발점의 누적 수익을 비교하게 된다 — 같은 날짜를 보는데 SPY 수익률이 변형마다 달라지는 것이 그 증상이다.
    """
    if not history:
        return []
    first = history[0]
    nav_scale, benchmark_scale = INITIAL_NAV / first.nav, INITIAL_NAV / first.benchmark_nav
    return [{**mark.__dict__, "nav": mark.nav * nav_scale, "benchmark_nav": mark.benchmark_nav * benchmark_scale}
            for mark in history]


# 설계 §9.2의 목표 tracking error(연 6%)와 허용 폭(±50%).
TARGET_TRACKING_ERROR = 0.06
_TRACKING_ERROR_BAND = 0.5


def adoption_checks(summary: Mapping[str, Any], champion: Mapping[str, Any]) -> dict[str, Any]:
    """설계 §9.2의 채택 기준을 숫자로 판정한다. 값이 없으면 None — 통과로 치지 않는다.

    채택은 이 표가 모두 True일 때 사람이 한다. 표가 자동 승격을 하지 않는다.
    """
    def at_least(key: str) -> bool | None:
        value, base = summary.get(key), champion.get(key)
        return None if value is None or base is None else value >= base

    stress = (summary.get("stress") or {}).get("2022_bear") or {}

    def not_worse_than_spy(key: str) -> bool | None:
        value, benchmark = stress.get(key), stress.get(f"benchmark_{key}")
        return None if value is None or benchmark is None else value <= benchmark

    tracking_error = summary.get("tracking_error")
    breaches = summary.get("turnover_breaches")
    checks: dict[str, Any] = {
        "excess_return_not_worse": at_least("excess_return"),
        "information_ratio_not_worse": at_least("information_ratio"),
        "tracking_error_within_target": None if tracking_error is None else
        abs(tracking_error - TARGET_TRACKING_ERROR) <= TARGET_TRACKING_ERROR * _TRACKING_ERROR_BAND,
        "drawdown_2022_not_worse_than_spy": not_worse_than_spy("max_drawdown"),
        "cvar_2022_not_worse_than_spy": not_worse_than_spy("cvar_95_5d"),
        # 위험 축소 조정이 있었던 재조정의 초과는 설계다. 그런 조정 없이 넘은 날이 하나라도 있으면 실패다.
        "rebalance_turnover_within_limit": None if breaches is None else
        not any(not item["risk_reducing"] for item in breaches),
    }
    checks["all_passed"] = all(value is True for value in checks.values())
    return checks


def _coverage_reason(row: Mapping[str, Any], variant: AblationVariant) -> str | None:
    coverage = row["coverage"]
    if coverage.get("nav_unexplained_days"):
        return "nav_not_explained_by_prices"
    if not row.get("targets") or not coverage["factor_snapshot_periods"]:
        return "factor_target_never_built"
    if variant.alpha.use_ml and not coverage["ml_forecasts_applied"]:
        return "ml_forecast_never_applied"
    if variant.alpha.use_thesis and not coverage["thesis_views_seen"]:
        return "thesis_view_never_observed"
    # 변형 이름 목록으로 판정하면 `--cvar-limits`가 기본값(0.05·0.12)이 아닐 때 이름이
    # `cvar_3`·`cvar_20`이 되어 이 검사가 조용히 건너뛰어진다. 그러면 게이트가 위험자산을
    # 전부 거절한 회차도 `completed`로 보고된다. 그래서 정책 차이 자체로 판정한다.
    baseline = SystemPortfolioPolicy()
    changes_risk_policy = (
        variant.system.use_tail_risk != baseline.use_tail_risk
        or variant.system.use_market_risk != baseline.use_market_risk
        or variant.system.max_cvar_95_5d != baseline.max_cvar_95_5d
        or variant.system.benchmark_relative_risk != baseline.benchmark_relative_risk
    )
    if changes_risk_policy and not coverage["risky_target_count"]:
        return "risk_policy_never_exercised"
    return None


def run_ablation(
    base: Any,
    *,
    start: date,
    end: date,
    variants: Sequence[AblationVariant] | None = None,
    ml_artifact: Mapping[str, Any] | None = None,
    feature_rows: Callable[[datetime, datetime], list[dict[str, Any]]] = _default_feature_rows,
    cross_section: Callable[[datetime], Any] | None = None,
    work_dir: Path | None = None,
) -> dict[str, Any]:
    """변형마다 System 엔진을 재현 기간 동안 돌려 성과 요약을 모은다."""
    if end <= start:
        raise ValueError("ablation end must be after start")
    selected = tuple(variants or default_variants())
    sessions = replay_sessions(base, start=start, end=end)
    if not sessions:
        raise ValueError("no trading sessions in the replay window")
    lookahead = ml_artifact_lookahead(ml_artifact, replay_start=sessions[0]) if ml_artifact is not None else None
    # 단계 진단은 판단 뒤의 실현 가격으로 채점한다(판단 입력이 아니라 사후 평가라 미래 가격을 읽는 것이 맞다).
    # 재현 끝 이후 가격까지 있어야 마지막 목표들도 긴 기간으로 채점된다.
    price_limit = len(sessions) + max(DIAGNOSIS_HORIZONS) + 90
    prices = PricePaths(lambda symbol: base.market_prices(symbol, datetime.now(timezone.utc), limit=price_limit))
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(dir=work_dir) as scratch:
        model_path = None
        if ml_artifact is not None and lookahead is None:
            model_path = Path(scratch) / "champion.json"
            model_path.write_text(json.dumps(dict(ml_artifact)), encoding="utf-8")
        for variant in selected:
            if variant.alpha.use_ml and ml_artifact is not None and lookahead is not None:
                results.append({"name": variant.name, "description": variant.description, "status": "refused",
                                "reason": lookahead})
                continue
            repository = ReplayRepository(base, feature_rows=feature_rows, cross_section=cross_section)
            store = SystemPortfolioStore(Path(scratch) / f"{variant.name}.sqlite3")
            ml_forecasts_applied = 0

            def forecast(repo, tickers, *, as_of_at):
                nonlocal ml_forecasts_applied
                if model_path is None:
                    return NO_FORECAST
                result = champion_forecast(
                    repo, tickers, as_of_at=as_of_at, model_path=model_path, store=repo,
                )
                if result.is_available:
                    ml_forecasts_applied += 1
                return result

            targets = 0
            skipped: dict[str, int] = {}
            for now in sessions:
                repository.now = now
                result = run_system(store, repository, now=now, alpha_policy=variant.alpha, policy=variant.system,
                                    forecast=forecast)
                if result.target_id:
                    targets += 1
                elif result.skipped_reason:
                    skipped[result.skipped_reason] = skipped.get(result.skipped_reason, 0) + 1
            log.info("ablation variant %s done targets=%d", variant.name, targets)
            row = _variant_result(store, repository, variant=variant, targets=targets, skipped=skipped,
                                  ml_forecasts_applied=ml_forecasts_applied)
            row["stage_diagnosis"] = diagnose(
                [(target.decided_at[:10], target.detail.get("stage_trace"))
                 for target in store.targets(limit=max(50, targets + 1))],
                prices,
            )
            reason = _coverage_reason(row, variant)
            results.append({"status": "insufficient_coverage" if reason else "completed",
                            **({"reason": reason} if reason else {}), **row})

    comparable = [row for row in results if row.get("status") == "completed" and row.get("_history")]
    common_dates = set.intersection(*[
        {mark.trade_date for mark in row["_history"]} for row in comparable
    ]) if comparable else set()
    for row in results:
        history = row.pop("_history", None)
        if history is None:
            continue
        selected_history = [mark for mark in history if mark.trade_date in common_dates] if common_dates else history
        row["summary"] = performance_summary(_rebased(selected_history))
        # performance_summary의 cash_weight는 마지막 날 값이다. 현금 편향은 기간 평균으로 본다.
        cash = [float(dict(mark.weights).get(CASH_SYMBOL, 0.0)) for mark in selected_history]
        row["summary"]["average_cash_weight"] = sum(cash) / len(cash) if cash else None
        row["summary"].update(active_risk_summary(_rebased(selected_history)))
        row["summary"]["turnover_breaches"] = [item for item in row["coverage"].get("turnover_breaches") or ()
                                               if not common_dates or item["trade_date"] in common_dates]
        row["coverage"]["common_evaluation_start"] = min(common_dates) if common_dates else None
        row["coverage"]["common_evaluation_end"] = max(common_dates) if common_dates else None
    baseline = next((row for row in results if row.get("status") == "completed"), None)
    for row in results:
        if row.get("status") != "completed" or baseline is None:
            continue
        summary, base_summary = row["summary"], baseline["summary"]
        row["versus_baseline"] = {
            key: (summary[key] - base_summary[key])
            if isinstance(summary.get(key), (int, float)) and isinstance(base_summary.get(key), (int, float)) else None
            for key in ("total_return", "excess_return", "max_drawdown", "annualized_volatility", "annualized_turnover",
                        "average_cash_weight", "tracking_error", "information_ratio")
        }
        row["adoption_checks"] = adoption_checks(summary, base_summary)
    return {
        "version": ABLATION_VERSION,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "sessions": len(sessions),
        "baseline": baseline["name"] if baseline else None,
        "ml_artifact_id": ((ml_artifact or {}).get("artifact") or {}).get("artifact_id"),
        "variants": results,
    }


__all__ = [
    "ABLATION_VERSION",
    "AblationVariant",
    "ReplayRepository",
    "TARGET_TRACKING_ERROR",
    "adoption_checks",
    "default_variants",
    "turnover_breaches",
    "ml_artifact_lookahead",
    "replay_sessions",
    "run_ablation",
    "unexplained_nav_days",
]
