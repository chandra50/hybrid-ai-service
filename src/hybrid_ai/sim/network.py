"""Network fault injector for the hybrid operating modes (DESIGN.md section 5).

A ``Scenario`` is a timeline of segments, each with a base mode (M0-M5) and an
optional equipment-data-loss flag (M6 can overlap any mode). ``NetworkSim``
answers "what happens if I send N bytes over link L at time t?" deterministically
for a given seed, so later phases (router, outbox, agents) can be tested
against exactly reproducible outages.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum


class Mode(str, Enum):
    M0_CONNECTED = "M0"
    M1_CONSTRAINED = "M1"
    M2_INTERMITTENT = "M2"
    M3_CLOUD_AGENTS_DOWN = "M3"
    M4_HUB_ISLAND = "M4"
    M5_OFFLINE = "M5"
    M6_EQUIPMENT_DATA_LOST = "M6"  # flag-style; see Segment.telemetry_lost


class Link(str, Enum):
    FIELD_CLOUD = "field->cloud"
    FIELD_HUB = "field->hub"
    HUB_CLOUD = "hub->cloud"
    EDGE_CLOUD = "edge->cloud"
    FIELD_EDGE = "field->edge"  # local site Wi-Fi/BLE, never needs the WAN
    CLOUD_LLM = "cloud->llm"    # the cloud model API itself


WAN_LINKS = {Link.FIELD_CLOUD, Link.HUB_CLOUD, Link.EDGE_CLOUD}


@dataclass(frozen=True)
class LinkProfile:
    up: bool
    bandwidth_kbps: float = 0.0
    rtt_ms: float = 0.0
    loss: float = 0.0               # per-message loss probability
    flap_up_s: tuple[int, int] = (0, 0)    # if set, link alternates up/down windows
    flap_down_s: tuple[int, int] = (0, 0)


_LOCAL = LinkProfile(True, 20_000, 15)
_DOWN = LinkProfile(False)
_GOOD_WAN = LinkProfile(True, 10_000, 80)

PROFILES: dict[Mode, dict[Link, LinkProfile]] = {
    Mode.M0_CONNECTED: {
        Link.FIELD_CLOUD: _GOOD_WAN, Link.FIELD_HUB: _GOOD_WAN, Link.HUB_CLOUD: LinkProfile(True, 100_000, 30),
        Link.EDGE_CLOUD: _GOOD_WAN, Link.FIELD_EDGE: _LOCAL, Link.CLOUD_LLM: LinkProfile(True, 100_000, 50),
    },
    Mode.M1_CONSTRAINED: {  # e.g. one bar of LTE or satellite backup
        Link.FIELD_CLOUD: LinkProfile(True, 128, 900, 0.02), Link.FIELD_HUB: LinkProfile(True, 128, 700, 0.02),
        Link.HUB_CLOUD: LinkProfile(True, 100_000, 30), Link.EDGE_CLOUD: LinkProfile(True, 64, 1100, 0.03),
        Link.FIELD_EDGE: _LOCAL, Link.CLOUD_LLM: LinkProfile(True, 100_000, 50),
    },
    Mode.M2_INTERMITTENT: {
        Link.FIELD_CLOUD: LinkProfile(True, 512, 400, 0.10, (20, 180), (30, 300)),
        Link.FIELD_HUB: LinkProfile(True, 512, 300, 0.10, (20, 180), (30, 300)),
        Link.HUB_CLOUD: LinkProfile(True, 100_000, 30),
        Link.EDGE_CLOUD: LinkProfile(True, 256, 500, 0.15, (20, 120), (60, 600)),
        Link.FIELD_EDGE: _LOCAL, Link.CLOUD_LLM: LinkProfile(True, 100_000, 50),
    },
    Mode.M3_CLOUD_AGENTS_DOWN: {  # network fine, model API failing (outage, quota, region)
        Link.FIELD_CLOUD: _GOOD_WAN, Link.FIELD_HUB: _GOOD_WAN, Link.HUB_CLOUD: LinkProfile(True, 100_000, 30),
        Link.EDGE_CLOUD: _GOOD_WAN, Link.FIELD_EDGE: _LOCAL, Link.CLOUD_LLM: _DOWN,
    },
    Mode.M4_HUB_ISLAND: {  # WAN backbone down, depot LAN/radio still up
        Link.FIELD_CLOUD: _DOWN, Link.FIELD_HUB: LinkProfile(True, 2_000, 120, 0.02),
        Link.HUB_CLOUD: _DOWN, Link.EDGE_CLOUD: _DOWN, Link.FIELD_EDGE: _LOCAL, Link.CLOUD_LLM: _DOWN,
    },
    Mode.M5_OFFLINE: {
        Link.FIELD_CLOUD: _DOWN, Link.FIELD_HUB: _DOWN, Link.HUB_CLOUD: _DOWN,
        Link.EDGE_CLOUD: _DOWN, Link.FIELD_EDGE: _LOCAL, Link.CLOUD_LLM: _DOWN,
    },
}


@dataclass(frozen=True)
class Segment:
    start_s: int
    mode: Mode
    telemetry_lost: bool = False  # M6 overlay: sensors / edge gateway not producing data
    note: str = ""


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    segments: tuple[Segment, ...]
    duration_s: int

    def segment_at(self, t: float) -> tuple[int, Segment]:
        if not 0 <= t < self.duration_s:
            raise ValueError(f"t={t} outside scenario 0..{self.duration_s}")
        idx = 0
        for i, seg in enumerate(self.segments):
            if seg.start_s <= t:
                idx = i
        return idx, self.segments[idx]

    def segment_end(self, idx: int) -> int:
        return self.segments[idx + 1].start_s if idx + 1 < len(self.segments) else self.duration_s


@dataclass(frozen=True)
class Delivery:
    ok: bool
    latency_ms: float
    reason: str  # delivered | link_down | flap_down | lost | timeout | telemetry_lost
    mode: Mode
    telemetry_lost: bool


class NetworkSim:
    def __init__(self, scenario: Scenario, seed: int = 0):
        self.scenario = scenario
        self.seed = seed
        self._flap_cache: dict[tuple[int, Link], list[tuple[int, int]]] = {}
        self._msg_counter = 0

    # -- state queries -----------------------------------------------------
    def mode_at(self, t: float) -> Mode:
        return self.scenario.segment_at(t)[1].mode

    def telemetry_lost_at(self, t: float) -> bool:
        return self.scenario.segment_at(t)[1].telemetry_lost

    def link_up(self, link: Link, t: float) -> bool:
        idx, seg = self.scenario.segment_at(t)
        prof = PROFILES[seg.mode][link]
        if not prof.up:
            return False
        if prof.flap_up_s == (0, 0):
            return True
        return any(a <= t < b for a, b in self._up_windows(idx, link, prof))

    def _up_windows(self, idx: int, link: Link, prof: LinkProfile) -> list[tuple[int, int]]:
        key = (idx, link)
        if key not in self._flap_cache:
            rng = random.Random(f"{self.seed}:flap:{idx}:{link.value}")
            t, end = self.scenario.segments[idx].start_s, self.scenario.segment_end(idx)
            windows, up = [], rng.random() < 0.5
            while t < end:
                dur = rng.randint(*(prof.flap_up_s if up else prof.flap_down_s))
                if up:
                    windows.append((t, min(t + dur, end)))
                t += dur
                up = not up
            self._flap_cache[key] = windows
        return self._flap_cache[key]

    # -- transmission ------------------------------------------------------
    def transmit(self, link: Link, nbytes: int, t: float, deadline_ms: float | None = None,
                 telemetry: bool = False) -> Delivery:
        """Simulate one request/response of ``nbytes`` payload over ``link`` at time ``t``.

        ``telemetry=True`` marks a request that needs fresh equipment data; it fails
        with ``telemetry_lost`` during an M6 overlay regardless of the link.
        """
        idx, seg = self.scenario.segment_at(t)
        prof = PROFILES[seg.mode][link]
        self._msg_counter += 1

        def result(ok: bool, latency: float, reason: str) -> Delivery:
            return Delivery(ok, round(latency, 1), reason, seg.mode, seg.telemetry_lost)

        if telemetry and seg.telemetry_lost:
            return result(False, 0.0, "telemetry_lost")
        if not prof.up:
            return result(False, 0.0, "link_down")
        if not self.link_up(link, t):
            return result(False, 0.0, "flap_down")

        rng = random.Random(f"{self.seed}:msg:{link.value}:{t}:{nbytes}:{self._msg_counter}")
        latency = prof.rtt_ms * rng.uniform(0.8, 1.4) + (nbytes * 8) / prof.bandwidth_kbps
        if deadline_ms is not None and latency > deadline_ms:
            return result(False, float(deadline_ms), "timeout")
        if rng.random() < prof.loss:
            return result(False, latency, "lost")
        return result(True, latency, "delivered")


H = 3600

SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in (
        Scenario("normal_day", "Full connectivity all shift.",
                 (Segment(0, Mode.M0_CONNECTED),), 10 * H),
        Scenario(
            "remote_site_visit",
            "Technician drives from depot into a desert dead zone and back.",
            (
                Segment(0, Mode.M0_CONNECTED, note="at depot, mission pack sync"),
                Segment(1 * H, Mode.M1_CONSTRAINED, note="highway, weak LTE"),
                Segment(2 * H, Mode.M2_INTERMITTENT, note="approach road"),
                Segment(3 * H, Mode.M5_OFFLINE, note="on site, no coverage"),
                Segment(6 * H, Mode.M2_INTERMITTENT, note="driving out"),
                Segment(7 * H, Mode.M0_CONNECTED, note="back in coverage, outbox replay"),
            ),
            8 * H,
        ),
        Scenario(
            "psps_outage",
            "Wildfire public-safety power shutoff: towers and site power drop, depot on generator.",
            (
                Segment(0, Mode.M0_CONNECTED),
                Segment(2 * H, Mode.M4_HUB_ISLAND, note="backbone down, depot on generator"),
                Segment(4 * H, Mode.M5_OFFLINE, telemetry_lost=True, note="site power cut, gateway battery exhausted"),
                Segment(16 * H, Mode.M4_HUB_ISLAND, note="power restoring"),
                Segment(20 * H, Mode.M0_CONNECTED),
            ),
            24 * H,
        ),
        Scenario(
            "cloud_llm_outage",
            "Network is fine but the cloud model API is unavailable for two hours.",
            (
                Segment(0, Mode.M0_CONNECTED),
                Segment(1 * H, Mode.M3_CLOUD_AGENTS_DOWN),
                Segment(3 * H, Mode.M0_CONNECTED),
            ),
            5 * H,
        ),
        Scenario(
            "satellite_backup",
            "Primary link lost; running all day on a constrained satellite backup.",
            (Segment(0, Mode.M1_CONSTRAINED),),
            10 * H,
        ),
        Scenario(
            "sensor_failure",
            "Connectivity fine but the asset's edge gateway stops reporting.",
            (
                Segment(0, Mode.M0_CONNECTED),
                Segment(1 * H, Mode.M0_CONNECTED, telemetry_lost=True, note="gateway offline"),
                Segment(5 * H, Mode.M0_CONNECTED),
            ),
            6 * H,
        ),
    )
}
