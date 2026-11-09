"""Edge place: an MCP server at the site gateway / depot server.

Telemetry is read from per-compressor JSONL files (the demo stand-in for
OPC-UA/Modbus). Tools: get_live_telemetry, diagnose_issue (edge copy of the
repair-rec model on live readings), find_technicians (depot roster snapshot),
check_parts (depot mirror), explain (stands in for the edge LLM), health, status.

In the background it pushes summarized features for compressors with open work
orders to the cloud every few seconds, over the edge->cloud link. When that link
is down the features are buffered and sent when it returns (store-and-forward).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from datetime import datetime

import uvicorn
from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ..sim.fleet import SIM_EPOCH, generate_fleet
from ..sim.telemetry import export_telemetry_files, read_telemetry_file
from .common import DATA_DIR, HOST, PORT, SEED, demo_data, features_from_series, manual_agent, now_iso, rank, url

srv = MCPServer(name="hybrid-edge", instructions="Edge tools next to the compressors.")
TEL_DIR = DATA_DIR / "edge-telemetry"
STATE = {"pushed": 0, "push_failed": 0, "buffer": []}


def _now() -> datetime:
    return datetime.fromisoformat(demo_data()["generated"]["now"].replace("Z", "+00:00"))


def _wo(work_order_id: str) -> dict:
    wo = next((w for w in demo_data()["work_orders"] if w["work_order_id"] == work_order_id), None)
    if wo is None:
        raise ToolError(f"unknown work order {work_order_id}")
    return wo


def _series(asset_id: str, window_min: int = 180) -> dict:
    path = TEL_DIR / f"{asset_id}.jsonl"
    if not path.exists():
        raise ToolError(f"no telemetry file for {asset_id}")
    return read_telemetry_file(path, _now(), window_min=window_min)


@srv.tool()
def health() -> dict:
    """Liveness probe used by the device's link monitor."""
    return {"place": "edge", "ok": True, "at": now_iso()}


@srv.tool()
def get_live_telemetry(asset_id: str, window_min: int = 30) -> dict:
    """Latest readings and alarms, read from the gateway's telemetry file."""
    t = _series(asset_id, window_min)
    latest = {s["signal"]: {"value": round(s["points"][-1]["value"], 2), "unit": s["unit"]} for s in t["series"] if s["points"]}
    return {"place": "edge", "source": f"{asset_id}.jsonl", "latest": latest, "alarms": t["alarms"][-3:]}


@srv.tool()
def diagnose_issue(work_order_id: str, symptoms: list[str] | None = None) -> dict:
    """Rank likely causes with the edge copy of the repair-rec model, on live readings from the file."""
    wo = _wo(work_order_id)
    a = next(x for x in demo_data()["assets"] if x["asset_id"] == wo["asset_id"])
    t = _series(a["asset_id"])
    readings, trends = features_from_series(t["series"], demo_data()["telemetry"][a["asset_id"]]["thresholds"])
    syms = list(dict.fromkeys((wo.get("symptoms") or []) + (symptoms or [])))
    return {"place": "edge", "model": "repair-rec (edge copy)", "inputs": "live readings from the gateway + symptoms",
            "causes": rank(a["model"], readings, trends, syms)[:3]}


@srv.tool()
def find_technicians(work_order_id: str) -> dict:
    """Depot roster snapshot (about 3 h old): provisional ranking."""
    return {"place": "edge", "freshness": "roster snapshot, ~3 h old (provisional)",
            "candidates": _wo(work_order_id)["technicians"][:3]}


@srv.tool()
def check_parts(work_order_id: str) -> dict:
    """Depot mirror: depot stock is live, other sources from the last snapshot."""
    lines = [{**l, "sources": [s for s in l["sources"] if s["source_type"] in ("van", "depot")]}
             for l in _wo(work_order_id)["parts"]["lines"]]
    return {"place": "edge", "freshness": "depot mirror", "lines": lines}


@srv.tool()
def recommend_repair(work_order_id: str, question: str = "") -> dict:
    """Repair recommendation from the edge's copy of the manuals: retrieval only, no LLM."""
    return {"place": "edge", **manual_agent().retrieval_only(work_order_id, question,
                                                             reason="edge: retrieval only (no LLM at the edge in this demo)")}


@srv.tool()
def explain(facts: str, question: str = "") -> dict:
    """Write a short answer (stands in for the edge LLM)."""
    return {"place": "edge", "model": "edge-local-14b (simulated: templated text, no LLM call)", "answer": facts}


@srv.tool()
def status() -> dict:
    return {"place": "edge", "telemetry_files": len(list(TEL_DIR.glob("*.jsonl"))), "features_pushed": STATE["pushed"],
            "push_failed": STATE["push_failed"], "buffered": len(STATE["buffer"])}


async def push_features() -> None:
    """Store-and-forward: summarize the open work orders' compressors and send to the cloud."""
    assets = sorted({w["asset_id"] for w in demo_data()["work_orders"]})
    while True:
        await asyncio.sleep(4)
        for aid in assets:
            t = _series(aid, 30)
            feats = {s["signal"]: round(s["points"][-1]["value"], 2) for s in t["series"] if s["points"]}
            STATE["buffer"].append({"asset_id": aid, "ts": now_iso(), "features": feats})
        STATE["buffer"] = STATE["buffer"][-200:]
        try:
            async with Client(url("edge-cloud"), read_timeout_seconds=3) as c:
                while STATE["buffer"]:
                    item = STATE["buffer"][0]
                    await asyncio.wait_for(c.call_tool("ingest_features", item), timeout=3)
                    STATE["buffer"].pop(0)
                    STATE["pushed"] += 1
        except Exception:  # noqa: BLE001  link down or flapping: keep the buffer
            STATE["push_failed"] += 1


async def serve() -> None:
    app = srv.streamable_http_app(stateless_http=True, json_response=True)
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT["edge"], log_level="warning"))
    task = asyncio.create_task(push_features())
    try:
        await server.serve()
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def main() -> None:
    TEL_DIR.mkdir(parents=True, exist_ok=True)
    t = time.time()
    export_telemetry_files(generate_fleet(seed=SEED), TEL_DIR, SIM_EPOCH, hours=13, step_min=5)
    print(f"edge: MCP on http://{HOST}:{PORT['edge']}/mcp, telemetry files in {TEL_DIR} ({time.time() - t:.1f} s)", flush=True)
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:  # stopped by the launcher
        pass


if __name__ == "__main__":
    main()
