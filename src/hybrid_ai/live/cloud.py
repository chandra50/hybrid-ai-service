"""Cloud place: an MCP server over the authoritative data.

Tools: diagnose_issue (cloud copy of the repair-rec model, full fleet telemetry),
find_technicians, recommend_repair_location, check_parts, reserve_parts,
get_repair_plan / update_step / record_outcome (repair recommendations DB),
explain (stands in for the cloud LLM; fails during a cloud AI outage),
ingest_features (summarized telemetry pushed by the edge), health, status.

Control (operator switch, not part of MCP):  POST /control {"cloud_ai_down": bool}
"""

from __future__ import annotations

import asyncio

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..demo import repair_db
from .common import DATA_DIR, HOST, PORT, demo_data, features_from_series, manual_agent, now_iso, rank

srv = MCPServer(name="hybrid-cloud", instructions="Authoritative cloud tools for the compressor fleet.")
STATE = {"ai_down": False, "features": {}, "features_received": 0, "reservations": {}}
DB = None


def _wo(work_order_id: str) -> dict:
    wo = next((w for w in demo_data()["work_orders"] if w["work_order_id"] == work_order_id), None)
    if wo is None:
        raise ToolError(f"unknown work order {work_order_id}")
    return wo


def _asset(asset_id: str) -> dict:
    return next(a for a in demo_data()["assets"] if a["asset_id"] == asset_id)


@srv.tool()
def health() -> dict:
    """Liveness probe used by the device's link monitor."""
    return {"place": "cloud", "ok": True, "ai_down": STATE["ai_down"], "at": now_iso()}


@srv.tool()
def diagnose_issue(work_order_id: str, symptoms: list[str] | None = None) -> dict:
    """Rank likely causes with the cloud copy of the repair recommendation model."""
    wo = _wo(work_order_id)
    a = _asset(wo["asset_id"])
    tel = demo_data()["telemetry"][a["asset_id"]]
    readings, trends = features_from_series(tel["series"], tel["thresholds"])
    syms = list(dict.fromkeys((wo.get("symptoms") or []) + (symptoms or [])))
    return {"place": "cloud", "model": "repair-rec (cloud copy)", "inputs": "fleet telemetry + symptoms",
            "causes": rank(a["model"], readings, trends, syms)[:3]}


@srv.tool()
def find_technicians(work_order_id: str) -> dict:
    """Live roster, GPS and SLA: rank technicians."""
    return {"place": "cloud", "freshness": "live", "candidates": _wo(work_order_id)["technicians"][:3]}


@srv.tool()
def recommend_repair_location(work_order_id: str) -> dict:
    """On site vs workshop, with the factors."""
    return {"place": "cloud", **_wo(work_order_id)["location"]}


@srv.tool()
def check_parts(work_order_id: str) -> dict:
    """Live ERP: every source for each part."""
    return {"place": "cloud", "freshness": "live ERP", "lines": _wo(work_order_id)["parts"]["lines"]}


@srv.tool()
def reserve_parts(work_order_id: str, idempotency_key: str) -> dict:
    """Hard reservation in the ERP. Replaying the same key returns the same reservation."""
    if idempotency_key not in STATE["reservations"]:
        STATE["reservations"][idempotency_key] = {"reservation_id": f"RSV-{len(STATE['reservations']) + 1:04d}",
                                                  "work_order_id": work_order_id, "status": "hard", "at": now_iso()}
        return {"place": "cloud", "duplicate": False, **STATE["reservations"][idempotency_key]}
    return {"place": "cloud", "duplicate": True, **STATE["reservations"][idempotency_key]}


@srv.tool()
def get_repair_plan(work_order_id: str) -> dict:
    """The repair recommendation for a work order, from the repair recommendations DB."""
    plan = repair_db.get_plan(DB, work_order_id)
    if plan is None:
        raise ToolError(f"no plan for {work_order_id}")
    return {"place": "cloud", "plan": plan}


@srv.tool()
def update_step(work_order_id: str, seq: int, status: str, by: str, idempotency_key: str,
                origin_tier: str = "device", at: str | None = None) -> dict:
    """Mark a repair-plan step. Idempotent: a replayed key is acknowledged but not applied twice."""
    res = repair_db.update_step(DB, work_order_id, seq, status, by, idempotency_key, at=at, origin_tier=origin_tier)
    return {"place": "cloud", **res}


@srv.tool()
def record_outcome(work_order_id: str, confirmed_cause: str, by: str, idempotency_key: str, notes: str = "") -> dict:
    """Complete the work order with the confirmed cause."""
    plan = repair_db.get_plan(DB, work_order_id)
    if plan and plan["outcome"]:
        return {"place": "cloud", "applied": False, "duplicate": True}
    repair_db.record_outcome(DB, work_order_id, confirmed_cause, by, notes)
    return {"place": "cloud", "applied": True, "duplicate": False}


@srv.tool()
def explain(facts: str, question: str = "") -> dict:
    """Write a short answer for the technician (stands in for the cloud LLM)."""
    if STATE["ai_down"]:
        raise ToolError("cloud model API unavailable (cloud AI outage)")
    return {"place": "cloud", "model": "claude-haiku-5-5 (simulated: templated text, no LLM call)", "answer": facts}


@srv.tool()
async def recommend_repair(work_order_id: str, question: str = "") -> dict:
    """Repair recommendation from the Claude agent: RAG over the service manuals with cited steps.
    Fails (so the router falls back) when the cloud AI is down or no Claude credentials are configured."""
    from ..agents.manual_agent import AgentUnavailable
    if STATE["ai_down"]:
        raise ToolError("cloud model API unavailable (cloud AI outage)")
    try:
        res = await asyncio.to_thread(manual_agent().recommend, work_order_id, question)
    except AgentUnavailable as e:
        raise ToolError(f"manual agent unavailable: {e}") from e
    return {"place": "cloud", **res}


@srv.tool()
def ingest_features(asset_id: str, ts: str, features: dict) -> dict:
    """Summarized telemetry pushed by the edge (never raw waveforms)."""
    STATE["features"][asset_id] = {"ts": ts, "features": features, "received": now_iso()}
    STATE["features_received"] += 1
    return {"place": "cloud", "ok": True, "received": STATE["features_received"]}


@srv.tool()
def status() -> dict:
    """Summary for the live dashboard."""
    plans = repair_db.list_plans(DB)
    return {"place": "cloud", "ai_down": STATE["ai_down"], "plans": len(plans),
            "steps_done": sum(p["steps_done"] or 0 for p in plans),
            "completed": [p["work_order_id"] for p in plans if p["status"] == "completed"],
            "in_progress": [p["work_order_id"] for p in plans if p["status"] == "in_progress"],
            "features_received": STATE["features_received"],
            "last_feature": max((v["received"] for v in STATE["features"].values()), default=None),
            "reservations": len(STATE["reservations"])}


@srv.custom_route("/control", methods=["GET", "POST"])
async def control(request: Request) -> JSONResponse:
    if request.method == "POST":
        body = await request.json()
        if "cloud_ai_down" in body:
            STATE["ai_down"] = bool(body["cloud_ai_down"])
    return JSONResponse({"ai_down": STATE["ai_down"]})


def main() -> None:
    global DB
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "cloud-repair-recommendations.db"
    path.unlink(missing_ok=True)
    DB = repair_db.connect(path)
    repair_db.populate(DB, demo_data())
    app = srv.streamable_http_app(stateless_http=True, json_response=True)
    print(f"cloud: MCP on http://{HOST}:{PORT['cloud']}/mcp, repair DB {path}", flush=True)
    try:
        asyncio.run(uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT["cloud"], log_level="warning")).serve())
    except KeyboardInterrupt:  # stopped by the launcher
        pass


if __name__ == "__main__":
    main()
