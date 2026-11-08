"""Build the dashboard's demo data from the simulators.

    PYTHONPATH=src python3 -m hybrid_ai.demo.build_data [--seed 42] [--out dashboard/data.js]

Writes ``window.HYBRID_DATA = {...}`` so the static dashboard works without a
server-side API. The "agent" recommendations here are deterministic rules
(the same fallbacks the design uses when no LLM is reachable). They stand in
for the phase 2 agents until those exist.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import timedelta
from pathlib import Path
from typing import Any

from ..sim import catalog as cat
from ..sim.fleet import SIM_EPOCH, Fleet, Location, generate_fleet, haversine_km
from ..sim.network import SCENARIOS
from ..models.repair_model import HEALTHY, VERSION, RepairModel, train
from ..sim.telemetry import _iso, fault_progress, live_telemetry

MODEL_PATH = Path(__file__).resolve().parents[3] / "models" / f"{VERSION}.json"

NOW = SIM_EPOCH + timedelta(hours=12)
SEV_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
URGENCY = {"low": "routine", "medium": "soon", "high": "urgent", "critical": "emergency"}
COVERAGE_MODE = {"good": "ONLINE", "patchy": "LIMITED", "none": "OFFLINE"}
DRIVE_KMH = 60.0
ROAD_FACTOR = 1.3


def drive(a: Location, b: Location) -> tuple[float, int]:
    km = haversine_km(a, b) * ROAD_FACTOR
    return round(km, 1), int(km / DRIVE_KMH * 60)


# ---------------------------------------------------------------- agents (rule fallbacks)
def latest(series: list[dict[str, Any]]) -> dict[str, float]:
    return {s["signal"]: s["points"][-1]["value"] for s in series}


def trends(series: list[dict[str, Any]], baselines: dict[str, float]) -> dict[str, float]:
    """Relative change over the telemetry window, per signal."""
    return {x["signal"]: (x["points"][-1]["value"] - x["points"][0]["value"]) / baselines[x["signal"]] for x in series}


def diagnose(model: RepairModel, asset, series: list[dict[str, Any]], symptoms: list[str],
             alarms: list[dict]) -> dict[str, Any]:
    """Rank causes with the repair recommendation model, then apply the safety rules."""
    am = cat.MODELS_BY_NAME[asset.model]
    base = {s.name: s.baseline for s in am.signals}
    ranked = model.predict(asset.model, latest(series), trends(series, base), symptoms)
    healthy = next((r["probability"] for r in ranked if r["cause_code"] == HEALTHY), 0.0)
    faults = [r for r in ranked if r["cause_code"] != HEALTHY]
    total = sum(r["probability"] for r in faults) or 1.0
    causes = [{**r, "probability": round(r["probability"] / total, 2),
               "severity": cat.failure_mode(r["cause_code"])[1].severity} for r in faults]
    top = cat.failure_mode(causes[0]["cause_code"])[1]
    trip = any(a["severity"] == "critical" for a in alarms)
    unsafe = trip or (top.safety_critical and causes[0]["probability"] > 0.4)
    evidence = [a["message"] for a in alarms[-3:]]
    if symptoms:
        evidence.append("Reported: " + "; ".join(symptoms))
    return {
        "causes": causes,
        "severity": top.severity,
        "safe_to_run": not unsafe,
        "safety_override": trip,
        "evidence": evidence,
        "model_version": model.version,
        "model_confidence": causes[0]["probability"],
        "healthy_probability": round(healthy, 3),
    }


def load_or_train_model(fleet: Fleet) -> RepairModel:
    if MODEL_PATH.exists():
        return RepairModel.load(MODEL_PATH)
    model = train(seed=fleet.seed, repair_history=fleet.repair_history)
    model.save(MODEL_PATH)
    return model


def rank_technicians(fleet: Fleet, site, skills: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for t in fleet.technicians:
        matched = [s for s in skills if s in t.skills]
        km, eta = drive(t.location, site.location)
        score = (0.45 * len(matched) / len(skills) + 0.25 * (1 - min(km / 500, 1))
                 + 0.15 * (1 if t.on_shift else 0) + 0.15 * (1 - min(t.open_jobs, 4) / 4))
        out.append({"technician_id": t.technician_id, "name": t.name, "score": round(score, 2),
                    "available": t.on_shift, "distance_km": km, "eta_min": eta, "skills_matched": matched,
                    "missing_skills": [s for s in skills if s not in t.skills]})
    return sorted(out, key=lambda c: -c["score"])[:5]


def repair_location(fleet: Fleet, asset, fm: cat.FailureMode, site) -> dict[str, Any]:
    model = cat.MODELS_BY_NAME[asset.model]
    factors = [
        {"factor": f"Estimated {fm.est_hours} h repair", "favors": "workshop" if fm.est_hours >= 8 else "on_site", "weight": 0.3},
        {"factor": "Portable / skid-mounted" if model.portable else "Fixed or large asset",
         "favors": "workshop" if model.portable else "on_site", "weight": 0.25},
        {"factor": "Needs bench or test rig" if fm.needs_workshop else "Field-serviceable",
         "favors": "workshop" if fm.needs_workshop else "on_site", "weight": 0.35},
        {"factor": f"Criticality {asset.criticality}: downtime cost",
         "favors": "on_site" if asset.criticality == "high" else "neutral", "weight": 0.1},
    ]
    ws = sum(f["weight"] for f in factors if f["favors"] == "workshop")
    on = sum(f["weight"] for f in factors if f["favors"] == "on_site")
    loc = "workshop" if (ws > on and model.portable) else "on_site"
    out = {"location": loc, "score_on_site": round(on, 2), "score_workshop": round(ws, 2), "factors": factors}
    if loc == "workshop":
        shops = [d for d in fleet.depots if d.has_workshop]
        out["workshop_id"] = min(shops, key=lambda d: haversine_km(d.location, site.location)).depot_id
    elif fm.needs_workshop:
        out["note"] = "Workshop-type job on a fixed asset: bring the workshop to the site (crane / exchange unit)"
    return out


def parts_plan(fleet: Fleet, fm: cat.FailureMode, site, tech) -> dict[str, Any]:
    depot = fleet.depot(site.depot_id)
    wh = Location(**fleet.warehouse["location"])
    lines, total, all_local = [], 0, True
    for pn, qty in fm.parts:
        price = cat.PART_PRICES[pn]
        total += price * qty
        srcs = []
        if tech:
            srcs.append({"source_type": "van", "source_id": tech.van_id,
                         "qty": fleet.stock.get(tech.van_id, {}).get(pn, 0), "eta_hours": 0})
        srcs.append({"source_type": "depot", "source_id": depot.depot_id, "qty": fleet.stock[depot.depot_id].get(pn, 0),
                     "eta_hours": round(drive(depot.location, site.location)[1] / 60, 1)})
        srcs.append({"source_type": "warehouse", "source_id": fleet.warehouse["warehouse_id"],
                     "qty": fleet.stock[fleet.warehouse["warehouse_id"]].get(pn, 0),
                     "eta_hours": round(drive(wh, site.location)[1] / 60 + 2, 1)})
        srcs.append({"source_type": "vendor", "source_id": "VENDOR", "qty": 99, "eta_hours": 72})
        pick = next(s for s in srcs if s["qty"] >= qty)
        if pick["source_type"] not in ("van", "depot"):
            all_local = False
        lines.append({"part_number": pn, "description": cat.all_parts()[pn], "qty": qty, "unit_price": price,
                      "sources": srcs, "pick": pick["source_id"], "pick_type": pick["source_type"]})
    return {"lines": lines, "total_usd": total, "all_local": all_local}


def approvals(diag, urgency, best, loc, parts) -> list[dict[str, Any]]:
    out = []
    if diag["safety_override"]:
        out.append({"action": "Shutdown", "rule": "Edge safety rule fired", "outcome": "auto", "approver": "Auto, supervisor notified"})
    elif not diag["safe_to_run"]:
        out.append({"action": "Shutdown", "rule": "Unsafe verdict without edge trip", "outcome": "human", "approver": "Site operator"})
    full = best and not best["missing_skills"] and best["available"]
    if urgency in ("routine", "soon") and full:
        out.append({"action": "Dispatch", "rule": "Routine or soon, skills matched, on shift", "outcome": "auto", "approver": "Auto"})
    else:
        why = "Urgent/emergency" if urgency in ("urgent", "emergency") else "Missing skills or off shift"
        out.append({"action": "Dispatch", "rule": why, "outcome": "human", "approver": "Supervisor"})
    if parts["all_local"] and parts["total_usd"] < 1000:
        out.append({"action": "Parts", "rule": "Van or depot stock, under $1,000", "outcome": "auto", "approver": "Auto"})
    else:
        why = "Vendor or warehouse order" if not parts["all_local"] else "$1,000 or more"
        out.append({"action": "Parts", "rule": why, "outcome": "human", "approver": "Regional manager"})
    if loc["location"] == "workshop":
        out.append({"action": "Workshop", "rule": "Any transfer to a workshop", "outcome": "human", "approver": "Supervisor"})
    return out


# ---------------------------------------------------------------- build
def build(seed: int = 42) -> dict[str, Any]:
    fleet = generate_fleet(seed=seed)
    rmodel = load_or_train_model(fleet)
    rng = random.Random(seed * 7 + 1)
    site_by = {s.site_id: s for s in fleet.sites}

    assets_out, telemetry = [], {}
    for a in fleet.assets:
        site = site_by[a.site_id]
        # random position around the site so co-located assets don't stack
        lat = site.location.lat + rng.uniform(-0.09, 0.09)
        lon = site.location.lon + rng.uniform(-0.11, 0.11)
        tel = live_telemetry(fleet, a.asset_id, NOW, window_min=180, step_min=5)
        model = cat.MODELS_BY_NAME[a.model]
        thresholds = {s.name: {"warn": s.warn, "trip": s.trip, "low_is_bad": s.low_is_bad, "baseline": s.baseline}
                      for s in model.signals}
        telemetry[a.asset_id] = {"series": tel["series"], "alarms": tel["alarms"], "thresholds": thresholds}
        sev = max((SEV_RANK[x["severity"]] for x in tel["alarms"]), default=-1)
        status = "fault" if sev >= 3 else "warning" if sev >= 1 else "healthy"
        assets_out.append({
            "asset_id": a.asset_id, "model": a.model, "category": a.category, "site_id": a.site_id,
            "site_name": site.name, "region": site.region, "depot_id": site.depot_id,
            "lat": round(lat, 5), "lon": round(lon, 5), "criticality": a.criticality, "install_year": a.install_year,
            "serial": a.serial, "status": status, "coverage": site.coverage,
            "site_mode": COVERAGE_MODE[site.coverage], "hazards": site.hazards, "access_notes": site.access_notes,
        })

    # Work orders: reported ones plus telemetry-detected silent faults.
    wos = [{"work_order_id": w.work_order_id, "asset_id": w.asset_id, "priority": w.priority,
            "symptoms": w.reported_symptoms, "source": "reported", "created": w.updated_at} for w in fleet.work_orders]
    reported = {w["asset_id"] for w in wos}
    for aid in fleet.active_faults:
        if aid not in reported and telemetry[aid]["alarms"]:
            wos.append({"work_order_id": f"WO-2026-{len(wos) + 1:04d}", "asset_id": aid, "priority": None,
                        "symptoms": [], "source": "telemetry", "created": telemetry[aid]["alarms"][0]["ts"]})

    plans_ok = 0
    for i, wo in enumerate(wos):
        asset = fleet.asset(wo["asset_id"])
        site = site_by[asset.site_id]
        tel = telemetry[asset.asset_id]
        diag = diagnose(rmodel, asset, tel["series"], wo["symptoms"], tel["alarms"])
        _, fm = cat.failure_mode(diag["causes"][0]["cause_code"])
        wo["priority"] = wo["priority"] or URGENCY[fm.severity]
        techs = rank_technicians(fleet, site, fm.skills)
        best = techs[0]
        tech = fleet.technician(best["technician_id"])
        loc = repair_location(fleet, asset, fm, site)
        parts = parts_plan(fleet, fm, site, tech)
        appr = approvals(diag, wo["priority"], best, loc, parts)
        needs_human = any(x["outcome"] == "human" for x in appr)
        wo.update({
            "title": f"{asset.category[0].upper() + asset.category[1:]} at {site.name}",
            "status": "assigned" if not needs_human else "awaiting_approval",
            "assigned_technician_id": best["technician_id"] if not needs_human else None,
            "diagnosis": diag, "skills_required": list(fm.skills), "est_hours": fm.est_hours,
            "procedure": list(fm.procedure), "technicians": techs, "location": loc, "parts": parts,
            "approvals": appr, "ground_truth": fleet.active_faults.get(asset.asset_id, {}).get("cause_code"),
        })
        plans_ok += wo["ground_truth"] == diag["causes"][0]["cause_code"]

    # Assets with an open work order show at least as warning, or as fault when it's serious.
    by_id = {a["asset_id"]: a for a in assets_out}
    for wo in wos:
        a = by_id[wo["asset_id"]]
        serious = SEV_RANK[wo["diagnosis"]["severity"]] >= 2 or not wo["diagnosis"]["safe_to_run"]
        a["status"] = "fault" if serious else ("warning" if a["status"] == "healthy" else a["status"])
        a["work_order_id"] = wo["work_order_id"]

    # Make sure the technician persona has a job to open: the first awaiting WO with a full skill match
    # is pre-approved by the planner.
    if not any(w["status"] == "assigned" for w in wos):
        w = wos[0]
        w["status"], w["assigned_technician_id"] = "assigned", w["technicians"][0]["technician_id"]
        for a in w["approvals"]:
            if a["outcome"] == "human":
                a["outcome"], a["approver"] = "approved", a["approver"] + " (approved)"

    techs_out = [{
        "technician_id": t.technician_id, "name": t.name, "home_depot": t.home_depot, "van_id": t.van_id,
        "skills": t.skills, "on_shift": t.on_shift, "open_jobs": t.open_jobs,
        "lat": t.location.lat, "lon": t.location.lon,
        "van_stock": [{"part_number": p, "description": cat.all_parts()[p], "qty": q}
                        for p, q in sorted(fleet.stock.get(t.van_id, {}).items())],
    } for t in fleet.technicians]

    manuals = {}
    for m in fleet.manuals:
        manuals.setdefault(m.model, []).append({"doc_id": m.doc_id, "title": m.title, "text": m.text})
    history = {}
    for r in fleet.repair_history:
        history.setdefault(r.asset_id, []).append({"date": r.date, "cause_code": r.cause_code,
                                                   "labor_hours": r.labor_hours, "first_time_fix": r.first_time_fix,
                                                   "notes": r.notes, "technician_id": r.technician_id})
    for v in history.values():
        v.sort(key=lambda r: r["date"], reverse=True)

    scenarios = [{"name": s.name, "description": s.description, "duration_s": s.duration_s,
                  "segments": [{"start_s": g.start_s, "mode": g.mode.value, "sensors_lost": g.sensors_lost,
                                "cloud_ai_down": g.cloud_ai_down,
                                "note": g.note} for g in s.segments]} for s in SCENARIOS.values()]

    return {
        "generated": {"seed": seed, "now": _iso(NOW), "diagnosis_top1_correct": f"{plans_ok}/{len(wos)}"},
        "repair_model": rmodel.to_dict(),
        "depots": [{"depot_id": d.depot_id, "city": d.city, "region": d.region, "lat": d.location.lat,
                    "lon": d.location.lon, "has_workshop": d.has_workshop, "has_edge_server": d.has_edge_server,
                    "stock": [{"part_number": p, "qty": q} for p, q in sorted(fleet.stock[d.depot_id].items())]}
                   for d in fleet.depots],
        "warehouse": fleet.warehouse,
        "assets": assets_out,
        "technicians": techs_out,
        "work_orders": wos,
        "telemetry": telemetry,
        "manuals": manuals,
        "history": history,
        "loto": list(cat.LOTO_STEPS),
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="dashboard/data.js")
    args = ap.parse_args(argv)
    data = build(args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("window.HYBRID_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n", encoding="utf-8")
    g = data["generated"]
    print(f"wrote {out} ({out.stat().st_size // 1024} KB): {len(data['assets'])} assets, "
          f"{len(data['work_orders'])} work orders, diagnosis top-1 correct {g['diagnosis_top1_correct']}")


if __name__ == "__main__":
    main()
