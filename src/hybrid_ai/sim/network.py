"""Network fault injector for the three operating modes (DESIGN.md section 5).

Modes describe the technician's link:

    ONLINE   cloud reachable, normal latency
    LIMITED  slow or intermittent: one bar of LTE, satellite backup, coverage gaps
    OFFLINE  no WAN: only the device and the site edge, over the local link

Two events can happen inside any mode:

    cloud_ai_down   the cloud model API fails while the network still works
    sensors_lost    the site edge gateway / sensors stop reporting

A ``Scenario`` is a timeline of segments. ``NetworkSim`` answers "what happens if
I send N bytes over link L at time t?" deterministically for a given seed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum


class Mode(str, Enum):
    ONLINE = "ONLINE"
    LIMITED = "LIMITED"
    OFFLINE = "OFFLINE"


class Link(str, Enum):
    DEVICE_CLOUD = "device->cloud"
    EDGE_CLOUD = "edge->cloud"
    DEVICE_EDGE = "device->edge"   # local site Wi-Fi/BLE, never needs the WAN
    CLOUD_AI = "cloud->ai"         # the cloud model API itself


WAN_LINKS = {Link.DEVICE_CLOUD, Link.EDGE_CLOUD}


@dataclass(frozen=True)
class LinkProfile:
    up: bool
    bandwidth_kbps: float = 0.0
    rtt_ms: float = 0.0
    loss: float = 0.0                         # per-message loss probability
    flap_up_s: tuple[int, int] = (0, 0)       # if set, link alternates up/down windows
    flap_down_s: tuple[int, int] = (0, 0)


_LOCAL = LinkProfile(True, 20_000, 15)
_DOWN = LinkProfile(False)
_AI = LinkProfile(True, 100_000, 50)

PROFILES: dict[Mode, dict[Link, LinkProfile]] = {
    Mode.ONLINE: {
        Link.DEVICE_CLOUD: LinkProfile(True, 10_000, 80), Link.EDGE_CLOUD: LinkProfile(True, 10_000, 80),
        Link.DEVICE_EDGE: _LOCAL, Link.CLOUD_AI: _AI,
    },
    Mode.LIMITED: {  # slow AND intermittent: one bar of LTE, satellite, the edge of coverage
        Link.DEVICE_CLOUD: LinkProfile(True, 256, 700, 0.05, (20, 180), (30, 300)),
        Link.EDGE_CLOUD: LinkProfile(True, 128, 900, 0.08, (20, 120), (60, 600)),
        Link.DEVICE_EDGE: _LOCAL, Link.CLOUD_AI: _AI,
    },
    Mode.OFFLINE: {
        Link.DEVICE_CLOUD: _DOWN, Link.EDGE_CLOUD: _DOWN, Link.DEVICE_EDGE: _LOCAL, Link.CLOUD_AI: _AI,
    },
}


@dataclass(frozen=True)
class Segment:
    start_s: int
    mode: Mode
    sensors_lost: bool = False    # event: site gateway / sensors not reporting
    cloud_ai_down: bool = False   # event: cloud model API failing
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
    reason: str  # delivered | link_down | flap_down | lost | timeout | sensors_lost | ai_down
    mode: Mode
    sensors_lost: bool
    cloud_ai_down: bool


class NetworkSim:
    def __init__(self, scenario: Scenario, seed: int = 0):
        self.scenario = scenario
        self.seed = seed
        self._flap_cache: dict[tuple[int, Link], list[tuple[int, int]]] = {}
        self._msg_counter = 0

    def mode_at(self, t: float) -> Mode:
        return self.scenario.segment_at(t)[1].mode

    def sensors_lost_at(self, t: float) -> bool:
        return self.scenario.segment_at(t)[1].sensors_lost

    def cloud_ai_down_at(self, t: float) -> bool:
        return self.scenario.segment_at(t)[1].cloud_ai_down

    def link_up(self, link: Link, t: float) -> bool:
        idx, seg = self.scenario.segment_at(t)
        if link is Link.CLOUD_AI and seg.cloud_ai_down:
            return False
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

    def transmit(self, link: Link, nbytes: int, t: float, deadline_ms: float | None = None,
                 telemetry: bool = False) -> Delivery:
        """Simulate one request/response of ``nbytes`` over ``link`` at time ``t``.

        ``telemetry=True`` marks a request that needs fresh equipment data; it fails
        with ``sensors_lost`` during that event regardless of the link.
        """
        idx, seg = self.scenario.segment_at(t)
        prof = PROFILES[seg.mode][link]
        self._msg_counter += 1

        def result(ok: bool, latency: float, reason: str) -> Delivery:
            return Delivery(ok, round(latency, 1), reason, seg.mode, seg.sensors_lost, seg.cloud_ai_down)

        if telemetry and seg.sensors_lost:
            return result(False, 0.0, "sensors_lost")
        if link is Link.CLOUD_AI and seg.cloud_ai_down:
            return result(False, 0.0, "ai_down")
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
ON, LIM, OFF = Mode.ONLINE, Mode.LIMITED, Mode.OFFLINE

SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in (
        Scenario("normal_day", "Online all shift.", (Segment(0, ON),), 10 * H),
        Scenario(
            "remote_site_visit",
            "Technician drives from the depot into a desert dead zone and back.",
            (
                Segment(0, ON, note="at depot, mission pack sync"),
                Segment(1 * H, LIM, note="highway and approach road, weak signal"),
                Segment(3 * H, OFF, note="on site, no coverage"),
                Segment(6 * H, LIM, note="driving out, signal returning"),
                Segment(7 * H, ON, note="back in coverage, outbox replay"),
            ),
            8 * H,
        ),
        Scenario(
            "psps_outage",
            "Wildfire public-safety power shutoff: towers and site power drop.",
            (
                Segment(0, ON),
                Segment(2 * H, LIM, note="towers on backup power, links degrading"),
                Segment(4 * H, OFF, sensors_lost=True, note="site power cut, gateway battery exhausted"),
                Segment(16 * H, LIM, note="power restoring"),
                Segment(20 * H, ON),
            ),
            24 * H,
        ),
        Scenario(
            "cloud_ai_outage",
            "Network is fine but the cloud model API is unavailable for two hours.",
            (
                Segment(0, ON),
                Segment(1 * H, ON, cloud_ai_down=True, note="cloud model API failing"),
                Segment(3 * H, ON),
            ),
            5 * H,
        ),
        Scenario(
            "satellite_backup",
            "Primary link lost; running all day on a constrained satellite backup.",
            (Segment(0, LIM),),
            10 * H,
        ),
        Scenario(
            "sensor_failure",
            "Online, but the compressor's edge gateway stops reporting.",
            (
                Segment(0, ON),
                Segment(1 * H, ON, sensors_lost=True, note="gateway offline"),
                Segment(5 * H, ON),
            ),
            6 * H,
        ),
    )
}
