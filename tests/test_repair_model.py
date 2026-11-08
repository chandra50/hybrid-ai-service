import math
import tempfile
import unittest
from pathlib import Path

from hybrid_ai.demo import repair_db
from hybrid_ai.demo.build_data import MODEL_PATH, build
from hybrid_ai.models.repair_model import HEALTHY, RepairModel, history_priors, train
from hybrid_ai.sim import catalog as cat
from hybrid_ai.sim.fleet import generate_fleet

FLEET = generate_fleet(seed=42)
MODEL = train(seed=7, n_per_class=120, repair_history=FLEET.repair_history)


class RepairModelTests(unittest.TestCase):
    def test_accuracy_on_held_out_data(self):
        self.assertGreaterEqual(MODEL.metrics["top1"], 0.85)
        self.assertGreaterEqual(MODEL.metrics["top2"], 0.93)

    def test_one_model_per_compressor_type(self):
        self.assertEqual(set(MODEL.types), {m.model for m in cat.MODELS})
        for m in cat.MODELS:
            self.assertEqual(MODEL.types[m.model].classes, [HEALTHY] + [fm.code for fm in m.failure_modes])

    def test_probabilities_sum_to_one(self):
        out = MODEL.predict("CMP-SCR-75", symptoms=["low oil pressure"])
        self.assertAlmostEqual(sum(r["probability"] for r in out), 1.0, places=2)

    def test_fully_developed_fault_ranks_first(self):
        for m in cat.MODELS:
            for fm in m.failure_modes:
                readings = {s.name: s.baseline * (1 + fm.effects.get(s.name, 0.0)) for s in m.signals}
                out = MODEL.predict(m.model, readings, {}, list(fm.symptoms))
                self.assertEqual(out[0]["cause_code"], fm.code, f"{m.model} {fm.code}")

    def test_symptoms_only_works_when_sensors_are_lost(self):
        out = MODEL.predict("CMP-SCL-15", None, None, ["moisture in air lines", "dew point alarm"])
        self.assertEqual(out[0]["cause_code"], "SCL-DRYER")

    def test_healthy_readings_rank_healthy(self):
        m = cat.MODELS_BY_NAME["CMP-CEN-300"]
        out = MODEL.predict(m.model, {s.name: s.baseline for s in m.signals}, {}, [])
        self.assertEqual(out[0]["cause_code"], HEALTHY)

    def test_priors_follow_repair_history(self):
        pri = history_priors(FLEET.repair_history)
        for m in cat.MODELS:
            self.assertAlmostEqual(sum(pri[m.model].values()), 1.0, places=6)

    def test_save_load_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = MODEL.save(Path(d) / "m.json")
            again = RepairModel.load(path)
            self.assertLess(path.stat().st_size, 50_000)  # small enough for every device
        args = ("CMP-REC-50", {"crankcase_oil_pressure": 1.3}, {}, ["low oil pressure alarm"])
        a, b = MODEL.predict(*args), again.predict(*args)
        self.assertEqual([r["cause_code"] for r in a], [r["cause_code"] for r in b])
        for x, y in zip(a, b):
            self.assertTrue(math.isclose(x["probability"], y["probability"], abs_tol=1e-3))

    def test_committed_model_file_loads(self):
        self.assertTrue(MODEL_PATH.exists(), "run: PYTHONPATH=src python3 -m hybrid_ai.models")
        self.assertGreaterEqual(RepairModel.load(MODEL_PATH).metrics["top1"], 0.85)


class ModelInRecommendations(unittest.TestCase):
    def test_db_records_model_version(self):
        data = build(seed=42)
        conn = repair_db.connect(":memory:")
        repair_db.populate(conn, data)
        plan = repair_db.get_plan(conn, data["work_orders"][0]["work_order_id"])
        self.assertEqual(plan["model_version"], data["repair_model"]["version"])
        self.assertGreater(plan["model_confidence"], 0)
        self.assertIn("model", plan["generated_by"])


if __name__ == "__main__":
    unittest.main()
