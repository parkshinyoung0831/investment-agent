"""학습과 추론이 공유하는 무결성 검증 PPO 산출물."""
from __future__ import annotations
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import numpy as np
from investment_agent.platform.serialization import canonical_json
from investment_agent.research.rl.environment import action_to_weights

SCHEMA = "ppo-policy-v1"

def _load_ppo(path):
    from stable_baselines3 import PPO
    return PPO.load(str(path), device="cpu")

@dataclass(frozen=True)
class PPOPolicy:
    model: Any
    metadata: dict

    @property
    def symbols(self): return tuple(self.metadata["symbols"])
    @property
    def feature_names(self): return tuple(self.metadata["feature_names"])
    @property
    def feature_version(self): return self.metadata["feature_version"]
    @property
    def artifact_id(self): return self.metadata["artifact_id"]
    @property
    def dsr_probability(self): return float(self.metadata["score"]["dsr_probability"])

    def predict(self, observation, deterministic=True):
        return self.model.predict(np.asarray(observation, dtype=np.float32), deterministic=deterministic)

    def predict_weights(self, frame, *, current_weights=None):
        if (frame.symbols, frame.feature_names, frame.feature_version) != (self.symbols, self.feature_names, self.feature_version):
            raise ValueError("policy observation axes mismatch")
        weights = {"CASH": 1.0} if current_weights is None else current_weights
        axis = (*self.symbols, "CASH")
        if set(weights) - set(axis): raise ValueError("holdings outside policy axes")
        values=np.array([weights.get(k, 0.0) for k in axis], dtype=float)
        if not np.isfinite(values).all() or (values < 0).any() or not np.isclose(values.sum(), 1):
            raise ValueError("invalid current weights")
        observation=np.concatenate((frame.features.ravel(), frame.availability.astype(float), values))
        action, _=self.predict(observation)
        return dict(zip(axis, map(float, action_to_weights(action, frame.availability))))

def save_policy_bundle(model, directory: Path, *, dataset, score: Mapping, training: Mapping) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    import tempfile
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        binary=Path(tmp)/"policy.zip"
        model.save(str(binary))
        data=binary.read_bytes()
    digest=hashlib.sha256(data).hexdigest()
    payload={"schema": SCHEMA, "algorithm":"ppo", "symbols":list(dataset.symbols),
             "feature_names":list(dataset.feature_names), "feature_version":dataset.feature_version,
             "normalization":{"kind":"identity", "observation_dtype":"float32"},
             "action_axis":[*dataset.symbols,"CASH"], "model_sha256":digest,
             "model_binary":digest+".zip", "score":dict(score), "training":dict(training)}
    identity=hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    payload["artifact_id"]=identity
    target=directory/(identity+".json")
    binary=directory/payload["model_binary"]
    if binary.exists() and binary.read_bytes()!=data: raise ValueError("immutable binary collision")
    if not binary.exists():
        with binary.open("xb") as stream:
            stream.write(data)
    serialized=canonical_json(payload)+"\n"
    if target.exists() and target.read_text(encoding="utf-8")!=serialized: raise ValueError("immutable metadata collision")
    if not target.exists():
        with target.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
    return target

def load_policy_bundle(path: Path) -> PPOPolicy:
    payload=json.loads(path.read_text(encoding="utf-8"))
    identity=payload.pop("artifact_id")
    if hashlib.sha256(canonical_json(payload).encode()).hexdigest()!=identity: raise ValueError("policy metadata hash mismatch")
    payload["artifact_id"]=identity
    if payload["schema"]!=SCHEMA or payload["algorithm"]!="ppo": raise ValueError("unsupported policy schema")
    if payload["normalization"]!={"kind":"identity", "observation_dtype":"float32"}: raise ValueError("unsupported normalization")
    symbols=payload["symbols"]; names=payload["feature_names"]
    if not symbols or len(set(symbols))!=len(symbols) or "CASH" in symbols or not names or len(set(names))!=len(names): raise ValueError("invalid policy axes")
    if payload["action_axis"]!=[*symbols,"CASH"]: raise ValueError("action axes mismatch")
    probability=float(payload["score"]["dsr_probability"])
    if not math.isfinite(probability) or not 0<=probability<=1: raise ValueError("invalid policy score")
    binary=path.parent/payload["model_binary"]
    if binary.resolve().parent!=path.parent.resolve(): raise ValueError("invalid binary path")
    if hashlib.sha256(binary.read_bytes()).hexdigest()!=payload["model_sha256"]: raise ValueError("policy binary hash mismatch")
    model=_load_ppo(binary)
    if hasattr(model,"observation_space") and model.observation_space.shape!=(len(symbols)*len(names)+2*len(symbols)+1,): raise ValueError("binary observation axes mismatch")
    if hasattr(model,"action_space") and model.action_space.shape!=(len(symbols)+1,): raise ValueError("binary action axes mismatch")
    return PPOPolicy(model,payload)
