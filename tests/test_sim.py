import unittest
from datetime import timedelta

from hybrid_ai import contracts as c
from hybrid_ai.sim import catalog as cat
from hybrid_ai.sim.fleet import SIM_EPOCH, generate_fleet, haversine_km
from hybrid_ai.sim.network import SCENARIOS, WAN_LINKS, Link, Mode, NetworkSim, Scenario, Segment
from hybrid_ai.sim.telemetry import fault_progress, live_telemetry

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

    def test_every_truck_and_depot_has_stock_entry(self):
        for t in FLEET.technicians:
            self.assertIn(t.truck_id, FLEET.stock)
        for d in FLEET.depots:
            self.assertIn(d.depot_id, FLEET.stock)

    def test_wind_turbines_only_in_windy_regions(self):
        for a in FLEET.assets:
            if a.model == "WTG-GBX-2M":
                self.assertIn(FLEET.site(a.site_id).region, {"Mojave", "Northern", "Kern"})

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

    def test_bushing_crack_detectable(self):
        model, fm = cat.failure_mode("XFM-BUSH-CRACK")
        gas = next(s for s in model.signals if s.name == "dissolved_gas_ppm")
        self.assertGreater(gas.baseline * (1 + fm.effects["dissolved_gas_ppm"]), gas.warn)


class Network(unittest.TestCase):
    def test_every_mode_has_every_link(self):
        from hybrid_ai.sim.network import PROFILES
        for mode in Mode:
            if mode is Mode.M6_EQUIPMENT_DATA_LOST:
                continue
            self.assertEqual(set(PROFILES[mode]), set(Link), mode)

    def test_scenarios_well_formed(self):
        for s in SCENARIOS.values():
            self.assertEqual(s.segments[0].start_s, 0, s.name)
            starts = [seg.start_s for seg in s.segments]
            self.assertEqual(starts, sorted(starts), s.name)
            self.assertLess(starts[-1], s.duration_s, s.name)

    def test_all_modes_covered_by_scenarios(self):
        modes = {seg.mode for s in SCENARIOS.values() for seg in s.segments}
        self.assertEqual(modes, set(Mode) - {Mode.M6_EQUIPMENT_DATA_LOST})
        self.assertTrue(any(seg.telemetry_lost for s in SCENARIOS.values() for seg in s.segments))

    def _sim(self, mode, telemetry_lost=False, seed=1):
        return NetworkSim(Scenario("t", "", (Segment(0, mode, telemetry_lost),), 3600), seed=seed)

    def test_m0_everything_delivers(self):
        sim = self._sim(Mode.M0_CONNECTED)
        for link in Link:
            self.assertTrue(sim.transmit(link, 2000, 10).ok, link)

    def test_m1_slow_and_size_sensitive(self):
        sim = self._sim(Mode.M1_CONSTRAINED)
        small = sim.transmit(Link.FIELD_CLOUD, 1_000, 10, deadline_ms=60_000)
        big = sim.transmit(Link.FIELD_CLOUD, 5_000_000, 20, deadline_ms=60_000)  # 5 MB photo
        self.assertEqual(big.reason, "timeout")
        if small.ok:
            self.assertGreater(small.latency_ms, 500)

    def test_m2_flaps_both_ways(self):
        sim = self._sim(Mode.M2_INTERMITTENT, seed=3)
        states = {sim.link_up(Link.FIELD_CLOUD, t) for t in range(0, 3600, 10)}
        self.assertEqual(states, {True, False})
        self.assertTrue(sim.link_up(Link.FIELD_EDGE, 100))

    def test_m3_only_llm_down(self):
        sim = self._sim(Mode.M3_CLOUD_AGENTS_DOWN)
        self.assertEqual(sim.transmit(Link.CLOUD_LLM, 100, 5).reason, "link_down")
        self.assertTrue(sim.transmit(Link.FIELD_CLOUD, 100, 5).ok)

    def test_m4_hub_island(self):
        sim = self._sim(Mode.M4_HUB_ISLAND)
        for link in WAN_LINKS:
            self.assertFalse(sim.link_up(link, 5), link)
        self.assertTrue(sim.link_up(Link.FIELD_HUB, 5))

    def test_m5_only_local_link(self):
        sim = self._sim(Mode.M5_OFFLINE)
        up = {link for link in Link if sim.link_up(link, 5)}
        self.assertEqual(up, {Link.FIELD_EDGE})

    def test_m6_overlay_blocks_telemetry_only(self):
        sim = self._sim(Mode.M0_CONNECTED, telemetry_lost=True)
        self.assertEqual(sim.transmit(Link.FIELD_EDGE, 100, 5, telemetry=True).reason, "telemetry_lost")
        self.assertTrue(sim.transmit(Link.FIELD_CLOUD, 100, 5).ok)

    def test_deterministic_for_seed(self):
        s = SCENARIOS["remote_site_visit"]
        run = lambda: [NetworkSim(s, seed=9).transmit(Link.FIELD_CLOUD, 4000, t) for t in range(0, s.duration_s, 600)]
        self.assertEqual(run(), run())

    def test_remote_visit_timeline(self):
        sim = NetworkSim(SCENARIOS["remote_site_visit"], seed=0)
        self.assertEqual(sim.mode_at(0), Mode.M0_CONNECTED)
        self.assertEqual(sim.mode_at(4 * 3600), Mode.M5_OFFLINE)
        self.assertEqual(sim.mode_at(7.5 * 3600), Mode.M0_CONNECTED)
        with self.assertRaises(ValueError):
            sim.mode_at(99 * 3600)

    def test_psps_has_sensor_loss(self):
        sim = NetworkSim(SCENARIOS["psps_outage"])
        self.assertTrue(sim.telemetry_lost_at(10 * 3600))
        self.assertFalse(sim.telemetry_lost_at(1 * 3600))


if __name__ == "__main__":
    unittest.main()
