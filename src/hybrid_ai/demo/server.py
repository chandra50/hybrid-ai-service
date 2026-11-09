"""Demo server: the dashboard plus a small JSON API over the repair recommendations database.

    PYTHONPATH=src python3 -m hybrid_ai.demo.server [--port 8765] [--db data/repair_recommendations.db] [--reset]

Endpoints
    GET  /api/health
    GET  /api/recommendations[?technician_id=TEC-0001]
    GET  /api/recommendations/<WO>
    POST /api/recommendations/<WO>/steps/<seq>   {"status", "by", "idempotency_key", "at"?, "note"?, "origin_tier"?}
    POST /api/recommendations/<WO>/assign        {"technician_id"}
    POST /api/recommendations/<WO>/outcome       {"confirmed_cause", "by", "notes"?, "first_time_fix"?}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import repair_db
from .build_data import build

ROOT = Path(__file__).resolve().parents[3]


class Handler(SimpleHTTPRequestHandler):
    conn = None
    lock = threading.Lock()

    def end_headers(self):
        # make browsers revalidate the dashboard files, so a rebuilt page shows up on reload
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):  # quieter console
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def _json(self, code: int, body) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlparse(self.path)
        if not u.path.startswith("/api/"):
            return super().do_GET()
        with self.lock:
            if u.path == "/api/health":
                n = self.conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0]
                return self._json(200, {"ok": True, "recommendations": n, "store": "sqlite"})
            if u.path == "/api/recommendations":
                tech = parse_qs(u.query).get("technician_id", [None])[0]
                return self._json(200, repair_db.list_plans(self.conn, tech))
            m = re.fullmatch(r"/api/recommendations/([A-Z0-9-]+)", u.path)
            if m:
                plan = repair_db.get_plan(self.conn, m.group(1))
                return self._json(200, plan) if plan else self._json(404, {"error": "not found"})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        try:
            body = self._body()
            with self.lock:
                m = re.fullmatch(r"/api/recommendations/([A-Z0-9-]+)/steps/(\d+)", u.path)
                if m:
                    res = repair_db.update_step(self.conn, m.group(1), int(m.group(2)), body["status"], body["by"],
                                                body["idempotency_key"], body.get("at"), body.get("note"),
                                                body.get("origin_tier", "device"))
                    return self._json(200, res)
                m = re.fullmatch(r"/api/recommendations/([A-Z0-9-]+)/assign", u.path)
                if m:
                    repair_db.assign(self.conn, m.group(1), body["technician_id"])
                    return self._json(200, {"ok": True})
                m = re.fullmatch(r"/api/recommendations/([A-Z0-9-]+)/outcome", u.path)
                if m:
                    repair_db.record_outcome(self.conn, m.group(1), body["confirmed_cause"], body["by"],
                                             body.get("notes", ""), body.get("first_time_fix", True), body.get("at"))
                    return self._json(200, {"ok": True})
        except KeyError as e:
            return self._json(404 if "WO-" in str(e) else 400, {"error": f"missing or unknown: {e}"})
        except (ValueError, json.JSONDecodeError) as e:
            return self._json(400, {"error": str(e)})
        return self._json(404, {"error": "not found"})


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default=os.environ.get("HYBRID_BIND", "127.0.0.1"),
                    help="address to listen on (default 127.0.0.1; set HYBRID_BIND or --host 0.0.0.0 to expose it)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--db", default=str(ROOT / "data" / "repair_recommendations.db"))
    ap.add_argument("--reset", action="store_true", help="rebuild the database from the simulator")
    args = ap.parse_args(argv)

    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    fresh = args.reset or not db.exists()
    conn = repair_db.connect(db)
    if fresh or conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0] == 0:
        n = repair_db.populate(conn, build(args.seed))
        print(f"built {db} with {n} repair recommendations")
    Handler.conn = conn
    srv = ThreadingHTTPServer((args.host, args.port), partial(Handler, directory=str(ROOT / "dashboard")))
    print(f"serving dashboard + API on http://{args.host}:{args.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
