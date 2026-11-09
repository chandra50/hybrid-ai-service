"""Shared settings for the live (multi-process) demo.

Four real processes on localhost:

    netsim  : TCP proxy that delays, flaps or cuts links by mode (control on base+10)
    cloud   : MCP server (base+1)  - repair DB, model registry, dispatch, ERP
    edge    : MCP server (base+2)  - telemetry from files, depot mirror, model copy
    device  : tablet backend (base+3) - router, link monitor, mission pack, outbox; serves the live page

Traffic between places goes through netsim:
    device -> cloud : base+11      device -> edge : base+12      edge -> cloud : base+13
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..envfile import load_env_file

load_env_file()   # e.g. ANTHROPIC_API_KEY from ~/.config/hybrid-ai/env

ROOT = Path(__file__).resolve().parents[3]
BASE = int(os.environ.get("HYBRID_PORT_BASE", "8800"))
DATA_DIR = Path(os.environ.get("HYBRID_LIVE_DIR", ROOT / "data" / "live"))
SEED = int(os.environ.get("HYBRID_SEED", "42"))

PORT = {
    "cloud": BASE + 1, "edge": BASE + 2, "device": BASE + 3,
    "netsim": BASE + 10, "device-cloud": BASE + 11, "device-edge": BASE + 12, "edge-cloud": BASE + 13,
}
HOST = "127.0.0.1"   # internal traffic between the places always stays on localhost
BIND = os.environ.get("HYBRID_BIND", "127.0.0.1")   # address the device web page listens on

for _name in ("httpx", "httpx2", "mcp", "mcp.client", "mcp.server"):
    logging.getLogger(_name).setLevel(logging.WARNING)


def url(port_name: str, path: str = "/mcp") -> str:
    return f"http://{HOST}:{PORT[port_name]}{path}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@lru_cache(maxsize=1)
def demo_data() -> dict[str, Any]:
    from ..demo.build_data import build
    return build(SEED)


@lru_cache(maxsize=1)
def repair_model():
    from ..demo.build_data import MODEL_PATH
    from ..models.repair_model import RepairModel
    return RepairModel.load(MODEL_PATH)


def assigned_job() -> dict[str, Any]:
    """The work order the device (tablet) belongs to: the first one assigned in the demo data."""
    return next(w for w in demo_data()["work_orders"] if w["assigned_technician_id"])


def features_from_series(series: list[dict[str, Any]], thresholds: dict[str, Any]) -> tuple[dict, dict]:
    readings = {s["signal"]: s["points"][-1]["value"] for s in series if s["points"]}
    trends = {s["signal"]: (s["points"][-1]["value"] - s["points"][0]["value"]) / thresholds[s["signal"]]["baseline"]
              for s in series if s["points"]}
    return readings, trends


def rank(asset_model: str, readings, trends, symptoms) -> list[dict[str, Any]]:
    return repair_model().predict(asset_model, readings, trends, symptoms)


_AGENT = None


def manual_agent():
    """One ManualAgent per process, over this place's copy of the manuals."""
    global _AGENT
    if _AGENT is None:
        from ..agents.manual_agent import ManualAgent
        _AGENT = ManualAgent(demo_data())
    return _AGENT


def dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))
