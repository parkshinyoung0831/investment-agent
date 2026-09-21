"""과거 재현 시점들의 factor 점수가 실제로 앞으로의 수익률 순위를 맞혔는지(IC) 잰다.

    python -m investment_agent.research.commands.factor_research
    python -m investment_agent.research.commands.factor_research --horizons 20 60 126

## 무엇을 재는가

시점마다 종목들을 factor 점수로 줄 세운 순위와, 그 뒤 h거래일 수익률로 줄 세운 순위의 Spearman 상관이
IC다. 모든 종목에서 같은 벤치마크를 빼도 순위는 변하지 않으므로 초과수익 대신 원 수익률을 쓴다.

- **어느 기간(horizon)에 쓸지**: factor마다 IC가 5·20·60·126일 중 어디서 가장 크고 오래 가는지(decay)로
  고른다. 기간을 먼저 정해 두고 factor를 맞추지 않는다.
- **가중치 제안**: 평균 IC가 양수이고 겹침 보정 t가 기준을 넘는 category만 IC에 비례해 제안한다. 제안일 뿐
  `FactorModel`에 자동 반영하지 않는다 — 몇십 개 시점의 IC는 우연과 구별이 어렵다.

## 알고 읽어야 할 한계

- 판단 시점 간격보다 기간이 길면 인접 시점의 수익률 구간이 겹쳐 t가 부풀려진다. `t_stat_overlap_adjusted`는
  겹치는 배수의 제곱근으로 나눈 보수적 값이다.
- 기간 끝 종가가 없는 종목(상장폐지·합병)은 빠진다. 살아남은 종목 쪽으로 치우친 IC다.
- 배당은 넣지 않은 가격 수익률이다. 고배당 가치주의 IC가 약간 낮게 나온다.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from investment_agent.platform.storage_paths import repository_artifact_root
from investment_agent.data.market import persistence as market_data
from investment_agent.data.universe import persistence as universe_data
from investment_agent.platform.logging import get_logger
from investment_agent.research.factors import (
    FACTOR_CATEGORIES,
    FactorModel,
    percentile_ranks,
    score_cross_section,
)

log = get_logger(__name__)

DEFAULT_HORIZONS = (5, 20, 60, 126)
REFERENCE_TICKER = "SPY"
# 한 시점의 IC를 믿을 최소 종목 수.
MIN_CROSS_SECTION = 30
# 가격 비율이 이 범위를 벗어나면 분할 미반영 같은 자료 오류로 보고 뺀다.
_MAX_PRICE_RATIO = 4.0
# 가중치를 제안할 최소 겹침 보정 t.
SUGGEST_MIN_T = 1.5
# 거래일 → 달력일 환산(겹침 판정용).
_CALENDAR_PER_TRADING_DAY = 365.25 / 252


def spearman(left: Mapping[str, float], right: Mapping[str, float]) -> tuple[float | None, int]:
    """두 값 사전의 공통 종목 순위 상관. 종목이 모자라거나 한쪽이 전부 같으면 None."""
    common = sorted(set(left) & set(right))
    if len(common) < MIN_CROSS_SECTION:
        return None, len(common)
    x = percentile_ranks({ticker: left[ticker] for ticker in common})
    y = percentile_ranks({ticker: right[ticker] for ticker in common})
    mean_x = math.fsum(x.values()) / len(common)
    mean_y = math.fsum(y.values()) / len(common)
    cov = math.fsum((x[t] - mean_x) * (y[t] - mean_y) for t in common)
    var_x = math.fsum((x[t] - mean_x) ** 2 for t in common)
    var_y = math.fsum((y[t] - mean_y) ** 2 for t in common)
    if var_x <= 0 or var_y <= 0:
        return None, len(common)
    return cov / math.sqrt(var_x * var_y), len(common)


def forward_returns(
    start_closes: Mapping[str, float], end_closes: Mapping[str, float],
) -> tuple[dict[str, float], int]:
    """시작·끝 종가가 모두 양수인 종목의 수익률. 비정상 비율은 빼고 그 개수를 돌려준다."""
    output: dict[str, float] = {}
    rejected = 0
    for ticker, start in start_closes.items():
        end = end_closes.get(ticker)
        if end is None or start <= 0 or end <= 0:
            continue
        ratio = end / start
        if not 1 / _MAX_PRICE_RATIO <= ratio <= _MAX_PRICE_RATIO:
            rejected += 1
            continue
        output[ticker] = ratio - 1
    return output, rejected


def horizon_dates(calendar: Sequence[date], as_of: date, horizons: Iterable[int]) -> tuple[date | None, dict[int, date]]:
    """판단일 이하 마지막 거래일(시작)과, 그로부터 h거래일 뒤 날짜들. 달력이 모자라면 그 기간은 없다."""
    ordered = sorted(calendar)
    start_index = None
    for index, day in enumerate(ordered):
        if day <= as_of:
            start_index = index
        else:
            break
    if start_index is None:
        return None, {}
    ends = {h: ordered[start_index + h] for h in horizons if start_index + h < len(ordered)}
    return ordered[start_index], ends


def signal_values(
    features: Mapping[str, Mapping[str, float | None]],
    *,
    groups: Mapping[str, str] | None,
    model: FactorModel,
) -> dict[str, dict[str, float]]:
    """IC를 잴 신호들: 방향을 맞춘 개별 factor, category 점수, 종합 점수."""
    signals: dict[str, dict[str, float]] = defaultdict(dict)
    for members in FACTOR_CATEGORIES.values():
        for name, direction in members:
            for ticker, row in features.items():
                value = row.get(name)
                if value is not None and math.isfinite(float(value)):
                    signals[f"factor:{name}"][ticker] = float(value) * direction
    for ticker, score in score_cross_section(features, model=model, groups=groups).items():
        for category, value in score.category_scores.items():
            signals[f"category:{category}"][ticker] = value
        if score.composite is not None:
            signals["composite"][ticker] = score.composite
            if score.passes_quality_gate:
                signals["composite_gated"][ticker] = score.composite
    return dict(signals)


def quantile_spread(signal: Mapping[str, float], returns: Mapping[str, float], *, quantile: float = 0.2) -> float | None:
    """신호 상위 20% 평균 수익률 − 하위 20%. 순위 상관이 실제 수익 차이로 얼마인지 보여 준다."""
    common = sorted(set(signal) & set(returns), key=lambda ticker: (signal[ticker], ticker))
    bucket = int(len(common) * quantile)
    if len(common) < MIN_CROSS_SECTION or bucket < 1:
        return None
    bottom = [returns[ticker] for ticker in common[:bucket]]
    top = [returns[ticker] for ticker in common[-bucket:]]
    return math.fsum(top) / len(top) - math.fsum(bottom) / len(bottom)


@dataclass(frozen=True)
class IcSummary:
    mean_ic: float
    std_ic: float | None
    t_stat: float | None
    t_stat_overlap_adjusted: float | None
    positive_rate: float
    n_dates: int
    mean_spread: float | None

    def to_dict(self) -> dict[str, Any]:
        def rounded(value: float | None) -> float | None:
            return None if value is None else round(value, 6)
        return {
            "mean_ic": rounded(self.mean_ic),
            "std_ic": rounded(self.std_ic),
            "t_stat": rounded(self.t_stat),
            "t_stat_overlap_adjusted": rounded(self.t_stat_overlap_adjusted),
            "positive_rate": rounded(self.positive_rate),
            "n_dates": self.n_dates,
            "mean_spread": rounded(self.mean_spread),
        }


def summarize(ics: Sequence[float], spreads: Sequence[float], *, overlap_factor: float) -> IcSummary | None:
    if not ics:
        return None
    count = len(ics)
    mean = math.fsum(ics) / count
    std = math.sqrt(math.fsum((value - mean) ** 2 for value in ics) / (count - 1)) if count > 1 else None
    t_stat = mean / (std / math.sqrt(count)) if std else None
    adjusted = t_stat / math.sqrt(max(1.0, overlap_factor)) if t_stat is not None else None
    return IcSummary(
        mean_ic=mean,
        std_ic=std,
        t_stat=t_stat,
        t_stat_overlap_adjusted=adjusted,
        positive_rate=sum(1 for value in ics if value > 0) / count,
        n_dates=count,
        mean_spread=math.fsum(spreads) / len(spreads) if spreads else None,
    )


def overlap_factor(horizon_trading_days: int, spacing_calendar_days: float | None) -> float:
    """기간이 시점 간격의 몇 배인가. 1 이하면 구간이 겹치지 않는다."""
    if not spacing_calendar_days or spacing_calendar_days <= 0:
        return 1.0
    return max(1.0, horizon_trading_days * _CALENDAR_PER_TRADING_DAY / spacing_calendar_days)


def suggest_category_weights(
    summaries: Mapping[str, IcSummary | None], *, min_t: float = SUGGEST_MIN_T,
) -> dict[str, Any]:
    """평균 IC가 양수이고 겹침 보정 t가 기준 이상인 category만 IC 비례 가중치. 없으면 동일가중 유지."""
    eligible = {
        category: summary.mean_ic
        for category in FACTOR_CATEGORIES
        if (summary := summaries.get(category)) is not None
        and summary.mean_ic > 0
        and summary.t_stat_overlap_adjusted is not None
        and summary.t_stat_overlap_adjusted >= min_t
    }
    if not eligible:
        return {"basis": "equal_weight_kept", "weights": {name: 1.0 for name in FACTOR_CATEGORIES}}
    total = math.fsum(eligible.values())
    return {
        "basis": f"mean_ic_where_t_adj>={min_t}",
        "weights": {name: round(eligible.get(name, 0.0) / total, 4) for name in FACTOR_CATEGORIES},
    }


class _CloseCache:
    """(날짜, 종목)별로 종가를 한 번만 읽는다.

    날짜만 키로 쓰면 그 날짜를 먼저 요청한 종목 집합으로 채워져, 나중에 새로 들어온 멤버는 시작가가 없어
    조용히 수익률에서 빠진다(편입 종목이 IC 표본에서 누락). 요청한 종목 중 아직 못 읽은 것만 조회한다.
    """

    def __init__(self, closes_on: Callable[[Sequence[str], date], Mapping[str, float]]) -> None:
        self._closes_on = closes_on
        self._asked: dict[date, set[str]] = {}
        self._closes: dict[date, dict[str, float]] = {}

    def __call__(self, day: date, tickers: Sequence[str]) -> Mapping[str, float]:
        asked = self._asked.setdefault(day, set())
        missing = [ticker for ticker in tickers if ticker not in asked]
        if missing:
            self._closes.setdefault(day, {}).update(self._closes_on(missing, day))
            asked.update(missing)
        known = self._closes.get(day, {})
        return {ticker: known[ticker] for ticker in tickers if ticker in known}


def research(
    *,
    snapshots_by_date: Mapping[date, Mapping[str, Mapping[str, float | None]]],
    calendar: Sequence[date],
    closes_on: Callable[[Sequence[str], date], Mapping[str, float]],
    groups: Mapping[str, str] | None = None,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    model: FactorModel | None = None,
) -> dict[str, Any]:
    """시점별 IC를 계산하고 신호×기간으로 요약한다. 가격 조회는 주입받아 순수하게 시험할 수 있다."""
    selected = model or FactorModel()
    dates = sorted(snapshots_by_date)
    spacing = (
        (dates[-1] - dates[0]).days / (len(dates) - 1) if len(dates) > 1 else None
    )
    ics: dict[tuple[str, int], list[float]] = defaultdict(list)
    spreads: dict[tuple[str, int], list[float]] = defaultdict(list)
    per_date: list[dict[str, Any]] = []
    closes = _CloseCache(closes_on)

    for as_of in dates:
        features = snapshots_by_date[as_of]
        tickers = sorted(features)
        start_day, ends = horizon_dates(calendar, as_of, horizons)
        record: dict[str, Any] = {"as_of": as_of.isoformat(), "tickers": len(tickers), "horizons": {}}
        if start_day is None or not ends:
            record["status"] = "no_forward_window"
            per_date.append(record)
            continue
        signals = signal_values(features, groups=groups, model=selected)
        start_closes = closes(start_day, tickers)
        for horizon, end_day in sorted(ends.items()):
            returns, rejected = forward_returns(start_closes, closes(end_day, tickers))
            ic_row: dict[str, Any] = {"end": end_day.isoformat(), "returns": len(returns), "rejected_ratio": rejected}
            composite_ic, _ = spearman(signals.get("composite", {}), returns)
            ic_row["composite_ic"] = None if composite_ic is None else round(composite_ic, 6)
            record["horizons"][str(horizon)] = ic_row
            for name, values in signals.items():
                value, _count = spearman(values, returns)
                if value is None:
                    continue
                ics[(name, horizon)].append(value)
                spread = quantile_spread(values, returns)
                if spread is not None:
                    spreads[(name, horizon)].append(spread)
        record["status"] = "measured"
        per_date.append(record)

    summary: dict[str, dict[str, Any]] = defaultdict(dict)
    by_horizon_category: dict[int, dict[str, IcSummary | None]] = defaultdict(dict)
    for (name, horizon), values in sorted(ics.items()):
        result = summarize(values, spreads.get((name, horizon), []), overlap_factor=overlap_factor(horizon, spacing))
        summary[name][str(horizon)] = None if result is None else result.to_dict()
        if name.startswith("category:"):
            by_horizon_category[horizon][name.split(":", 1)[1]] = result
    best_horizon = {
        name: max(
            ((h, row) for h, row in horizons_row.items() if row is not None),
            key=lambda item: item[1]["mean_ic"],
        )[0]
        for name, horizons_row in summary.items()
        if any(row is not None for row in horizons_row.values())
    }
    return {
        "model_version": selected.version,
        "horizons": list(horizons),
        "n_dates": len(dates),
        "mean_spacing_days": None if spacing is None else round(spacing, 2),
        "summary": dict(summary),
        "best_horizon_by_signal": best_horizon,
        "suggested_weights_by_horizon": {
            str(horizon): suggest_category_weights(categories)
            for horizon, categories in sorted(by_horizon_category.items())
        },
        "per_date": per_date,
    }


def group_snapshots(rows: Iterable[Mapping[str, Any]]) -> dict[date, dict[str, dict]]:
    """저장 행을 판단일 → ticker → feature로."""
    output: dict[date, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        if not row.get("is_available", True):
            continue
        as_of = datetime.fromisoformat(str(row["as_of_at"]).replace("Z", "+00:00")).date()
        output[as_of][str(row["ticker"]).upper()] = dict(row.get("features") or {})
    return dict(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_agent.research.commands.factor_research")
    parser.add_argument("--horizons", type=int, nargs="+", default=list(DEFAULT_HORIZONS))
    parser.add_argument("--source-kind", default="historical_replay",
                        help="이 출처의 snapshot만 쓴다(provenance.source_kind). 빈 값이면 전부")
    parser.add_argument("--output-dir", default=str(repository_artifact_root() / "research" / "factor_ic"))
    args = parser.parse_args(argv)

    from investment_agent.research.storage.repository import ResearchStore

    rows = ResearchStore(read_only=True).records("rl_feature_snapshots")
    if args.source_kind:
        rows = [row for row in rows if (row.get("provenance") or {}).get("source_kind") in (None, args.source_kind)]
    snapshots = group_snapshots(rows)
    if not snapshots:
        log.warning("factor research has no feature snapshots")
        return 1
    tickers = sorted({ticker for day in snapshots.values() for ticker in day})
    first = min(snapshots)
    calendar = market_data.trading_dates(
        REFERENCE_TICKER, start=first - timedelta(days=10), end=datetime.now(timezone.utc).date(),
    )
    report = research(
        snapshots_by_date=snapshots,
        calendar=calendar,
        closes_on=market_data.closes_on_date,
        groups=universe_data.select_sp500_sector_map(tickers),
        horizons=tuple(sorted(set(args.horizons))),
    )
    report.update({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_kind": args.source_kind or None,
    })
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    (output_dir / "latest.json").write_text(payload, encoding="utf-8")
    (output_dir / f"factor_ic_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json").write_text(payload, encoding="utf-8")
    log.info("factor research dates=%d best=%s", report["n_dates"], report["best_horizon_by_signal"])
    return 0


__all__ = [
    "forward_returns",
    "group_snapshots",
    "horizon_dates",
    "main",
    "overlap_factor",
    "quantile_spread",
    "research",
    "signal_values",
    "spearman",
    "suggest_category_weights",
    "summarize",
]


if __name__ == "__main__":
    from investment_agent.bootstrap import start_cli
    start_cli()
    raise SystemExit(main())
