"""저장된 원본 판단을 관측 상태로 쓰는 가상 시장 PPO 학습 입력."""
from __future__ import annotations
import hashlib
from datetime import timedelta
from typing import Mapping
import numpy as np
from investment_agent.platform.serialization import canonical_json, parse_datetime
from investment_agent.research.rl.environment import FeatureDataset
from investment_agent.research.rl.features import HistoricalTrainingSet, LiveInferenceFrame
from investment_agent.research.rl.contracts import RLDataNotReadyError

FEATURE_VERSION = "decision_v1"
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

def decision_training_set(rows, *, as_of_at, max_symbols):
    cutoff = parse_datetime(as_of_at)
    rows = [row for row in rows if parse_datetime(row["available_at"]) <= cutoff]
    if not rows: raise RLDataNotReadyError("no mature original decision experience")
    symbols = tuple(sorted({row["ticker"] for row in rows})[:max_symbols])
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
    dataset=FeatureDataset(symbols, FEATURE_NAMES, times, features, returns, benchmarks, masks, FEATURE_VERSION)
    digest=hashlib.sha256(canonical_json(rows).encode()).hexdigest()
    membership=hashlib.sha256(canonical_json({"symbols":symbols,"times":times,"availability":masks.tolist()}).encode()).hexdigest()
    return HistoricalTrainingSet(dataset,tuple(ends),membership,tuple(ids),tuple(ids),digest)

def decision_inference_frame(model, proposals, *, as_of_at):
    if model.feature_names != FEATURE_NAMES:
        raise ValueError("decision model feature axes mismatch")
    by_ticker={p.ticker:p for p in proposals}
    if len(by_ticker) != len(proposals):
        raise ValueError("duplicate original decision ticker")
    features=np.zeros((len(model.symbols),len(FEATURE_NAMES))); mask=np.zeros(len(model.symbols),dtype=bool)
    for i,ticker in enumerate(model.symbols):
        if ticker not in by_ticker: continue
        proposal=by_ticker[ticker]
        if parse_datetime(proposal.as_of_at)>parse_datetime(as_of_at): raise ValueError("future decision")
        features[i]=[decision_features(proposal)[name] for name in FEATURE_NAMES]; mask[i]=True
    if not mask.any(): raise ValueError("no original decisions match model axes")
    digest=hashlib.sha256(canonical_json({"features":features.tolist(),"mask":mask.tolist(),"as_of_at":str(as_of_at)}).encode()).hexdigest()
    return LiveInferenceFrame(model.symbols, FEATURE_NAMES, FEATURE_VERSION, str(as_of_at), features, mask, digest, digest)
