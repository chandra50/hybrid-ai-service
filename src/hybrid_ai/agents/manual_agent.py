"""Repair-recommendation agent: RAG over the service manuals, written by Claude.

The agent runs a tool-use loop on Claude Opus 5.5 with three tools:

    search_service_manual  BM25 retrieval over manual sections and past repair notes
    get_work_order         the work order, reported symptoms and the trained model's ranked causes
    get_repair_history     past repairs on this compressor

It must cite the manual passage behind every step ([doc_id]) and may only use part
numbers it has retrieved. When no Claude credentials are configured, the network is
down, or HYBRID_LLM=off, `retrieval_only()` returns the best-matching manual passages
with no LLM, so the technician always gets the procedure.

    PYTHONPATH=src .venv/bin/python -m hybrid_ai.agents.manual_agent WO-2026-0001 ["question"]
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from ..rag.index import ManualIndex

MODEL = os.environ.get("HYBRID_AGENT_MODEL", "claude-opus-5-5")
MAX_TURNS = 8

SYSTEM = """You are the repair-recommendation agent for a fleet of industrial air compressors in California.
A field technician will follow your answer at the compressor, often with no network, so be precise and practical.

How to work:
- Call get_work_order first. It includes the trained repair-recommendation model's ranked causes; treat them as
  evidence, not as the answer.
- Search the service manual for the likely cause, its procedure, the parts, and the lockout/tagout section.
  Search again if the first results don't cover something. Use get_repair_history when past repairs could help.
- Base every recommendation on retrieved passages. Cite the doc_id of the passage behind each step in square
  brackets, e.g. [MAN-CMP-SCL-15-06]. Only use part numbers that appear in retrieved passages or the work order.
- If the manual doesn't cover something, say so instead of guessing.

Answer format (plain text, short):
1. Likely cause - one line, with the model's confidence and the evidence.
2. Safety - lockout/tagout first; any hazard from the work order or manual.
3. Repair steps - numbered, each with a citation.
4. Parts - part number, description, quantity.
5. After the repair - what to check during the test run.
"""

TOOLS = [
    {
        "name": "search_service_manual",
        "description": "Search the compressor service manuals and past repair notes. Returns the best-matching passages with "
                       "their doc_id. Use specific terms: symptoms, fault codes, component names, part numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for"},
                "compressor_model": {"type": "string", "description": "Limit to one model, e.g. CMP-SCL-15"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_work_order",
        "description": "The work order: compressor, site, hazards, reported symptoms, recent alarms, and the trained "
                       "repair-recommendation model's ranked causes with probabilities.",
        "input_schema": {
            "type": "object",
            "properties": {"work_order_id": {"type": "string"}},
            "required": ["work_order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_repair_history",
        "description": "Past repairs on one compressor: date, cause code, labor hours, notes, and whether it was fixed first time.",
        "input_schema": {
            "type": "object",
            "properties": {"asset_id": {"type": "string"}},
            "required": ["asset_id"],
            "additionalProperties": False,
        },
    },
]


class AgentUnavailable(RuntimeError):
    """Claude can't be used right now (no credentials, disabled, network or API error)."""


def llm_configured() -> tuple[bool, str]:
    if os.environ.get("HYBRID_LLM", "").lower() in ("off", "0", "false", "no"):
        return False, "LLM disabled (HYBRID_LLM=off)"
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True, "API key"
    if (Path.home() / ".config" / "anthropic").exists():
        return True, "ant CLI profile"
    return False, "no Claude credentials configured (set ANTHROPIC_API_KEY)"


class ManualAgent:
    def __init__(self, data: dict[str, Any], index: ManualIndex | None = None, client: Any = None):
        self.data = data
        self.index = index or ManualIndex.from_demo_data(data)
        self.client = client   # injected in tests; created lazily otherwise

    # ---------------------------------------------------------------- tools
    def _wo(self, work_order_id: str) -> dict[str, Any]:
        wo = next((w for w in self.data["work_orders"] if w["work_order_id"] == work_order_id), None)
        if wo is None:
            raise KeyError(f"unknown work order {work_order_id}")
        return wo

    def tool_get_work_order(self, work_order_id: str) -> dict[str, Any]:
        wo = self._wo(work_order_id)
        a = next(x for x in self.data["assets"] if x["asset_id"] == wo["asset_id"])
        return {"work_order_id": wo["work_order_id"], "priority": wo["priority"], "title": wo["title"],
                "asset_id": a["asset_id"], "compressor_model": a["model"], "category": a["category"],
                "site": a["site_name"], "hazards": a["hazards"], "reported_symptoms": wo["symptoms"],
                "recent_alarms": [x["message"] for x in self.data["telemetry"][a["asset_id"]]["alarms"][-3:]],
                "model_ranked_causes": wo["diagnosis"]["causes"], "safe_to_run": wo["diagnosis"]["safe_to_run"],
                "planned_parts": [{k: l[k] for k in ("part_number", "description", "qty")} for l in wo["parts"]["lines"]]}

    def tool_search_service_manual(self, query: str, compressor_model: str | None = None) -> list[dict[str, Any]]:
        return self.index.search(query, model=compressor_model, k=5)

    def tool_get_repair_history(self, asset_id: str) -> list[dict[str, Any]]:
        return self.data["history"].get(asset_id, [])[:6]

    def run_tool(self, name: str, args: dict[str, Any]) -> Any:
        if name == "search_service_manual":
            if not isinstance(args.get("query"), str) or not args["query"].strip():
                raise ValueError("query must be a non-empty string")
            return self.tool_search_service_manual(args["query"], args.get("compressor_model"))
        if name == "get_work_order":
            return self.tool_get_work_order(str(args["work_order_id"]))
        if name == "get_repair_history":
            return self.tool_get_repair_history(str(args["asset_id"]))
        raise ValueError(f"unknown tool {name}")

    # ---------------------------------------------------------------- Claude loop
    def recommend(self, work_order_id: str, question: str = "") -> dict[str, Any]:
        self._wo(work_order_id)
        ok, why = llm_configured()
        if self.client is None:
            if not ok:
                raise AgentUnavailable(why)
            import anthropic
            self.client = anthropic.Anthropic(timeout=120.0, max_retries=2)
        import anthropic

        t0 = time.perf_counter()
        prompt = f"Work order {work_order_id}. " + (question.strip() or "What is wrong and how do I repair it?")
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        trace, usage = [], {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
        response = None
        for _ in range(MAX_TURNS):
            try:
                response = self.client.beta.messages.create(
                    model=MODEL, max_tokens=16000, system=SYSTEM, tools=TOOLS, messages=messages,
                    output_config={"effort": "medium"},
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                )
            except anthropic.AuthenticationError as e:
                raise AgentUnavailable(f"Claude rejected the credentials: {e.message}") from e
            except anthropic.APIConnectionError as e:
                raise AgentUnavailable(f"can't reach the Claude API: {e}") from e
            except anthropic.RateLimitError as e:
                raise AgentUnavailable("Claude API rate limit reached") from e
            except anthropic.APIStatusError as e:
                raise AgentUnavailable(f"Claude API error {e.status_code}: {e.message}") from e
            u = response.usage
            usage["input_tokens"] += u.input_tokens or 0
            usage["output_tokens"] += u.output_tokens or 0
            usage["cache_read_input_tokens"] += getattr(u, "cache_read_input_tokens", 0) or 0
            if response.stop_reason == "refusal":
                raise AgentUnavailable("Claude declined this request")
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue
            calls = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not calls:
                break
            results = []
            for b in calls:
                t = time.perf_counter()
                try:
                    out = self.run_tool(b.name, b.input if isinstance(b.input, dict) else json.loads(b.input))
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out)})
                    n = len(out) if isinstance(out, list) else 1
                    trace.append({"tool": b.name, "input": b.input, "results": n, "ms": round((time.perf_counter() - t) * 1000, 1)})
                except Exception as e:  # noqa: BLE001  tool errors go back to Claude, not up the stack
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": f"Error: {e}", "is_error": True})
                    trace.append({"tool": b.name, "input": b.input, "error": str(e)})
            messages.append({"role": "user", "content": results})
        answer = "\n".join(b.text for b in (response.content if response else []) if b.type == "text").strip()
        return {"mode": "llm", "model": getattr(response, "model", MODEL), "answer": answer,
                "citations": self._citations(answer), "tool_calls": trace, "usage": usage,
                "stop_reason": getattr(response, "stop_reason", None), "ms": round((time.perf_counter() - t0) * 1000)}

    def _citations(self, text: str) -> list[dict[str, str]]:
        out = []
        for doc_id in dict.fromkeys(re.findall(r"\[([A-Z][A-Z0-9\-]+)\]", text)):
            p = self.index.get(doc_id)
            if p:
                out.append({"doc_id": doc_id, "title": p["title"]})
        return out

    # ---------------------------------------------------------------- no-LLM fallback
    def retrieval_only(self, work_order_id: str, question: str = "", reason: str = "") -> dict[str, Any]:
        t0 = time.perf_counter()
        wo = self.tool_get_work_order(work_order_id)
        top = wo["model_ranked_causes"][0]
        query = " ".join([top["cause_code"], top["description"], question, *wo["reported_symptoms"]])
        hits = self.index.search(query, model=wo["compressor_model"], k=4)
        trouble = next((h for h in hits if h["kind"] == "manual" and top["cause_code"] in h["text"]), None) \
            or next((h for h in self.index.search(top["cause_code"], model=wo["compressor_model"], k=3, kinds=("manual",))), None)
        loto = next(iter(self.index.search("lockout tagout safety", model=wo["compressor_model"], k=1, kinds=("manual",))), None)
        conf = ">99%" if top["probability"] >= 0.995 else f"{round(top['probability'] * 100)}%"
        lines = [f"Likely cause: {top['description']} ({top['cause_code']}, model confidence {conf})."]
        if loto:
            lines.append(f"Safety: complete lockout/tagout first [{loto['doc_id']}].")
        if trouble:
            proc = trouble["text"].split("Procedure:")[-1].split("Parts:")[0].strip().splitlines()
            lines.append("Steps:")
            lines += [f"  {s.strip()} [{trouble['doc_id']}]" for s in proc if s.strip()]
            if "Parts:" in trouble["text"]:
                lines.append(f"Parts: {trouble['text'].split('Parts:')[-1].strip()} [{trouble['doc_id']}]")
        reps = [h for h in hits if h["kind"] == "repair"][:2]
        if reps:
            lines.append("Similar past repairs: " + "; ".join(f"{h['title']} [{h['doc_id']}]" for h in reps))
        cited = [h for h in [loto, trouble, *reps] if h]
        return {"mode": "retrieval_only", "model": None, "answer": "\n".join(lines),
                "citations": [{"doc_id": h["doc_id"], "title": h["title"]} for h in cited],
                "tool_calls": [{"tool": "search_service_manual", "input": {"query": query}, "results": len(hits)}],
                "usage": {"input_tokens": 0, "output_tokens": 0}, "reason": reason or "no LLM used",
                "ms": round((time.perf_counter() - t0) * 1000, 1)}

    def answer(self, work_order_id: str, question: str = "") -> dict[str, Any]:
        """Claude when available, otherwise retrieval only. Never raises for LLM problems."""
        try:
            return self.recommend(work_order_id, question)
        except AgentUnavailable as e:
            return self.retrieval_only(work_order_id, question, reason=str(e))


def main(argv: list[str] | None = None) -> None:
    from ..demo.build_data import build
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__)
        return
    res = ManualAgent(build(42)).answer(args[0], " ".join(args[1:]))
    print(f"[{res['mode']}{' · ' + res['model'] if res['model'] else ''} · {res['ms']} ms · "
          f"{res['usage']['input_tokens']} in / {res['usage']['output_tokens']} out tokens]")
    if res.get("reason"):
        print(f"(fallback: {res['reason']})")
    print(res["answer"])
    print("\nSources:", ", ".join(c["doc_id"] for c in res["citations"]))
    for t in res["tool_calls"]:
        print("  tool:", t["tool"], json.dumps(t.get("input")), "->", t.get("results", t.get("error")))


if __name__ == "__main__":
    main()
