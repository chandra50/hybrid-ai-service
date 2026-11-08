import unittest
from datetime import timedelta

from hybrid_ai import contracts as c
from hybrid_ai.sim import catalog as cat
from hybrid_ai.sim.fleet import SIM_EPOCH, generate_fleet, haversine_km
from hybrid_ai.sim.network import SCENARIOS, WAN_LINKS, Link, Mode, NetworkSim, Scenario, Segment
import tempfile
from pathlib import Path

from hybrid_ai.sim.telemetry import (
    export_telemetry_files, fault_progress, live_telemetry, read_telemetry_file)

FLEET = generate_fleet(seed=42)


class FleetGeneration(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(generate_fleet(seed=42).to_dict(), FLEET.to_dict())
        self.assertNotEqual(generate_fleet(seed=7).to_dict(), FLEET.to_dict())

    def test_ids_match_contract_patterns(self):
        for a in FLEET.assets:
            c.validate_input("diagnose_issue", {"asset_id": a.asset_id})
        for t in FLEET.technicians:
            c.validate_input("check_parts", {"cause_code": "X", "technician_id": t.technician_id})
        for w in FLEET.work_orders:
            c.validate_input("update_work_order", {
                "work_order_id": w.work_order_id, "patch": {"status": "triaged"}, "idempotency_key": "test-0001"})
        c.validate_input("check_parts", {"part_numbers": sorted(cat.all_parts())})

    def test_locations_inside_california_bounds(self):
        for s in FLEET.sites:
            c.validate_input("check_parts", {"cause_code": "X", "near": {"lat": s.location.lat, "lon": s.location.lon}})

    def test_referential_integrity(self):
        site_ids = {s.site_id for s in FLEET.sites}
        depot_ids = {d.depot_id for d in FLEET.depots}
        tech_ids = {t.technician_id for t in FLEET.technicians}
        asset_ids = {a.asset_id for a in FLEET.assets}
        parts = cat.all_parts()
        self.assertTrue(all(s.depot_id in depot_ids for s in FLEET.sites))
        self.assertTrue(all(a.site_id in site_ids for a in FLEET.assets))
        self.assertTrue(all(t.home_depot in depot_ids for t in FLEET.technicians))
        for r in FLEET.repair_history:
            self.assertIn(r.asset_id, asset_ids)
            self.assertIn(r.technician_id, tech_ids)
            self.assertTrue(all(p["part_number"] in parts for p in r.parts_used))
        for loc, items in FLEET.stock.items():
            self.assertTrue(set(items) <= set(parts), loc)

    def test_every_van_and_depot_has_stock_entry(self):
        for t in FLEET.technicians:
            self.assertIn(t.van_id, FLEET.stock)
        for d in FLEET.depots:
            self.assertIn(d.depot_id, FLEET.stock)

    def test_fleet_is_all_compressors(self):
        self.assertTrue(all(a.model.startswith("CMP-") and "compressor" in a.category for a in FLEET.assets))
        self.assertGreaterEqual(len({a.model for a in FLEET.assets}), 3)

    def test_hv_certified_techs_are_electricians(self):
        for t in FLEET.technicians:
            if "hv_certified" in t.skills:
                self.assertIn("electrical", t.skills)

    def test_some_coverage_gaps_exist(self):
        self.assertTrue({"patchy", "none"} & {s.coverage for s in FLEET.sites})

    def test_faults_and_work_orders(self):
        self.assertGreater(len(FLEET.active_faults), 0)
        for wo in FLEET.work_orders:
            self.assertIn(wo.asset_id, FLEET.active_faults)  # every WO has a real cause
        # some faults are silent (no WO) - telemetry-only detection is needed
        self.assertLess(len(FLEET.work_orders), len(FLEET.active_faults))

    def test_manuals_cover_every_failure_mode(self):
        text = "\n".join(m.text for m in FLEET.manuals)
        for m in cat.MODELS:
            for fm in m.failure_modes:
                self.assertIn(fm.code, text)
        self.assertTrue(any("lockout" in m.title.lower() for m in FLEET.manuals))

    def test_demo_scale_under_50(self):
        for name, items in (("sites", FLEET.sites), ("assets", FLEET.assets), ("technicians", FLEET.technicians),
                            ("depots", FLEET.depots)):
            self.assertLess(len(items), 50, name)
        self.assertGreaterEqual(len(FLEET.active_faults), 3)
        self.assertTrue(any(d.has_workshop for d in FLEET.depots))
        self.assertTrue(all(d.has_edge_server for d in FLEET.depots))

    def test_haversine_sacramento_fresno(self):
        sac, fat = FLEET.depot("DEP-SAC").location, FLEET.depot("DEP-FAT").location
        self.assertAlmostEqual(haversine_km(sac, fat), 250, delta=15)


class Telemetry(unittest.TestCase):
    def setUp(self):
        self.faulty = next(iter(FLEET.active_faults))
        self.healthy = next(a.asset_id for a in FLEET.assets if a.asset_id not in FLEET.active_faults)

    def test_matches_contract(self):
        at = SIM_EPOCH + timedelta(hours=10)
        result = live_telemetry(FLEET, self.faulty, at, window_min=15)
        env = c.envelope(result, source_tier="edge", as_of=at, now=at)
        c.validate_response("get_live_telemetry", env)
        self.assertEqual(len(result["series"][0]["points"]), 16)

    def test_deterministic(self):
        at = SIM_EPOCH + timedelta(hours=3)
        self.assertEqual(live_telemetry(FLEET, self.faulty, at), live_telemetry(FLEET, self.faulty, at))

    def test_healthy_asset_has_no_alarms(self):
        at = SIM_EPOCH + timedelta(days=5)
        self.assertEqual(live_telemetry(FLEET, self.healthy, at)["alarms"], [])
        self.assertEqual(fault_progress(FLEET, self.healthy, at), 0.0)

    def test_signal_filter(self):
        result = live_telemetry(FLEET, self.healthy, SIM_EPOCH, window_min=5,
                                signals=[cat.MODELS_BY_NAME[FLEET.asset(self.healthy).model].signals[0].name])
        self.assertEqual(len(result["series"]), 1)

    def test_fully_developed_faults_raise_alarms(self):
        """Faults that push a signal past its warn limit must be visible as alarms."""
        late = SIM_EPOCH + timedelta(days=30)
        alarmed = 0
        for aid, f in FLEET.active_faults.items():
            self.assertEqual(fault_progress(FLEET, aid, late), 1.0)
            if live_telemetry(FLEET, aid, late, window_min=10)["alarms"]:
                alarmed += 1
        self.assertGreater(alarmed, len(FLEET.active_faults) // 2)

    def test_file_round_trip_matches_live(self):
        with tempfile.TemporaryDirectory() as d:
            paths = export_telemetry_files(FLEET, d, SIM_EPOCH, hours=2)
            self.assertEqual(len(paths), len(FLEET.assets))
            at = SIM_EPOCH + timedelta(hours=1, minutes=30)
            from_file = read_telemetry_file(Path(d) / f"{self.faulty}.jsonl", at, window_min=20)
            live = live_telemetry(FLEET, self.faulty, at, window_min=20)
            self.assertEqual(from_file["series"], live["series"])
            c.validate_response("get_live_telemetry",
                                c.envelope(from_file, source_tier="edge", as_of=at, now=at))
            only = read_telemetry_file(paths[0], at, window_min=5, signals=[from_file["series"][0]["signal"]])
            self.assertEqual(len(only["series"]), 1)

    def test_motor_insulation_fault_detectable(self):
        model, fm = cat.failure_mode("CEN-MTR-INS")
        cur = next(s for s in model.signals if s.name == "motor_current")
        self.assertGreater(cur.baseline * (1 + fm.effects["motor_current"]), cur.warn)

    def test_every_part_has_a_price(self):
        self.assertEqual(set(cat.PART_PRICES), set(cat.all_parts()))


class Network(unittest.TestCase):
    def test_exactly_three_modes(self):
        self.assertEqual([m.value for m in Mode], ["ONLINE", "LIMITED", "OFFLINE"])

    def test_every_mode_has_every_link(self):
        from hybrid_ai.sim.network import PROFILES
        for mode in Mode:
            self.assertEqual(set(PROFILES[mode]), set(Link), mode)

    def test_scenarios_well_formed(self):
        for s in SCENARIOS.values():
            self.assertEqual(s.segments[0].start_s, 0, s.name)
            starts = [seg.start_s for seg in s.segments]
            self.assertEqual(starts, sorted(starts), s.name)
            self.assertLess(starts[-1], s.duration_s, s.name)

    def test_scenarios_cover_all_modes_and_events(self):
        segs = [seg for s in SCENARIOS.values() for seg in s.segments]
        self.assertEqual({seg.mode for seg in segs}, set(Mode))
        self.assertTrue(any(seg.sensors_lost for seg in segs))
        self.assertTrue(any(seg.cloud_ai_down for seg in segs))

    def _sim(self, mode, sensors_lost=False, cloud_ai_down=False, seed=1):
        return NetworkSim(Scenario("t", "", (Segment(0, mode, sensors_lost, cloud_ai_down),), 3600), seed=seed)

    def test_online_everything_delivers(self):
        sim = self._sim(Mode.ONLINE)
        for link in Link:
            self.assertTrue(sim.transmit(link, 2000, 10).ok, link)

    def test_limited_is_slow_and_flaky(self):
        sim = self._sim(Mode.LIMITED, seed=3)
        states = {sim.link_up(Link.DEVICE_CLOUD, t) for t in range(0, 3600, 10)}
        self.assertEqual(states, {True, False})
        self.assertTrue(sim.link_up(Link.DEVICE_EDGE, 100))
        t_up = next(t for t in range(0, 3600, 5) if sim.link_up(Link.DEVICE_CLOUD, t))
        big = sim.transmit(Link.DEVICE_CLOUD, 5_000_000, t_up, deadline_ms=60_000)  # 5 MB photo
        self.assertEqual(big.reason, "timeout")

    def test_offline_only_local_link(self):
        sim = self._sim(Mode.OFFLINE)
        up = {link for link in Link if link is not Link.CLOUD_AI and sim.link_up(link, 5)}
        self.assertEqual(up, {Link.DEVICE_EDGE})
        for link in WAN_LINKS:
            self.assertEqual(sim.transmit(link, 100, 5).reason, "link_down")

    def test_cloud_ai_down_event(self):
        sim = self._sim(Mode.ONLINE, cloud_ai_down=True)
        self.assertEqual(sim.transmit(Link.CLOUD_AI, 100, 5).reason, "ai_down")
        self.assertTrue(sim.transmit(Link.DEVICE_CLOUD, 100, 5).ok)

    def test_sensors_lost_event_blocks_telemetry_only(self):
        sim = self._sim(Mode.ONLINE, sensors_lost=True)
        self.assertEqual(sim.transmit(Link.DEVICE_EDGE, 100, 5, telemetry=True).reason, "sensors_lost")
        self.assertTrue(sim.transmit(Link.DEVICE_CLOUD, 100, 5).ok)

    def test_deterministic_for_seed(self):
        s = SCENARIOS["remote_site_visit"]
        run = lambda: [NetworkSim(s, seed=9).transmit(Link.DEVICE_CLOUD, 4000, t) for t in range(0, s.duration_s, 600)]
        self.assertEqual(run(), run())

    def test_remote_visit_timeline(self):
        sim = NetworkSim(SCENARIOS["remote_site_visit"], seed=0)
        self.assertEqual(sim.mode_at(0), Mode.ONLINE)
        self.assertEqual(sim.mode_at(4 * 3600), Mode.OFFLINE)
        self.assertEqual(sim.mode_at(7.5 * 3600), Mode.ONLINE)
        with self.assertRaises(ValueError):
            sim.mode_at(99 * 3600)

    def test_psps_has_sensor_loss(self):
        sim = NetworkSim(SCENARIOS["psps_outage"])
        self.assertTrue(sim.sensors_lost_at(10 * 3600))
        self.assertFalse(sim.sensors_lost_at(1 * 3600))


if __name__ == "__main__":
    unittest.main()
