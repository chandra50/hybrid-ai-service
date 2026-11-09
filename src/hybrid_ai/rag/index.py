"""Service-manual retrieval (the "R" in RAG).

Chunks every manual section (safety/LOTO, specifications, parts list, one
troubleshooting section per fault) and every past repair note into passages,
then ranks passages with BM25 (lexical, standard library only). The same index
runs in the cloud, at the edge and on the device: each place builds it from its
own copy of the manuals, so retrieval works with no network.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

_WORD = re.compile(r"[a-z0-9][a-z0-9\-/.]*")
STOP = set("""a an and are as at be by for from has have in into is it its of on or that the this to was were will
with when what which who how do does did not no can should i we you your our my me about after before then than
so if""".split())


def tokens(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(text.lower()):
        w = w.strip(".-/")
        if w and w not in STOP:
            out.append(w)
            if "-" in w or "/" in w:  # also index the parts of scl-fan, p-scl-0603, lockout/tagout
                out += [p for p in re.split(r"[-/]", w) if p and p not in STOP]
    return out


@dataclass(frozen=True)
class Passage:
    doc_id: str
    title: str
    model: str | None
    kind: str          # manual | repair
    text: str

    def as_dict(self, score: float | None = None) -> dict[str, Any]:
        d = {"doc_id": self.doc_id, "title": self.title, "model": self.model, "kind": self.kind, "text": self.text}
        if score is not None:
            d["score"] = round(score, 3)
        return d


class ManualIndex:
    def __init__(self, passages: list[Passage], k1: float = 1.4, b: float = 0.75):
        self.passages = passages
        self.k1, self.b = k1, b
        self.tf = [Counter(tokens(p.title + " " + p.text)) for p in passages]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = sum(self.len) / max(1, len(self.len))
        df = Counter(t for c in self.tf for t in c)
        n = len(passages)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    @classmethod
    def from_demo_data(cls, data: dict[str, Any]) -> ManualIndex:
        passages: list[Passage] = []
        for model, sections in data["manuals"].items():
            for m in sections:
                passages.append(Passage(m["doc_id"], m["title"], model, "manual", m["text"]))
        models = {a["asset_id"]: a["model"] for a in data["assets"]}
        for asset_id, repairs in data["history"].items():
            for i, r in enumerate(repairs):
                passages.append(Passage(f"REPAIR-{asset_id}-{i + 1}", f"{r['date']} repair on {asset_id}: {r['cause_code']}",
                                        models.get(asset_id), "repair",
                                        f"{r['notes']} Labor {r['labor_hours']} h. "
                                        + ("Fixed on the first visit." if r["first_time_fix"] else "Needed a return visit.")))
        return cls(passages)

    def search(self, query: str, model: str | None = None, k: int = 5, kinds: tuple[str, ...] = ("manual", "repair")) -> list[dict[str, Any]]:
        q = tokens(query)
        scored = []
        for i, p in enumerate(self.passages):
            if p.kind not in kinds or (model and p.model not in (model, None)):
                continue
            tf, s = self.tf[i], 0.0
            for t in q:
                f = tf.get(t, 0)
                if f:
                    s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
            if s > 0:
                scored.append((s, p))
        scored.sort(key=lambda x: -x[0])
        return [p.as_dict(s) for s, p in scored[:k]]

    def get(self, doc_id: str) -> dict[str, Any] | None:
        return next((p.as_dict() for p in self.passages if p.doc_id == doc_id), None)
