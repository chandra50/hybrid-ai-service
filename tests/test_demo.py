import unittest

from hybrid_ai import contracts as c
from hybrid_ai.demo.build_data import NOW, build

DATA = build(seed=42)


class DemoData(unittest.TestCase):
    def test_counts_under_50(self):
        for key in ("assets", "technicians", "depots"):
            self.assertLess(len(DATA[key]), 50, key)
        self.assertGreater(len(DATA["work_orders"]), 0)

    def test_assets_inside_california_box(self):
        for a in DATA["assets"]:
            self.assertTrue(32.0 <= a["lat"] <= 42.5 and -125 <= a["lon"] <= -114, a["asset_id"])

    def test_every_work_order_has_a_full_plan(self):
        for w in DATA["work_orders"]:
            for key in ("diagnosis", "technicians", "location", "parts", "approvals"):
                self.assertIn(key, w)
            self.assertAlmostEqual(sum(x["probability"] for x in w["diagnosis"]["causes"]), 1.0, delta=0.05)
            self.assertIn(w["status"], ("assigned", "awaiting_approval"))

    def test_plans_match_contracts(self):
        for w in DATA["work_orders"]:
            d = w["diagnosis"]
            diag = {"asset_id": w["asset_id"], "severity": d["severity"], "safe_to_run": d["safe_to_run"],
                    "safety_override": d["safety_override"], "evidence": d["evidence"],
                    "causes": [{k: x[k] for k in ("cause_code", "description", "probability")} for x in d["causes"]]}
            c.validate_response("diagnose_issue", c.envelope(diag, source_tier="cloud", as_of=NOW, now=NOW))
            c.validate_response("find_technicians", c.envelope({"candidates": w["technicians"]},
                                                               source_tier="cloud", as_of=NOW, now=NOW))
            loc = {k: v for k, v in w["location"].items() if k != "note"}
            c.validate_response("recommend_repair_location", c.envelope(loc, source_tier="edge", as_of=NOW, now=NOW))

    def test_approval_rules(self):
        for w in DATA["work_orders"]:
            actions = {a["action"]: a for a in w["approvals"]}
            if w["location"]["location"] == "workshop":
                self.assertEqual(actions["Workshop"]["outcome"], "human")
            if w["parts"]["total_usd"] >= 1000:
                self.assertIn(actions["Parts"]["outcome"], ("human", "approved"))
            if w["priority"] in ("urgent", "emergency"):
                self.assertIn(actions["Dispatch"]["outcome"], ("human", "approved"))

    def test_technician_persona_has_a_job(self):
        self.assertTrue(any(w["assigned_technician_id"] for w in DATA["work_orders"]))

    def test_assets_with_work_orders_are_flagged(self):
        flagged = {a["asset_id"] for a in DATA["assets"] if a["status"] != "healthy"}
        for w in DATA["work_orders"]:
            self.assertIn(w["asset_id"], flagged)

    def test_scenarios_exported(self):
        names = {s["name"] for s in DATA["scenarios"]}
        self.assertIn("remote_site_visit", names)
        self.assertIn("psps_outage", names)


if __name__ == "__main__":
    unittest.main()
