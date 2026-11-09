"""Device place: the technician tablet's backend.

  - Router: every request goes here. It tries places in the tool's policy order for
    the *detected* mode, with a deadline per attempt, and falls back on failure.
    Remote places are reached over MCP, through the network simulator.
  - Link monitor: probes the cloud and the edge every 1.5 s and classifies the mode
    from real results (success rate and round-trip time), not from a setting.
  - Mission pack DB (SQLite): copy of the assigned repair plan, synced when online.
  - Outbox (SQLite): writes that can't reach the cloud are queued with an idempotency
    key and replayed in priority order (P0 first, P4 photos only when Online).
  - Local tools: device copy of the repair-rec model (symptoms only), van stock,
    plan copy, knowledge search, a stand-in for the device LLM.

Serves the dashboard and a JSON API for the live page (dashboard/live.html).
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import sqlite3
import time
import uuid
from typing import Any

import urllib.request
import uvicorn
from mcp.client.client import Client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .common import DATA_DIR, HOST, PORT, ROOT, assigned_job, demo_data, now_iso, rank, url

DEADLINE = {"cloud": 3.0, "edge": 2.0}
POLICY = {  # tool -> mode -> places in order
    "diagnose_issue": {"ONLINE": ["cloud", "edge", "device"], "LIMITED": ["edge", "device"], "OFFLINE": ["edge", "device"]},
    "get_live_telemetry": {"ONLINE": ["edge"], "LIMITED": ["edge"], "OFFLINE": ["edge"]},
    "find_technicians": {"ONLINE": ["cloud"], "LIMITED": ["cloud", "edge"], "OFFLINE": []},
    "recommend_repair_location": {"ONLINE": ["cloud", "device"], "LIMITED": ["device"], "OFFLINE": ["device"]},
    "check_parts": {"ONLINE": ["cloud", "edge", "device"], "LIMITED": ["cloud", "edge", "device"], "OFFLINE": ["edge", "device"]},
    "get_repair_plan": {"ONLINE": ["cloud", "device"], "LIMITED": ["cloud", "device"], "OFFLINE": ["device"]},
    "explain": {"ONLINE": ["cloud", "edge", "device"], "LIMITED": ["edge", "device"], "OFFLINE": ["edge", "device"]},
    "search_knowledge": {"ONLINE": ["device"], "LIMITED": ["device"], "OFFLINE": ["device"]},
}
WRITES = {"update_step": "P1", "record_outcome": "P1", "reserve_parts": "P1", "upload_photo": "P4"}
WHY = {
    "ONLINE": "Online: cloud first",
    "LIMITED": "Limited: local first, cloud only within its deadline",
    "OFFLINE": "Offline: only the edge (local link) and the device",
}


class Device:
    def __init__(self):
        self.db: sqlite3.Connection | None = None
        self.probes = {"cloud": collections.deque(maxlen=6), "edge": collections.deque(maxlen=4)}
        self.log: list[dict[str, Any]] = []
        self.seq = 0
        self.job = assigned_job()
        tech = next(t for t in demo_data()["technicians"] if t["technician_id"] == self.job["assigned_technician_id"])
        self.tech = tech
        self.van = {p["part_number"]: p["qty"] for p in tech["van_stock"]}

    # ---------------------------------------------------------------- storage
    def open(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / "device.db"
        path.unlink(missing_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE mission_pack (work_order_id TEXT PRIMARY KEY, plan TEXT NOT NULL, synced_at TEXT NOT NULL);
            CREATE TABLE outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE, prio TEXT, tool TEXT, args TEXT,
                                 label TEXT, created TEXT, status TEXT DEFAULT 'queued', attempts INTEGER DEFAULT 0,
                                 synced_at TEXT, result TEXT);
        """)

    # ---------------------------------------------------------------- mode detection
    def mode(self) -> str:
        c = list(self.probes["cloud"])
        if not c:
            return "OFFLINE"
        ok = [p for p in c if p["ok"]]
        if c[-1]["ok"] and len(ok) >= min(4, len(c)) and c[-1]["ms"] < 1000:
            return "ONLINE"
        return "LIMITED" if ok else "OFFLINE"

    def edge_ok(self) -> bool:
        e = list(self.probes["edge"])
        return bool(e) and e[-1]["ok"]

    # ---------------------------------------------------------------- remote calls
    async def remote(self, place: str, tool: str, args: dict) -> tuple[bool, Any, float, str]:
        route = {"cloud": "device-cloud", "edge": "device-edge"}[place]
        t = time.perf_counter()
        try:
            async def go():
                async with Client(url(route), read_timeout_seconds=DEADLINE[place]) as c:
                    return await c.call_tool(tool, args)
            res = await asyncio.wait_for(go(), timeout=DEADLINE[place])
            ms = (time.perf_counter() - t) * 1000
            text = res.content[0].text if res.content else "{}"
            if res.is_error:
                return False, None, ms, text[:160]
            return True, json.loads(text), ms, ""
        except asyncio.TimeoutError:
            return False, None, (time.perf_counter() - t) * 1000, f"timed out after {DEADLINE[place]:.0f} s"
        except Exception as e:  # noqa: BLE001  refused / cut by the network
            msg = str(e) or type(e).__name__
            if hasattr(e, "exceptions"):
                msg = "; ".join(str(x) or type(x).__name__ for x in e.exceptions)[:120]
            return False, None, (time.perf_counter() - t) * 1000, f"connection failed ({msg[:80]})"

    # ---------------------------------------------------------------- local tools
    def local(self, tool: str, args: dict) -> dict:
        wo = self.job
        a = next(x for x in demo_data()["assets"] if x["asset_id"] == wo["asset_id"])
        if tool == "diagnose_issue":
            syms = list(dict.fromkeys((wo.get("symptoms") or []) + (args.get("symptoms") or [])))
            return {"place": "device", "model": "repair-rec (device copy)", "inputs": "symptoms only (no live data)",
                    "causes": rank(a["model"], None, None, syms)[:3]}
        if tool == "check_parts":
            return {"place": "device", "freshness": "van stock", "lines": [
                {"part_number": l["part_number"], "description": l["description"], "qty": l["qty"],
                 "in_van": self.van.get(l["part_number"], 0)} for l in wo["parts"]["lines"]]}
        if tool == "recommend_repair_location":
            return {"place": "device", "location": wo["location"]["location"], "basis": "rule score on the device"}
        if tool == "get_repair_plan":
            row = self.db.execute("SELECT plan, synced_at FROM mission_pack WHERE work_order_id = ?", (wo["work_order_id"],)).fetchone()
            if not row:
                raise RuntimeError("no mission pack on the device yet")
            return {"place": "device", "copy_synced_at": row["synced_at"], "plan": json.loads(row["plan"])}
        if tool == "search_knowledge":
            q = (args.get("query") or "").lower()
            hits = [m for m in demo_data()["manuals"].get(a["model"], []) if not q or q in (m["title"] + m["text"]).lower()]
            return {"place": "device", "source": "mission pack", "hits": [{"title": m["title"]} for m in hits[:4]]}
        if tool == "explain":
            return {"place": "device", "model": "device-local-3b (simulated: templated text, no LLM call)", "answer": args.get("facts", "")}
        raise RuntimeError(f"no local implementation of {tool}")

    # ---------------------------------------------------------------- router
    async def call(self, tool: str, args: dict, who: str = "technician", request: str = "") -> dict:
        if tool == "get_live_telemetry":
            args = {"asset_id": self.job["asset_id"], **args}
        elif tool not in ("explain", "search_knowledge"):
            args = {"work_order_id": self.job["work_order_id"], **args}
        mode = self.mode()
        entry = {"id": self._id(), "t": now_iso(), "who": who, "request": request or tool, "tool": tool,
                 "mode": mode, "attempts": [], "place": None, "status": "failed", "why": "", "result": None}
        t0 = time.perf_counter()
        if tool in WRITES:
            await self._write(tool, args, entry, mode)
        else:
            order = POLICY.get(tool, {}).get(mode, [])
            if tool == "explain" and mode == "ONLINE" and not self.edge_ok():
                order = ["cloud", "device"]
            if tool in ("diagnose_issue", "explain") and mode != "ONLINE" and not self.edge_ok():
                order = [p for p in order if p != "edge"]
            entry["why"] = WHY[mode] + (" · edge not answering" if not self.edge_ok() else "")
            for place in order:
                if place == "device":
                    t = time.perf_counter()
                    try:
                        res = self.local(tool, args)
                        entry["attempts"].append({"place": "device", "ok": True, "ms": round((time.perf_counter() - t) * 1000, 1)})
                        entry.update(place="device", status="ok", result=res)
                        break
                    except Exception as e:  # noqa: BLE001
                        entry["attempts"].append({"place": "device", "ok": False, "ms": 0, "error": str(e)})
                        continue
                ok, res, ms, err = await self.remote(place, tool, args)
                entry["attempts"].append({"place": place, "ok": ok, "ms": round(ms), **({"error": err} if err else {})})
                if ok:
                    entry.update(place=place, status="ok", result=res)
                    break
            if not order:
                entry["why"] = f"{WHY[mode]} · {tool} needs the cloud; call the dispatcher"
        entry["ms"] = round((time.perf_counter() - t0) * 1000)
        self._log(entry)
        return entry

    async def _write(self, tool: str, args: dict, entry: dict, mode: str) -> None:
        args.setdefault("idempotency_key", f"dev-{uuid.uuid4().hex[:12]}")
        prio = "P0" if args.get("phase") == "safety" else WRITES[tool]
        args.pop("phase", None)
        if mode != "OFFLINE" and tool != "upload_photo":
            ok, res, ms, err = await self.remote("cloud", tool, args)
            entry["attempts"].append({"place": "cloud", "ok": ok, "ms": round(ms), **({"error": err} if err else {})})
            if ok:
                entry.update(place="cloud", status="ok", result=res, why=f"{WHY[mode]} · written to the cloud DB")
                return
        self.db.execute("INSERT INTO outbox (key, prio, tool, args, label, created) VALUES (?,?,?,?,?,?)",
                        (args["idempotency_key"], prio, tool, json.dumps(args), entry["request"], now_iso()))
        self.db.commit()
        entry.update(place="device", status="queued", why=f"{WHY[mode]} · queued in the outbox ({prio})",
                     result={"queued": True, "idempotency_key": args["idempotency_key"]})

    # ---------------------------------------------------------------- background loops
    async def monitor(self) -> None:
        while True:
            for place in ("cloud", "edge"):
                ok, _, ms, err = await self.remote(place, "health", {})
                self.probes[place].append({"ok": ok, "ms": round(ms), "at": now_iso(), "error": err})
            if self.mode() != "OFFLINE" and self.probes["cloud"][-1]["ok"]:
                await self.sync_pack()
                await self.replay()
            await asyncio.sleep(1.5)

    async def sync_pack(self) -> None:
        wo = self.job["work_order_id"]
        if self.db.execute("SELECT 1 FROM mission_pack WHERE work_order_id = ?", (wo,)).fetchone():
            return
        ok, res, ms, err = await self.remote("cloud", "get_repair_plan", {"work_order_id": wo})
        if ok:
            self.db.execute("INSERT OR REPLACE INTO mission_pack VALUES (?,?,?)", (wo, json.dumps(res["plan"]), now_iso()))
            self.db.commit()
            self._log({"id": self._id(), "t": now_iso(), "who": "sync", "request": f"Mission pack: copy plan {wo} to the device DB",
                       "tool": "get_repair_plan", "mode": self.mode(), "attempts": [{"place": "cloud", "ok": True, "ms": round(ms)}],
                       "place": "cloud", "status": "ok", "why": "Cloud reachable: P3 mission-pack download", "ms": round(ms), "result": None})

    async def replay(self) -> None:
        mode = self.mode()
        rows = self.db.execute("SELECT * FROM outbox WHERE status = 'queued' ORDER BY prio, id").fetchall()
        for r in rows:
            if r["prio"] == "P4" and mode != "ONLINE":
                continue
            if r["tool"] == "upload_photo":   # media store is not part of this demo: the upload is simulated
                ok, res, ms, err = True, {"uploaded": True, "bytes": 3_200_000, "simulated": True}, 0.0, ""
            else:
                ok, res, ms, err = await self.remote("cloud", r["tool"], json.loads(r["args"]))
            self.db.execute("UPDATE outbox SET attempts = attempts + 1 WHERE id = ?", (r["id"],))
            if not ok:
                self.db.commit()
                break
            self.db.execute("UPDATE outbox SET status = 'synced', synced_at = ?, result = ? WHERE id = ?",
                            (now_iso(), json.dumps(res), r["id"]))
            self.db.commit()
            self._log({"id": self._id(), "t": now_iso(), "who": "outbox", "request": f"Replay: {r['label']}", "tool": r["tool"],
                       "mode": mode, "attempts": [{"place": "cloud", "ok": True, "ms": round(ms)}], "place": "cloud", "status": "ok",
                       "why": f"Link back: {r['prio']} replayed; key {r['key']} keeps it single"
                              + (" (duplicate ignored)" if isinstance(res, dict) and res.get("duplicate") else ""),
                       "ms": round(ms), "result": res})

    # ---------------------------------------------------------------- helpers
    def _id(self) -> int:
        self.seq += 1
        return self.seq

    def _log(self, entry: dict) -> None:
        self.log.append(entry)
        self.log = self.log[-200:]

    def outbox(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT id, key, prio, tool, label, created, status, attempts, synced_at FROM outbox ORDER BY id DESC LIMIT 40")]


DEV = Device()


async def _direct(port_name: str, tool: str) -> dict | None:
    """Operator view: read a place's status directly, not through the field network."""
    try:
        async with Client(url(port_name), read_timeout_seconds=2) as c:
            r = await asyncio.wait_for(c.call_tool(tool, {}), timeout=2)
            return json.loads(r.content[0].text)
    except Exception:  # noqa: BLE001
        return None


def _http_json(url_: str, body: dict | None = None) -> dict | None:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url_, data=data, headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


async def api_state(request: Request) -> JSONResponse:
    net = await asyncio.to_thread(_http_json, f"http://{HOST}:{PORT['netsim']}/state")
    cloud, edge = await asyncio.gather(_direct("cloud", "status"), _direct("edge", "status"))
    pack = DEV.db.execute("SELECT work_order_id, synced_at FROM mission_pack").fetchall()
    return JSONResponse({
        "detected": {"mode": DEV.mode(), "cloud": list(DEV.probes["cloud"]), "edge": list(DEV.probes["edge"]), "edge_ok": DEV.edge_ok()},
        "net": net, "cloud": cloud, "edge": edge,
        "device": {"job": {k: DEV.job[k] for k in ("work_order_id", "asset_id", "title", "priority")},
                   "technician": DEV.tech["name"], "van": DEV.van, "mission_pack": [dict(r) for r in pack],
                   "outbox": DEV.outbox()},
        "log": DEV.log[-80:],
        "policy": POLICY,
    })


async def api_call(request: Request) -> JSONResponse:
    body = await request.json()
    entry = await DEV.call(body["tool"], body.get("args") or {}, body.get("who", "technician"), body.get("request", ""))
    return JSONResponse(entry)


async def api_net(request: Request) -> JSONResponse:
    body = await request.json()
    out = {}
    if "mode" in body or "sensors_lost" in body:
        out["net"] = await asyncio.to_thread(_http_json, f"http://{HOST}:{PORT['netsim']}/state",
                                             {k: body[k] for k in ("mode", "sensors_lost") if k in body})
    if "cloud_ai_down" in body:
        out["cloud"] = await asyncio.to_thread(_http_json, f"http://{HOST}:{PORT['cloud']}/control",
                                               {"cloud_ai_down": body["cloud_ai_down"]})
    return JSONResponse(out)


async def index(request: Request):
    return RedirectResponse("/live.html")


def make_app() -> Starlette:
    return Starlette(routes=[
        Route("/", index), Route("/api/state", api_state), Route("/api/call", api_call, methods=["POST"]),
        Route("/api/net", api_net, methods=["POST"]),
        Mount("/", StaticFiles(directory=str(ROOT / "dashboard"), html=True)),
    ])


async def serve() -> None:
    DEV.open()
    server = uvicorn.Server(uvicorn.Config(make_app(), host=HOST, port=PORT["device"], log_level="warning"))
    task = asyncio.create_task(DEV.monitor())
    print(f"device: live page on http://{HOST}:{PORT['device']}/live.html", flush=True)
    try:
        await server.serve()
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def main() -> None:
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:  # stopped by the launcher
        pass


if __name__ == "__main__":
    main()
