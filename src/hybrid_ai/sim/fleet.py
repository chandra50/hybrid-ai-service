"""Deterministic simulated fleet: sites, assets, technicians, stock, history, manuals.

Same seed -> identical fleet, so tests and agent evaluations are repeatable.
``active_faults`` is hidden ground truth: what is *really* wrong with each
faulty asset, used later to score diagnosis agents.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import catalog as cat

SIM_EPOCH = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)


@dataclass
class Location:
    lat: float
    lon: float


@dataclass
class Depot:
    depot_id: str
    region: str
    city: str
    location: Location
    has_workshop: bool
    has_edge_server: bool  # depot edge server: regional mirror + mid-size model


@dataclass
class Site:
    site_id: str
    name: str
    region: str
    depot_id: str
    location: Location
    coverage: str  # good | patchy | none
    hazards: list[str]
    access_notes: str


@dataclass
class Asset:
    asset_id: str
    model: str
    category: str
    site_id: str
    serial: str
    install_year: int
    criticality: str  # low | medium | high


@dataclass
class Technician:
    technician_id: str
    name: str
    home_depot: str
    van_id: str
    skills: list[str]
    on_shift: bool
    open_jobs: int
    location: Location


@dataclass
class RepairRecord:
    repair_id: str
    asset_id: str
    model: str
    date: str
    cause_code: str
    technician_id: str
    repair_location: str
    parts_used: list[dict[str, Any]]
    labor_hours: float
    first_time_fix: bool
    notes: str


@dataclass
class ManualSection:
    doc_id: str
    model: str
    title: str
    text: str


@dataclass
class WorkOrderRec:
    work_order_id: str
    asset_id: str
    status: str
    priority: str
    reported_symptoms: list[str]
    updated_at: str


@dataclass
class Fleet:
    seed: int
    generated_at: str
    depots: list[Depot]
    warehouse: dict[str, Any]
    sites: list[Site]
    assets: list[Asset]
    technicians: list[Technician]
    stock: dict[str, dict[str, int]]  # location_id (depot/van/warehouse) -> part -> qty
    repair_history: list[RepairRecord]
    manuals: list[ManualSection]
    work_orders: list[WorkOrderRec]
    active_faults: dict[str, dict[str, Any]] = field(default_factory=dict)

    # -- lookups -----------------------------------------------------------
    def asset(self, asset_id: str) -> Asset:
        return next(a for a in self.assets if a.asset_id == asset_id)

    def site(self, site_id: str) -> Site:
        return next(s for s in self.sites if s.site_id == site_id)

    def depot(self, depot_id: str) -> Depot:
        return next(d for d in self.depots if d.depot_id == depot_id)

    def technician(self, tech_id: str) -> Technician:
        return next(t for t in self.technicians if t.technician_id == tech_id)

    def history_for(self, asset_id: str) -> list[RepairRecord]:
        return [r for r in self.repair_history if r.asset_id == asset_id]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return p


def haversine_km(a: Location, b: Location) -> float:
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _clamp_ca(lat: float, lon: float) -> Location:
    return Location(round(min(max(lat, 32.6), 41.9), 4), round(min(max(lon, -124.2), -114.4), 4))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def generate_fleet(
    seed: int = 42,
    sites_per_depot: int = 2,
    assets_per_site: tuple[int, int] = (2, 3),
    techs_per_depot: int = 2,
    history_years: int = 4,
    fault_rate: float = 0.25,
) -> Fleet:
    rng = random.Random(seed)

    # Depots: every depot runs an edge server; only the bigger ones have a workshop.
    depots = [
        Depot(did, region, city, Location(lat, lon),
              has_workshop=did in ("DEP-SAC", "DEP-FAT", "DEP-BFL", "DEP-BSW"),
              has_edge_server=True)
        for did, (region, city, lat, lon) in cat.DEPOTS.items()
    ]
    wh_id, wh_city, wh_lat, wh_lon = cat.WAREHOUSE
    warehouse = {"warehouse_id": wh_id, "city": wh_city, "location": asdict(Location(wh_lat, wh_lon))}

    # Sites around each depot.
    sites: list[Site] = []
    for d in depots:
        good, patchy, _none = cat.COVERAGE_BY_REGION[d.region]
        for _ in range(sites_per_depot):
            n = len(sites) + 1
            loc = _clamp_ca(d.location.lat + rng.gauss(0, 0.45), d.location.lon + rng.gauss(0, 0.55))
            roll = rng.random()
            coverage = "good" if roll < good else "patchy" if roll < good + patchy else "none"
            sites.append(Site(
                site_id=f"SITE-{n:03d}",
                name=f"{d.city} area site {n}",
                region=d.region,
                depot_id=d.depot_id,
                location=loc,
                coverage=coverage,
                hazards=rng.sample(cat.HAZARDS, k=rng.randint(0, 2)),
                access_notes=f"Gate code on file; contact site operator {rng.randint(100, 999)}-{rng.randint(1000, 9999)}",
            ))

    # Assets: a fleet of industrial compressors.
    assets: list[Asset] = []
    for s in sites:
        choices = list(cat.MODELS)
        for _ in range(rng.randint(*assets_per_site)):
            m = rng.choice(choices)
            n = len(assets) + 1
            assets.append(Asset(
                asset_id=f"AST-{n:05d}",
                model=m.model,
                category=m.category,
                site_id=s.site_id,
                serial=f"{m.model.split('-')[0]}{rng.randint(100000, 999999)}",
                install_year=rng.randint(2008, 2025),
                criticality=rng.choices(("low", "medium", "high"), (0.3, 0.45, 0.25))[0],
            ))

    # Technicians with a realistic skill mix.
    techs: list[Technician] = []
    for d in depots:
        for _ in range(techs_per_depot):
            n = len(techs) + 1
            base = rng.sample(("mechanical", "electrical"), k=rng.randint(1, 2))
            extra = rng.sample([s for s in cat.SKILLS if s not in base], k=rng.randint(1, 3))
            if "hv_certified" in extra and "electrical" not in base:
                base.append("electrical")
            techs.append(Technician(
                technician_id=f"TEC-{n:04d}",
                name=f"{rng.choice(cat.FIRST_NAMES)} {rng.choice(cat.LAST_NAMES)}",
                home_depot=d.depot_id,
                van_id=f"VAN-{n:02d}",
                skills=sorted(set(base + extra)),
                on_shift=rng.random() < 0.8,
                open_jobs=rng.randint(0, 3),
                location=_clamp_ca(d.location.lat + rng.gauss(0, 0.3), d.location.lon + rng.gauss(0, 0.3)),
            ))

    # Stock: warehouse deep, depots medium, vans carry common consumables.
    parts = cat.all_parts()
    stock: dict[str, dict[str, int]] = {wh_id: {p: rng.randint(4, 20) for p in parts}}
    region_models: dict[str, set[str]] = {}
    for a in assets:
        region_models.setdefault(next(s.depot_id for s in sites if s.site_id == a.site_id), set()).add(a.model)
    for d in depots:
        models = region_models.get(d.depot_id, set())
        model_parts = {p for m in models for p in cat.MODELS_BY_NAME[m].parts}
        stock[d.depot_id] = {p: rng.randint(0, 5) for p in parts if p in model_parts}
    for t in techs:
        models = region_models.get(t.home_depot, set())
        model_parts = {p for m in models for p in cat.MODELS_BY_NAME[m].parts}
        candidates = [p for p in parts if p in model_parts]
        stock[t.van_id] = {p: rng.randint(1, 2) for p in rng.sample(candidates, k=min(len(candidates), 4))}

    # Repair history.
    history: list[RepairRecord] = []
    techs_by_depot: dict[str, list[Technician]] = {}
    for t in techs:
        techs_by_depot.setdefault(t.home_depot, []).append(t)
    site_by_id = {s.site_id: s for s in sites}
    for a in assets:
        model = cat.MODELS_BY_NAME[a.model]
        depot_id = site_by_id[a.site_id].depot_id
        for _ in range(rng.randint(0, history_years + 1)):
            fm = rng.choice(model.failure_modes)
            when = SIM_EPOCH - timedelta(days=rng.randint(30, 365 * history_years))
            tech = rng.choice(techs_by_depot[depot_id])
            ftf = rng.random() < 0.78
            history.append(RepairRecord(
                repair_id=f"REP-{len(history) + 1:06d}",
                asset_id=a.asset_id,
                model=a.model,
                date=when.date().isoformat(),
                cause_code=fm.code,
                technician_id=tech.technician_id,
                repair_location="workshop" if fm.needs_workshop else "on_site",
                parts_used=[{"part_number": p, "qty": q} for p, q in fm.parts],
                labor_hours=round(fm.est_hours * rng.uniform(0.7, 1.6), 1),
                first_time_fix=ftf,
                notes=(f"{fm.description}. Symptoms: {', '.join(rng.sample(fm.symptoms, k=min(2, len(fm.symptoms))))}. "
                       + ("Resolved on first visit." if ftf else "Return visit needed - part not in the van.")),
            ))
    history.sort(key=lambda r: r.date)

    manuals = _manuals()

    # Active faults (ground truth) and the open work orders they produced.
    faults: dict[str, dict[str, Any]] = {}
    work_orders: list[WorkOrderRec] = []
    for a in assets:
        if rng.random() >= fault_rate:
            continue
        fm = rng.choice(cat.MODELS_BY_NAME[a.model].failure_modes)
        onset = SIM_EPOCH - timedelta(hours=rng.randint(6, 240))
        faults[a.asset_id] = {"cause_code": fm.code, "onset": _iso(onset),
                              "hours_to_full": rng.choice((48, 96, 168))}
        reported = rng.random() < 0.7  # some faults are only visible in telemetry
        if reported:
            work_orders.append(WorkOrderRec(
                work_order_id=f"WO-2026-{len(work_orders) + 1:04d}",
                asset_id=a.asset_id,
                status="open",
                priority={"low": "routine", "medium": "soon", "high": "urgent", "critical": "emergency"}[fm.severity],
                reported_symptoms=rng.sample(fm.symptoms, k=min(2, len(fm.symptoms))),
                updated_at=_iso(SIM_EPOCH - timedelta(hours=rng.randint(0, 5))),
            ))

    return Fleet(
        seed=seed,
        generated_at=_iso(SIM_EPOCH),
        depots=depots,
        warehouse=warehouse,
        sites=sites,
        assets=assets,
        technicians=techs,
        stock=stock,
        repair_history=history,
        manuals=manuals,
        work_orders=work_orders,
        active_faults=faults,
    )


def _manuals() -> list[ManualSection]:
    out: list[ManualSection] = []
    for m in cat.MODELS:
        sections: list[tuple[str, str]] = [
            ("Safety and lockout/tagout",
             "Before any service on the " + m.category + ":\n" + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(cat.LOTO_STEPS))),
            ("Specifications and normal operating values",
             "\n".join(f"- {s.name}: nominal {s.baseline} {s.unit}"
                       + (f", warning {'below' if s.low_is_bad else 'above'} {s.warn}" if s.warn is not None else "")
                       + (f", trip {'below' if s.low_is_bad else 'above'} {s.trip}" if s.trip is not None else "")
                       for s in m.signals)),
            ("Parts list",
             "\n".join(f"- {pn}: {desc}" for pn, desc in m.parts.items())),
        ]
        for fm in m.failure_modes:
            sections.append((
                f"Troubleshooting: {fm.description}",
                f"Fault code {fm.code}. Typical symptoms: {'; '.join(fm.symptoms)}.\n"
                f"Required skills: {', '.join(fm.skills)}. Estimated labor: {fm.est_hours} h."
                + (" Normally performed at a workshop." if fm.needs_workshop else "")
                + (" SAFETY CRITICAL: stop the unit." if fm.safety_critical else "")
                + "\nProcedure:\n" + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(fm.procedure))
                + "\nParts: " + ", ".join(f"{q} x {p} ({m.parts[p]})" for p, q in fm.parts),
            ))
        for i, (title, text) in enumerate(sections, start=1):
            out.append(ManualSection(f"MAN-{m.model}-{i:02d}", m.model, title, text))
    return out
