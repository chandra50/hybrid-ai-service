"""Repair recommendation model.

A small multinomial logistic-regression model per compressor type that ranks
likely causes (failure modes, plus "healthy") from:

  - telemetry features: each signal's relative deviation from its baseline,
    and its recent trend
  - reported symptoms (bag of words over the type's symptom vocabulary)
  - class priors from the fleet's repair history

It is trained in the cloud on simulator data and exported as a small JSON file
(the "model card" + weights) that runs unchanged in the cloud, on the edge and on
the technician's device: pure arithmetic, no tokens, milliseconds per call.
When live data is missing (sensors lost) it still works from symptoms alone.

Standard library only, so it runs anywhere Python does; the dashboard has a
JavaScript port of ``predict``.
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..sim import catalog as cat

HEALTHY = "HEALTHY"
VERSION = "repair-rec-1.0"


# ---------------------------------------------------------------- features
def feature_names(model: cat.AssetModel) -> list[str]:
    names = []
    for s in model.signals:
        names += [f"dev:{s.name}", f"trend:{s.name}"]
    names += [f"sym:{x}" for x in symptom_vocab(model)]
    names += ["has_telemetry"]
    return names


def symptom_vocab(model: cat.AssetModel) -> list[str]:
    seen: list[str] = []
    for fm in model.failure_modes:
        for s in fm.symptoms:
            if s not in seen:
                seen.append(s)
    return seen


def featurize(model: cat.AssetModel, readings: dict[str, float] | None, trends: dict[str, float] | None,
              symptoms: list[str]) -> list[float]:
    """readings: latest value per signal; trends: relative change over the window (None if unknown)."""
    x: list[float] = []
    for s in model.signals:
        if readings and s.name in readings:
            x.append((readings[s.name] - s.baseline) / s.baseline)
            x.append((trends or {}).get(s.name, 0.0))
        else:
            x += [0.0, 0.0]
    vocab = symptom_vocab(model)
    sym = set(symptoms)
    x += [1.0 if v in sym else 0.0 for v in vocab]
    x.append(1.0 if readings else 0.0)
    return x


# ---------------------------------------------------------------- synthetic training data
def _sample(model: cat.AssetModel, fm: cat.FailureMode | None, rng: random.Random,
            drop_telemetry: float = 0.15, report_rate: float = 0.55) -> tuple[list[float], str]:
    progress = 0.0 if fm is None else rng.uniform(0.2, 1.0)
    readings, trends = {}, {}
    for s in model.signals:
        eff = fm.effects.get(s.name, 0.0) if fm else 0.0
        noise = rng.gauss(0, s.noise)
        readings[s.name] = s.baseline * (1 + eff * progress) + noise
        # trend over the last few hours: faults still developing drift upward in magnitude
        trends[s.name] = eff * min(progress, 0.35) * rng.uniform(0.3, 1.0) + rng.gauss(0, 0.01)
    vocab = symptom_vocab(model)
    symptoms = []
    if fm:
        symptoms = [x for x in fm.symptoms if rng.random() < report_rate]
    symptoms += [v for v in vocab if v not in symptoms and rng.random() < 0.04]  # confusing noise
    if rng.random() < drop_telemetry:
        readings, trends = None, None
    return featurize(model, readings, trends, symptoms), (fm.code if fm else HEALTHY)


def make_dataset(model: cat.AssetModel, n_per_class: int, seed: int) -> list[tuple[list[float], str]]:
    rng = random.Random(f"{seed}:{model.model}")
    data = []
    for fm in [None, *model.failure_modes]:
        data += [_sample(model, fm, rng) for _ in range(n_per_class)]
    rng.shuffle(data)
    return data


# ---------------------------------------------------------------- softmax regression
def _softmax(z: list[float]) -> list[float]:
    m = max(z)
    e = [math.exp(v - m) for v in z]
    t = sum(e)
    return [v / t for v in e]


@dataclass
class TypeModel:
    asset_model: str
    classes: list[str]
    features: list[str]
    mean: list[float]
    std: list[float]
    weights: list[list[float]]   # [class][feature]
    bias: list[float]
    log_prior: list[float]

    def scores(self, x: list[float]) -> list[float]:
        xs = [(v - m) / s for v, m, s in zip(x, self.mean, self.std)]
        z = [b + lp + sum(w * v for w, v in zip(ws, xs)) for ws, b, lp in zip(self.weights, self.bias, self.log_prior)]
        return _softmax(z)

    def to_dict(self) -> dict[str, Any]:
        r = lambda v: [round(a, 5) for a in v]  # noqa: E731
        return {"classes": self.classes, "features": self.features, "mean": r(self.mean), "std": r(self.std),
                "weights": [r(w) for w in self.weights], "bias": r(self.bias), "log_prior": r(self.log_prior)}


def train_type(model: cat.AssetModel, data: list[tuple[list[float], str]], priors: dict[str, float],
               epochs: int = 60, lr: float = 0.3, l2: float = 1e-3) -> TypeModel:
    classes = [HEALTHY] + [fm.code for fm in model.failure_modes]
    feats = feature_names(model)
    d = len(feats)
    cols = list(zip(*[x for x, _ in data]))
    mean = [sum(c) / len(c) for c in cols]
    std = [max(1e-6, math.sqrt(sum((v - m) ** 2 for v in c) / len(c))) for c, m in zip(cols, mean)]
    X = [[(v - m) / s for v, m, s in zip(x, mean, std)] for x, _ in data]
    Y = [classes.index(y) for _, y in data]
    W = [[0.0] * d for _ in classes]
    b = [0.0] * len(classes)
    n = len(X)
    for _ in range(epochs):
        gW = [[0.0] * d for _ in classes]
        gb = [0.0] * len(classes)
        for x, y in zip(X, Y):
            p = _softmax([bk + sum(w * v for w, v in zip(Wk, x)) for Wk, bk in zip(W, b)])
            for k in range(len(classes)):
                g = p[k] - (1.0 if k == y else 0.0)
                gb[k] += g
                row = gW[k]
                for j in range(d):
                    row[j] += g * x[j]
        for k in range(len(classes)):
            b[k] -= lr * gb[k] / n
            for j in range(d):
                W[k][j] -= lr * (gW[k][j] / n + l2 * W[k][j])
    # Training data is class-balanced; real-world priors come from repair history.
    log_prior = [math.log(priors.get(c, 1e-3)) - math.log(1 / len(classes)) for c in classes]
    return TypeModel(model.model, classes, feats, mean, std, W, b, log_prior)


# ---------------------------------------------------------------- whole model
@dataclass
class RepairModel:
    version: str
    types: dict[str, TypeModel]
    metrics: dict[str, Any]

    def predict(self, asset_model: str, readings: dict[str, float] | None = None,
                trends: dict[str, float] | None = None, symptoms: list[str] | None = None) -> list[dict[str, Any]]:
        tm = self.types[asset_model]
        x = featurize(cat.MODELS_BY_NAME[asset_model], readings, trends, symptoms or [])
        probs = tm.scores(x)
        ranked = sorted(zip(tm.classes, probs), key=lambda t: -t[1])
        out = []
        for code, p in ranked:
            desc = "No fault (healthy)" if code == HEALTHY else cat.failure_mode(code)[1].description
            out.append({"cause_code": code, "description": desc, "probability": round(p, 3)})
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "kind": "multinomial logistic regression, one per compressor type",
                "inputs": ["signal deviation from baseline", "signal trend", "reported symptoms", "history priors"],
                "metrics": self.metrics, "types": {k: v.to_dict() for k, v in self.types.items()}}

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), separators=(",", ":")), encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: str | Path) -> RepairModel:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        types = {k: TypeModel(asset_model=k, **v) for k, v in d["types"].items()}
        return cls(d["version"], types, d.get("metrics", {}))


def history_priors(repair_history: list[Any] | None) -> dict[str, dict[str, float]]:
    """Per compressor type: how often each cause appeared in past repairs (Laplace smoothed), plus 'healthy'."""
    out: dict[str, dict[str, float]] = {}
    for m in cat.MODELS:
        counts = Counter(r.cause_code for r in (repair_history or []) if r.model == m.model)
        codes = [fm.code for fm in m.failure_modes]
        total = sum(counts[c] + 1 for c in codes)
        # most alarms that reach the model are real faults; keep 'healthy' at 15%
        out[m.model] = {HEALTHY: 0.15, **{c: 0.85 * (counts[c] + 1) / total for c in codes}}
    return out


def _evaluate(tm: TypeModel, data: list[tuple[list[float], str]]) -> tuple[float, float]:
    top1 = top2 = 0
    for x, y in data:
        p = tm.scores(x)
        order = sorted(range(len(p)), key=lambda k: -p[k])
        top1 += tm.classes[order[0]] == y
        top2 += y in (tm.classes[order[0]], tm.classes[order[1]])
    return top1 / len(data), top2 / len(data)


def train(seed: int = 42, n_per_class: int = 220, repair_history: list[Any] | None = None) -> RepairModel:
    priors = history_priors(repair_history)
    types, metrics = {}, {"per_type": {}}
    t1 = t2 = n = 0
    for m in cat.MODELS:
        train_data = make_dataset(m, n_per_class, seed)
        test_data = make_dataset(m, n_per_class // 3, seed + 1000)
        flat = {c: 1 / (len(m.failure_modes) + 1) for c in [HEALTHY] + [fm.code for fm in m.failure_modes]}
        tm = train_type(m, train_data, flat)
        a1, a2 = _evaluate(tm, test_data)       # held-out, balanced classes
        tm.log_prior = [math.log(priors[m.model].get(c, 1e-3)) - math.log(flat[c]) for c in tm.classes]
        types[m.model] = tm
        metrics["per_type"][m.model] = {"top1": round(a1, 3), "top2": round(a2, 3), "test_samples": len(test_data)}
        t1 += a1 * len(test_data); t2 += a2 * len(test_data); n += len(test_data)
    metrics["top1"] = round(t1 / n, 3)
    metrics["top2"] = round(t2 / n, 3)
    metrics["trained_on"] = f"simulated telemetry + symptoms, {n_per_class} samples per class; priors from {len(repair_history or [])} past repairs"
    return RepairModel(VERSION, types, metrics)
