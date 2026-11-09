"""Integration test for the live demo: real processes, real network faults.

Needs the MCP SDK (run with the project venv):
    PYTHONPATH=src .venv/bin/python -m unittest tests.test_live -v
Skipped automatically when the SDK isn't installed.
"""

import importlib.util
import json
import os
import tempfile
import time
import unittest
import urllib.request

HAVE_MCP = importlib.util.find_spec("mcp") is not None


def _req(base, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"http://127.0.0.1:{base + 3}{path}", data=data, method="POST" if data else "GET",
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read())


@unittest.skipUnless(HAVE_MCP, "MCP SDK not installed (use .venv/bin/python)")
class LiveStack(unittest.TestCase):
    BASE = 9100

    @classmethod
    def setUpClass(cls):
        from hybrid_ai.live.__main__ import start, wait_ready
        cls.tmp = tempfile.TemporaryDirectory()
        cls.procs = start({"HYBRID_PORT_BASE": str(cls.BASE), "HYBRID_LIVE_DIR": cls.tmp.name})
        if not wait_ready(cls.BASE + 3, timeout=90):
            cls.tearDownClass()
            raise RuntimeError("live stack did not start")

    @classmethod
    def tearDownClass(cls):
        from hybrid_ai.live.__main__ import stop
        stop(cls.procs)
        cls.tmp.cleanup()

    def state(self):
        return _req(self.BASE, "/api/state")

    def call(self, tool, **args):
        return _req(self.BASE, "/api/call", {"tool": tool, "args": args})

    def net(self, **body):
        return _req(self.BASE, "/api/net", body)

    def wait_mode(self, mode, timeout=30):
        t = time.time()
        while time.time() - t < timeout:
            if self.state()["detected"]["mode"] == mode:
                return
            time.sleep(0.5)
        self.fail(f"device never detected {mode}: {self.state()['detected']}")

    def wait_until(self, check, timeout=30, msg=""):
        t = time.time()
        while time.time() - t < timeout:
            if check():
                return
            time.sleep(0.5)
        self.fail(msg)

    def test_full_story(self):
        # Online: cloud answers, mission pack arrives
        self.wait_mode("ONLINE")
        self.wait_until(lambda: self.state()["device"]["mission_pack"], msg="mission pack never synced")
        self.assertEqual(self.call("diagnose_issue")["place"], "cloud")
        self.assertEqual(self.call("get_live_telemetry")["place"], "edge")

        # Offline: WAN cut; edge and device carry on; writes queue
        self.net(mode="OFFLINE")
        self.wait_mode("OFFLINE")
        self.assertEqual(self.call("diagnose_issue")["place"], "edge")
        self.assertEqual(self.call("find_technicians")["status"], "failed")
        plan = self.call("get_repair_plan")
        self.assertEqual(plan["place"], "device")
        step = self.call("update_step", seq=1, status="done", by="TEC-TEST", phase="safety")
        self.assertEqual(step["status"], "queued")
        key = step["result"]["idempotency_key"]

        # Sensors lost: the edge goes dark, the device copy of the model answers from symptoms
        self.net(sensors_lost=True)
        self.wait_until(lambda: not self.state()["detected"]["edge_ok"], msg="edge never went dark")
        d = self.call("diagnose_issue", symptoms=["fan not spinning"])
        self.assertEqual(d["place"], "device")
        self.assertEqual(d["result"]["inputs"], "symptoms only (no live data)")
        self.assertEqual(self.call("get_live_telemetry")["status"], "failed")

        # Back online: outbox replays to the cloud DB exactly once
        self.net(mode="ONLINE", sensors_lost=False)
        self.wait_mode("ONLINE")
        self.wait_until(lambda: all(o["status"] == "synced" for o in self.state()["device"]["outbox"]),
                        msg="outbox never drained")
        self.assertGreaterEqual(self.state()["cloud"]["steps_done"], 1)
        again = self.call("update_step", seq=1, status="done", by="TEC-TEST", idempotency_key=key)
        self.assertEqual(again["place"], "cloud")
        self.assertTrue(again["result"]["duplicate"])

    def test_cloud_ai_outage_moves_explain_to_edge(self):
        self.wait_mode("ONLINE")
        self.net(cloud_ai_down=True)
        try:
            e = self.call("explain", question="q", facts="f")
            self.assertEqual(e["place"], "edge")
            self.assertFalse(e["attempts"][0]["ok"])
            self.assertEqual(self.call("diagnose_issue")["place"], "cloud")   # not an LLM: unaffected
        finally:
            self.net(cloud_ai_down=False)


if __name__ == "__main__":
    unittest.main()
