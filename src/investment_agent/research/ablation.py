"""Ablation: 각 모듈이 System Portfolio 성과를 실제로 개선하는지 같은 과거 재현에서 비교한다.

```
같은 기간 · 같은 PIT 데이터 · 같은 비용 · 같은 유니버스
  ├ factor_only             factor 사전값만
  ├ factor_ml               + champion ML
  ├ factor_ml_thesis        + TradingAgents 논지(운영 구성)
  ├ no_tail_risk            운영 구성에서 CVaR 축소만 끔
  ├ no_market_risk          운영 구성에서 시장위험 예산만 끔
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
from investment_agent.trading.system.accounting import performance_summary
from investment_agent.trading.system.engine import run_system
from investment_agent.trading.system.store import SystemPortfolioStore
from investment_agent.trading.system.target import SystemPortfolioPolicy
from investment_agent.trading.portfolio.contracts import CASH_SYMBOL

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
        from investment_agent.research.features.factors import latest_cross_section, score_cross_section
        from investment_agent.research.features.layer import FEATURE_VERSION

        members = set(self.current_tracked_tickers())
        rows = [
            row for row in self._feature_rows(as_of_at - timedelta(days=_CROSS_SECTION_WINDOW_DAYS), as_of_at)
            if parse_datetime(str(row["available_at"])) <= as_of_at and str(row["ticker"]).upper() in members
        ]
        section = latest_cross_section(rows, feature_version=FEATURE_VERSION, min_coverage=max(1, len(members) // 2))
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
            "market_risk_tightened_periods": sum(
                isinstance(regime, Mapping) and regime.get("risk_state") not in {None, "NORMAL"}
                for regime in regimes
            ),
        },
        "_history": history,
    }


def _coverage_reason(row: Mapping[str, Any], variant: AblationVariant) -> str | None:
    coverage = row["coverage"]
    if not row.get("targets") or not coverage["factor_snapshot_periods"]:
        return "factor_target_never_built"
    if variant.alpha.use_ml and not coverage["ml_forecasts_applied"]:
        return "ml_forecast_never_applied"
    if variant.alpha.use_thesis and not coverage["thesis_views_seen"]:
        return "thesis_view_never_observed"
    if variant.name in {"no_tail_risk", "no_market_risk", "cvar_5", "cvar_12"} and not coverage["risky_target_count"]:
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
                result = champion_forecast(repo, tickers, as_of_at=as_of_at, model_path=model_path)
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
        row["summary"] = performance_summary(selected_history)
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
            for key in ("total_return", "excess_return", "max_drawdown", "annualized_volatility", "annualized_turnover")
        }
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
    "default_variants",
    "ml_artifact_lookahead",
    "replay_sessions",
    "run_ablation",
]
