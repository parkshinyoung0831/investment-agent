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
    variants = [
        AblationVariant("factor_only", replace(base_alpha, use_ml=False, use_thesis=False), base_system, "factor 사전값만"),
        AblationVariant("factor_ml", replace(base_alpha, use_thesis=False), base_system, "factor + champion ML"),
        AblationVariant("factor_ml_thesis", base_alpha, base_system, "factor + ML + TradingAgents(운영 구성)"),
        AblationVariant("no_tail_risk", base_alpha, replace(base_system, use_tail_risk=False), "운영 구성에서 CVaR 축소 끔"),
        AblationVariant("no_market_risk", base_alpha, replace(base_system, use_market_risk=False), "운영 구성에서 시장위험 예산 끔"),
    ]
    variants += [
        AblationVariant(f"cvar_{round(limit * 100)}", base_alpha, replace(base_system, max_cvar_95_5d=limit),
                        f"운영 구성에서 CVaR 한도 {limit:.0%}")
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
            return self._cross_section(as_of_at)
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
        return snapshot_as_of, score_cross_section(features, groups=self._base.sp500_sector_map(list(features)))

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
                    targets: int, skipped: Mapping[str, int]) -> dict[str, Any]:
    history = store.history()
    return {
        "name": variant.name,
        "description": variant.description,
        "alpha_policy": variant.alpha.to_dict(),
        "system_policy": variant.system.to_dict(),
        "summary": performance_summary(history),
        "targets": targets,
        "skipped": dict(skipped),
        "thesis_views_seen": repository.thesis_view_count,
    }


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

            def forecast(repo, tickers, *, as_of_at):
                if model_path is None:
                    return NO_FORECAST
                return champion_forecast(repo, tickers, as_of_at=as_of_at, model_path=model_path)

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
            results.append({"status": "completed", **_variant_result(store, repository, variant=variant,
                                                                     targets=targets, skipped=skipped)})
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
