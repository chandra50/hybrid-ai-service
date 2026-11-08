"""Repair recommendations database (SQLite).

Each work order's agent plan is stored as a repair recommendation: ranked
causes, an ordered step-by-step repair plan, recommended parts, and knowledge
references (manual sections, past repairs). The assigned technician works
through the steps; each step update is an idempotent event, so updates queued
offline can be replayed safely when the device reconnects.

In the hybrid design this database sits behind the cloud work-orders MCP
server. A read-only copy of each assigned plan travels in the technician's
mission pack.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendations (
    work_order_id          TEXT PRIMARY KEY,
    asset_id               TEXT NOT NULL,
    model                  TEXT NOT NULL,
    category               TEXT NOT NULL,
    site_name              TEXT NOT NULL,
    priority               TEXT NOT NULL,
    status                 TEXT NOT NULL,           -- awaiting_approval | assigned | in_progress | completed
    assigned_technician_id TEXT,
    generated_by           TEXT NOT NULL,           -- which model / agents produced the plan
    model_version          TEXT,                    -- repair recommendation model that ranked the causes
    model_confidence       REAL,                    -- probability of the top cause
    source_tier            TEXT NOT NULL,
    confidence             TEXT NOT NULL,
    cause_code             TEXT NOT NULL,
    cause_description      TEXT NOT NULL,
    severity               TEXT NOT NULL,
    safe_to_run            INTEGER NOT NULL,
    safety_override        INTEGER NOT NULL,
    repair_location        TEXT NOT NULL,
    workshop_id            TEXT,
    location_note          TEXT,
    est_hours              REAL NOT NULL,
    skills                 TEXT NOT NULL,           -- JSON list
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    version                INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS recommendation_causes (
    work_order_id TEXT NOT NULL REFERENCES recommendations(work_order_id),
    rank          INTEGER NOT NULL,
    cause_code    TEXT NOT NULL,
    description   TEXT NOT NULL,
    probability   REAL NOT NULL,
    PRIMARY KEY (work_order_id, rank)
);
CREATE TABLE IF NOT EXISTS repair_steps (
    work_order_id TEXT NOT NULL REFERENCES recommendations(work_order_id),
    seq           INTEGER NOT NULL,
    phase         TEXT NOT NULL,                    -- safety | verify | repair | test | closeout
    instruction   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'todo',     -- todo | done | skipped
    done_at       TEXT,
    done_by       TEXT,
    note          TEXT,
    PRIMARY KEY (work_order_id, seq)
);
CREATE TABLE IF NOT EXISTS recommended_parts (
    work_order_id TEXT NOT NULL REFERENCES recommendations(work_order_id),
    part_number   TEXT NOT NULL,
    description   TEXT NOT NULL,
    qty           INTEGER NOT NULL,
    source_type   TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    unit_price    INTEGER NOT NULL,
    PRIMARY KEY (work_order_id, part_number)
);
CREATE TABLE IF NOT EXISTS knowledge_refs (
    work_order_id TEXT NOT NULL REFERENCES recommendations(work_order_id),
    kind          TEXT NOT NULL,                    -- manual | asset_repair | similar_repair
    ref_id        TEXT NOT NULL,
    title         TEXT NOT NULL,
    detail        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS step_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    work_order_id   TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    status          TEXT NOT NULL,
    at              TEXT NOT NULL,
    by              TEXT NOT NULL,
    note            TEXT,
    origin_tier     TEXT NOT NULL,                  -- where the update was made (device = offline)
    received_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS repair_outcomes (
    work_order_id   TEXT PRIMARY KEY REFERENCES recommendations(work_order_id),
    confirmed_cause TEXT NOT NULL,
    notes           TEXT,
    first_time_fix  INTEGER NOT NULL,
    completed_at    TEXT NOT NULL,
    completed_by    TEXT NOT NULL
);
"""

STEP_STATUSES = {"todo", "done", "skipped"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def plan_steps(wo: dict[str, Any], loto: list[str], signals: list[str]) -> list[tuple[str, str]]:
    """Ordered (phase, instruction) steps for a work order's recommendation."""
    top = wo["diagnosis"]["causes"][0]
    steps: list[tuple[str, str]] = [("safety", s) for s in loto]
    evidence = "; ".join(wo["diagnosis"]["evidence"][:2]) or "the reported symptoms"
    steps.append(("verify", f"Confirm the diagnosis ({top['description']}): check {evidence}."))
    steps += [("repair", s) for s in wo["procedure"]]
    if wo["parts"]["lines"]:
        steps.append(("repair", "Fit parts: " + ", ".join(f"{p['qty']} x {p['part_number']} ({p['description']})"
                                                            for p in wo["parts"]["lines"]) + "."))
    sig = ", ".join(signals[:3])
    steps.append(("test", f"Remove locks, restart and run loaded for 15 minutes; confirm {sig} are back within limits."))
    steps.append(("closeout", "Record the confirmed cause, parts used and photos, then complete the work order."))
    return steps


def populate(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    """Load every work order plan from build_data.build() output into the database."""
    assets = {a["asset_id"]: a for a in data["assets"]}
    created = data["generated"]["now"]
    all_history = [(aid, r) for aid, rs in data["history"].items() for r in rs]
    with conn:
        for table in ("step_events", "repair_outcomes", "knowledge_refs", "recommended_parts", "repair_steps",
                      "recommendation_causes", "recommendations"):
            conn.execute(f"DELETE FROM {table}")
        for wo in data["work_orders"]:
            a = assets[wo["asset_id"]]
            d, top, loc = wo["diagnosis"], wo["diagnosis"]["causes"][0], wo["location"]
            conn.execute(
                "INSERT INTO recommendations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (wo["work_order_id"], a["asset_id"], a["model"], a["category"], a["site_name"], wo["priority"],
                 wo["status"], wo["assigned_technician_id"], f"{d.get('model_version', 'rules')} model + planning rules",
                 d.get("model_version"), d.get("model_confidence"), "cloud",
                 "confirmed", top["cause_code"], top["description"], d["severity"], int(d["safe_to_run"]),
                 int(d["safety_override"]), loc["location"], loc.get("workshop_id"), loc.get("note"),
                 wo["est_hours"], json.dumps(wo["skills_required"]), created, created, 1))
            for i, c in enumerate(d["causes"], start=1):
                conn.execute("INSERT INTO recommendation_causes VALUES (?,?,?,?,?)",
                             (wo["work_order_id"], i, c["cause_code"], c["description"], c["probability"]))
            signals = list(data["telemetry"][a["asset_id"]]["thresholds"])
            for seq, (phase, text) in enumerate(plan_steps(wo, data["loto"], signals), start=1):
                conn.execute("INSERT INTO repair_steps (work_order_id, seq, phase, instruction) VALUES (?,?,?,?)",
                             (wo["work_order_id"], seq, phase, text))
            for p in wo["parts"]["lines"]:
                conn.execute("INSERT INTO recommended_parts VALUES (?,?,?,?,?,?,?)",
                             (wo["work_order_id"], p["part_number"], p["description"], p["qty"], p["pick_type"],
                              p["pick"], p["unit_price"]))
            for m in data["manuals"].get(a["model"], []):
                if top["cause_code"] in m["text"] or "lockout" in m["title"].lower():
                    conn.execute("INSERT INTO knowledge_refs VALUES (?,?,?,?,?)",
                                 (wo["work_order_id"], "manual", m["doc_id"], m["title"], m["text"]))
            for r in data["history"].get(a["asset_id"], [])[:3]:
                conn.execute("INSERT INTO knowledge_refs VALUES (?,?,?,?,?)",
                             (wo["work_order_id"], "asset_repair", f"{a['asset_id']}:{r['date']}",
                              f"{r['date']} · {r['cause_code']} on this asset", r["notes"]))
            similar = [(aid, r) for aid, r in all_history
                       if r["cause_code"] == top["cause_code"] and aid != a["asset_id"] and r["first_time_fix"]][:3]
            for aid, r in similar:
                conn.execute("INSERT INTO knowledge_refs VALUES (?,?,?,?,?)",
                             (wo["work_order_id"], "similar_repair", f"{aid}:{r['date']}",
                              f"{r['date']} · same fault on {aid} (first-time fix)", r["notes"]))
    return len(data["work_orders"])


def _rows(cur) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


def list_plans(conn: sqlite3.Connection, technician_id: str | None = None) -> list[dict[str, Any]]:
    sql = """SELECT r.work_order_id, r.asset_id, r.model, r.site_name, r.priority, r.status,
                    r.assigned_technician_id, r.cause_code, r.cause_description, r.version,
                    SUM(s.status = 'done') AS steps_done, COUNT(s.seq) AS steps_total
             FROM recommendations r JOIN repair_steps s USING (work_order_id)"""
    args: tuple = ()
    if technician_id:
        sql += " WHERE r.assigned_technician_id = ?"
        args = (technician_id,)
    sql += " GROUP BY r.work_order_id ORDER BY r.work_order_id"
    return _rows(conn.execute(sql, args))


def get_plan(conn: sqlite3.Connection, work_order_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM recommendations WHERE work_order_id = ?", (work_order_id,)).fetchone()
    if row is None:
        return None
    plan = dict(row)
    plan["skills"] = json.loads(plan["skills"])
    plan["safe_to_run"], plan["safety_override"] = bool(plan["safe_to_run"]), bool(plan["safety_override"])
    q = lambda sql: _rows(conn.execute(sql, (work_order_id,)))  # noqa: E731
    plan["causes"] = q("SELECT rank, cause_code, description, probability FROM recommendation_causes "
                       "WHERE work_order_id = ? ORDER BY rank")
    plan["steps"] = q("SELECT seq, phase, instruction, status, done_at, done_by, note FROM repair_steps "
                      "WHERE work_order_id = ? ORDER BY seq")
    plan["parts"] = q("SELECT part_number, description, qty, source_type, source_id, unit_price FROM recommended_parts "
                      "WHERE work_order_id = ?")
    plan["references"] = q("SELECT kind, ref_id, title, detail FROM knowledge_refs WHERE work_order_id = ?")
    out = conn.execute("SELECT * FROM repair_outcomes WHERE work_order_id = ?", (work_order_id,)).fetchone()
    plan["outcome"] = dict(out) if out else None
    return plan


def update_step(conn: sqlite3.Connection, work_order_id: str, seq: int, status: str, by: str,
                idempotency_key: str, at: str | None = None, note: str | None = None,
                origin_tier: str = "device") -> dict[str, Any]:
    """Apply a step update once. Replaying the same idempotency key is a no-op."""
    if status not in STEP_STATUSES:
        raise ValueError(f"status must be one of {sorted(STEP_STATUSES)}")
    if conn.execute("SELECT 1 FROM repair_steps WHERE work_order_id = ? AND seq = ?", (work_order_id, seq)).fetchone() is None:
        raise KeyError(f"{work_order_id} step {seq}")
    at = at or _now()
    with conn:
        try:
            conn.execute("INSERT INTO step_events (idempotency_key, work_order_id, seq, status, at, by, note, origin_tier, "
                         "received_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         (idempotency_key, work_order_id, seq, status, at, by, note, origin_tier, _now()))
        except sqlite3.IntegrityError:
            return {"applied": False, "duplicate": True}
        conn.execute("UPDATE repair_steps SET status = ?, done_at = ?, done_by = ?, note = COALESCE(?, note) "
                     "WHERE work_order_id = ? AND seq = ?", (status, at, by, note, work_order_id, seq))
        conn.execute("UPDATE recommendations SET status = CASE WHEN status = 'assigned' THEN 'in_progress' ELSE status END, "
                     "updated_at = ?, version = version + 1 WHERE work_order_id = ?", (_now(), work_order_id))
    return {"applied": True, "duplicate": False}


def assign(conn: sqlite3.Connection, work_order_id: str, technician_id: str) -> None:
    with conn:
        n = conn.execute("UPDATE recommendations SET assigned_technician_id = ?, status = 'assigned', updated_at = ?, "
                         "version = version + 1 WHERE work_order_id = ?", (technician_id, _now(), work_order_id)).rowcount
    if not n:
        raise KeyError(work_order_id)


def record_outcome(conn: sqlite3.Connection, work_order_id: str, confirmed_cause: str, by: str,
                   notes: str = "", first_time_fix: bool = True, at: str | None = None) -> None:
    with conn:
        conn.execute("INSERT OR REPLACE INTO repair_outcomes VALUES (?,?,?,?,?,?)",
                     (work_order_id, confirmed_cause, notes, int(first_time_fix), at or _now(), by))
        conn.execute("UPDATE recommendations SET status = 'completed', updated_at = ?, version = version + 1 "
                     "WHERE work_order_id = ?", (_now(), work_order_id))
