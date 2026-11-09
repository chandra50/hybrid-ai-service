import os
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from hybrid_ai.agents.manual_agent import TOOLS, AgentUnavailable, ManualAgent, llm_configured
from hybrid_ai.demo.build_data import build
from hybrid_ai.rag.index import ManualIndex
from hybrid_ai.sim import catalog as cat

DATA = build(seed=42)
INDEX = ManualIndex.from_demo_data(DATA)
WO = next(w for w in DATA["work_orders"] if w["assigned_technician_id"])


class Retrieval(unittest.TestCase):
    def test_every_fault_found_from_its_symptoms(self):
        for m in cat.MODELS:
            for fm in m.failure_modes:
                top = INDEX.search(" ".join(fm.symptoms[:2]), model=m.model, k=3, kinds=("manual",))
                self.assertTrue(any(fm.code in h["text"] for h in top), f"{m.model} {fm.code}")

    def test_model_filter_and_lookup(self):
        hits = INDEX.search("lockout tagout", model="CMP-CEN-300", k=3, kinds=("manual",))
        self.assertTrue(hits and all(h["model"] == "CMP-CEN-300" for h in hits))
        self.assertEqual(INDEX.get(hits[0]["doc_id"])["doc_id"], hits[0]["doc_id"])


class FakeClient:
    """Plays back scripted Claude responses and records the requests."""

    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})   # snapshot: the loop keeps appending
        return self.responses.pop(0)


def tool_use(id_, name, input_):
    return NS(type="tool_use", id=id_, name=name, input=input_)


def reply(blocks, stop):
    return NS(content=blocks, stop_reason=stop, model="claude-opus-5-5",
              usage=NS(input_tokens=1200, output_tokens=150, cache_read_input_tokens=0))


class AgentLoop(unittest.TestCase):
    def test_tool_loop_and_citations(self):
        trouble = next(h for h in INDEX.search(WO["diagnosis"]["causes"][0]["cause_code"], k=5, kinds=("manual",))
                       if WO["diagnosis"]["causes"][0]["cause_code"] in h["text"])
        client = FakeClient([
            reply([tool_use("t1", "get_work_order", {"work_order_id": WO["work_order_id"]}),
                   tool_use("t2", "search_service_manual", {"query": "cooling fan not spinning"})], "tool_use"),
            reply([NS(type="text", text=f"1. Likely cause: fan. 3. Replace the fan motor [{trouble['doc_id']}] [NOT-A-DOC]")], "end_turn"),
        ])
        res = ManualAgent(DATA, INDEX, client=client).recommend(WO["work_order_id"])
        self.assertEqual(res["mode"], "llm")
        self.assertEqual([t["tool"] for t in res["tool_calls"]], ["get_work_order", "search_service_manual"])
        self.assertEqual([c["doc_id"] for c in res["citations"]], [trouble["doc_id"]])   # unknown ids are dropped
        self.assertEqual(res["usage"]["input_tokens"], 2400)
        req = client.requests[0]
        self.assertEqual(req["model"], "claude-opus-5-5")
        self.assertEqual(req["fallbacks"], "default")
        self.assertEqual({t["name"] for t in req["tools"]}, {t["name"] for t in TOOLS})
        second = client.requests[1]["messages"]
        results = second[-1]["content"]
        self.assertEqual([r["tool_use_id"] for r in results], ["t1", "t2"])   # all results in one user turn
        self.assertNotIn("is_error", results[0])

    def test_tool_errors_go_back_to_claude(self):
        client = FakeClient([
            reply([tool_use("t1", "get_repair_history", {"asset_id": "AST-00005"}),
                   tool_use("t2", "search_service_manual", {"query": ""})], "tool_use"),
            reply([NS(type="text", text="done")], "end_turn"),
        ])
        res = ManualAgent(DATA, INDEX, client=client).recommend(WO["work_order_id"])
        results = client.requests[1]["messages"][-1]["content"]
        self.assertTrue(results[1]["is_error"])
        self.assertIn("error", res["tool_calls"][1])

    def test_refusal_becomes_unavailable(self):
        client = FakeClient([reply([], "refusal")])
        with self.assertRaises(AgentUnavailable):
            ManualAgent(DATA, INDEX, client=client).recommend(WO["work_order_id"])


class Fallback(unittest.TestCase):
    def test_no_credentials_falls_back_to_retrieval(self):
        with mock.patch.dict(os.environ, {"HYBRID_LLM": "off"}):
            self.assertFalse(llm_configured()[0])
            res = ManualAgent(DATA, INDEX).answer(WO["work_order_id"])
        self.assertEqual(res["mode"], "retrieval_only")
        self.assertIn("HYBRID_LLM=off", res["reason"])
        self.assertTrue(any(c["doc_id"].startswith("MAN-") for c in res["citations"]))
        self.assertIn(WO["diagnosis"]["causes"][0]["cause_code"], res["answer"])
        self.assertIn("lockout", res["answer"].lower())


if __name__ == "__main__":
    unittest.main()
