import json
import threading
import unittest
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

from hybrid_ai.demo import repair_db
from hybrid_ai.demo.build_data import build
from hybrid_ai.demo.server import ROOT, Handler

DATA = build(seed=42)


def fresh_db():
    conn = repair_db.connect(":memory:")
    repair_db.populate(conn, DATA)
    return conn


class RepairDb(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_db()
        self.wo = next(w for w in DATA["work_orders"] if w["assigned_technician_id"])

    def test_every_work_order_has_a_plan(self):
        self.assertEqual(len(repair_db.list_plans(self.conn)), len(DATA["work_orders"]))

    def test_plan_structure(self):
        p = repair_db.get_plan(self.conn, self.wo["work_order_id"])
        phases = [s["phase"] for s in p["steps"]]
        self.assertEqual(phases[0], "safety")
        self.assertEqual(phases[-1], "closeout")
        self.assertIn("test", phases)
        self.assertEqual(phases.index("verify"), len(DATA["loto"]))  # LOTO first, then verify
        self.assertEqual(p["causes"][0]["cause_code"], self.wo["diagnosis"]["causes"][0]["cause_code"])
        self.assertTrue(any(r["kind"] == "manual" for r in p["references"]))
        self.assertEqual(len(p["parts"]), len(self.wo["parts"]["lines"]))

    def test_filter_by_technician(self):
        tech = self.wo["assigned_technician_id"]
        plans = repair_db.list_plans(self.conn, tech)
        self.assertTrue(plans and all(p["assigned_technician_id"] == tech for p in plans))

    def test_step_update_is_idempotent(self):
        wo = self.wo["work_order_id"]
        r1 = repair_db.update_step(self.conn, wo, 1, "done", "TEC-0001", "dev-TEC-0001-1")
        r2 = repair_db.update_step(self.conn, wo, 1, "done", "TEC-0001", "dev-TEC-0001-1")
        self.assertTrue(r1["applied"])
        self.assertTrue(r2["duplicate"])
        p = repair_db.get_plan(self.conn, wo)
        self.assertEqual(p["steps"][0]["status"], "done")
        self.assertEqual(p["status"], "in_progress")
        self.assertEqual(p["version"], 2)  # replay did not bump the version again

    def test_bad_updates_rejected(self):
        with self.assertRaises(ValueError):
            repair_db.update_step(self.conn, self.wo["work_order_id"], 1, "exploded", "x", "k1-123456")
        with self.assertRaises(KeyError):
            repair_db.update_step(self.conn, self.wo["work_order_id"], 999, "done", "x", "k2-123456")

    def test_outcome_completes(self):
        wo = self.wo["work_order_id"]
        repair_db.record_outcome(self.conn, wo, self.wo["ground_truth"], "TEC-0001", "ok")
        p = repair_db.get_plan(self.conn, wo)
        self.assertEqual(p["status"], "completed")
        self.assertEqual(p["outcome"]["confirmed_cause"], self.wo["ground_truth"])


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Handler.conn = fresh_db()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "dashboard")))
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def call(self, path, body=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_health_and_list(self):
        code, body = self.call("/api/health")
        self.assertEqual((code, body["ok"]), (200, True))
        code, plans = self.call("/api/recommendations")
        self.assertEqual(len(plans), len(DATA["work_orders"]))

    def test_step_round_trip(self):
        wo = DATA["work_orders"][0]["work_order_id"]
        code, res = self.call(f"/api/recommendations/{wo}/steps/2",
                              {"status": "done", "by": "TEC-0009", "idempotency_key": "api-test-0002"})
        self.assertEqual((code, res["applied"]), (200, True))
        code, plan = self.call(f"/api/recommendations/{wo}")
        self.assertEqual(plan["steps"][1]["status"], "done")

    def test_errors(self):
        self.assertEqual(self.call("/api/recommendations/WO-0000-9999")[0], 404)
        wo = DATA["work_orders"][0]["work_order_id"]
        self.assertEqual(self.call(f"/api/recommendations/{wo}/steps/1", {"status": "done"})[0], 400)

    def test_static_dashboard_served(self):
        with urllib.request.urlopen(self.base + "/index.html") as r:
            self.assertIn(b"hybrid-ai Field Ops", r.read())


if __name__ == "__main__":
    unittest.main()
