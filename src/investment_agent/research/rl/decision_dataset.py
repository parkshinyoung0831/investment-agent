"""저장된 원본 판단을 관측 상태로 쓰는 가상 시장 PPO 학습 입력."""
from __future__ import annotations
import hashlib
from datetime import timedelta
from typing import Mapping
import numpy as np
from investment_agent.platform.serialization import canonical_json, parse_datetime
from investment_agent.research.rl.environment import FeatureDataset
from investment_agent.research.rl.features import HistoricalTrainingSet
from investment_agent.research.rl.contracts import RLDataNotReadyError

ACTIONS = ("open", "increase", "hold", "reduce", "exit", "watch", "avoid")
FEATURE_NAMES = ("decision_confidence", "decision_probability_up", "decision_expected_excess_return", *(f"decision_action_{action}" for action in ACTIONS))

def decision_features(proposal):
    """실제 원본 제안의 scalar만 같은 순서의 관측값으로 변환한다."""
    from dataclasses import asdict
    values = dict(proposal) if isinstance(proposal, Mapping) else asdict(proposal)
    action = values.get("signal", values.get("action"))
    if action not in ACTIONS: raise ValueError("invalid decision action")
    features = {f"decision_{name}": float(values[name]) for name in ("confidence", "probability_up", "expected_excess_return")}
    features.update({f"decision_action_{name}": float(action == name) for name in ACTIONS})
    return features

def _most_observed_tickers(rows, max_symbols):
    """판단 경험이 가장 많은 종목 `max_symbols`개(동률은 이름순). 축 순서는 이름순으로 고정한다.

    이름순으로 앞에서 자르면 알파벳이 앞선 종목군만 학습에 남고 나머지 경험은 조용히 버려진다.
    경험 수는 수익률과 무관해 생존 편향을 넣지 않는다.
    """
    counts = {}
    for row in rows:
        counts[row["ticker"]] = counts.get(row["ticker"], 0) + 1
    ranked = sorted(counts, key=lambda ticker: (-counts[ticker], ticker))
    return tuple(sorted(ranked[:max_symbols]))


def decision_training_set(rows, *, as_of_at, max_symbols):
    cutoff = parse_datetime(as_of_at)
    rows = [row for row in rows if parse_datetime(row["available_at"]) <= cutoff]
    if not rows: raise RLDataNotReadyError("no mature original decision experience")
    symbols = _most_observed_tickers(rows, max_symbols)
    groups = {}
    for row in rows:
        if row["ticker"] not in symbols: continue
        if row["end_trade_date"] > cutoff.date().isoformat():
            raise ValueError("label interval ends after training cutoff")
        if set(row["features"]) != set(FEATURE_NAMES):
            raise ValueError("decision feature axes mismatch")
        point = max(parse_datetime(row["as_of_at"]), parse_datetime(row["decision_available_at"]))
        if point > cutoff: raise ValueError("decision unavailable at training cutoff")
        groups.setdefault(point.isoformat(), []).append(row)
    times = tuple(sorted(groups, key=parse_datetime))
    features = np.zeros((len(times), len(symbols), len(FEATURE_NAMES)))
    returns = np.zeros((len(times), len(symbols)))
    masks = np.zeros_like(returns, dtype=bool)
    benchmarks = np.zeros(len(times)); ends=[]; ids=[]
    for t, point in enumerate(times):
        period_rows = groups[point]
        horizons = {row["end_trade_date"] for row in period_rows}
        benchmark = {float(row["benchmark_return"]) for row in period_rows}
        if len(horizons)!=1 or len(benchmark)!=1: raise ValueError("inconsistent decision label horizons")
        ends.append((parse_datetime(next(iter(horizons))+"T00:00:00+00:00")+timedelta(days=1)).isoformat())
        benchmarks[t]=next(iter(benchmark))
        for row in period_rows:
            i=symbols.index(row["ticker"])
            if masks[t,i]: raise ValueError("duplicate decision observation")
            features[t,i]=[float(row["features"][name]) for name in FEATURE_NAMES]
            returns[t,i]=float(row["asset_return"])
            masks[t,i]=True; ids.append(row["record_key"])
    dataset=FeatureDataset(symbols, FEATURE_NAMES, times, features, returns, benchmarks, masks)
    digest=hashlib.sha256(canonical_json(rows).encode()).hexdigest()
    membership=hashlib.sha256(canonical_json({"symbols":symbols,"times":times,"availability":masks.tolist()}).encode()).hexdigest()
    return HistoricalTrainingSet(dataset,tuple(ends),membership,tuple(ids),tuple(ids),digest)
