"""Synthetic equipment telemetry with injectable faults.

Readings are deterministic for (seed, asset, signal, minute), so the same
query always returns the same data. Assets with an active fault drift
linearly from onset to full effect over ``hours_to_full``; alarms fire when
warn/trip thresholds are crossed.

Output matches the ``get_live_telemetry`` contract result.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import catalog as cat
from .fleet import Fleet


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def fault_progress(fleet: Fleet, asset_id: str, at: datetime) -> float:
    """0.0 (healthy) .. 1.0 (fully developed fault)."""
    f = fleet.active_faults.get(asset_id)
    if not f:
        return 0.0
    elapsed_h = (at - _parse(f["onset"])).total_seconds() / 3600
    return min(max(elapsed_h / f["hours_to_full"], 0.0), 1.0)


def reading(fleet: Fleet, asset_id: str, signal: cat.Signal, at: datetime) -> float:
    minute = int(at.timestamp() // 60)
    rng = random.Random(f"{fleet.seed}:{asset_id}:{signal.name}:{minute}")
    value = signal.baseline + rng.gauss(0, signal.noise)
    f = fleet.active_faults.get(asset_id)
    if f:
        _, fm = cat.failure_mode(f["cause_code"])
        drift = fm.effects.get(signal.name, 0.0)
        value += signal.baseline * drift * fault_progress(fleet, asset_id, at)
    return round(value, 3)


def _alarm(signal: cat.Signal, value: float) -> tuple[str, str] | None:
    def crossed(limit: float | None) -> bool:
        if limit is None:
            return False
        return value <= limit if signal.low_is_bad else value >= limit

    if crossed(signal.trip):
        return "critical", "TRIP"
    if crossed(signal.warn):
        return "medium", "WARN"
    return None


def live_telemetry(
    fleet: Fleet,
    asset_id: str,
    at: datetime,
    signals: list[str] | None = None,
    window_min: int = 60,
    step_min: int = 1,
) -> dict[str, Any]:
    asset = fleet.asset(asset_id)
    model = cat.MODELS_BY_NAME[asset.model]
    wanted = [s for s in model.signals if not signals or s.name in signals]
    start = at - timedelta(minutes=window_min)

    series, alarms = [], []
    for sig in wanted:
        points = []
        last_state = None
        t = start
        while t <= at:
            v = reading(fleet, asset_id, sig, t)
            points.append({"ts": _iso(t), "value": v})
            state = _alarm(sig, v)
            if state and state != last_state:  # alarm on transition only
                sev, kind = state
                alarms.append({
                    "code": f"{sig.name.upper()}_{kind}",
                    "ts": _iso(t),
                    "severity": sev,
                    "message": f"{sig.name} = {v} {sig.unit} ({kind.lower()} limit "
                               f"{sig.trip if kind == 'TRIP' else sig.warn})",
                })
            last_state = state
            t += timedelta(minutes=step_min)
        series.append({"signal": sig.name, "unit": sig.unit, "points": points})

    return {"asset_id": asset_id, "series": series, "alarms": alarms}


# -- file-based telemetry (demo stand-in for OPC-UA / Modbus / MQTT) -------

def export_telemetry_files(
    fleet: Fleet,
    out_dir: str | Path,
    start: datetime,
    hours: float = 24.0,
    step_min: int = 1,
) -> list[Path]:
    """Write one JSONL file per asset: reading lines plus alarm lines.

    Each line is either
      {"type": "reading", "ts", "signal", "unit", "value"} or
      {"type": "alarm", "ts", "code", "severity", "message"}.
    The edge telemetry MCP server replays these files.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    window = int(hours * 60)
    end = start + timedelta(minutes=window)
    paths = []
    for asset in fleet.assets:
        data = live_telemetry(fleet, asset.asset_id, end, window_min=window, step_min=step_min)
        lines = []
        for s in data["series"]:
            for pt in s["points"]:
                lines.append({"type": "reading", "ts": pt["ts"], "signal": s["signal"],
                              "unit": s["unit"], "value": pt["value"]})
        lines += [{"type": "alarm", **a} for a in data["alarms"]]
        lines.sort(key=lambda r: (r["ts"], r["type"]))
        path = out / f"{asset.asset_id}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
        paths.append(path)
    return paths


def read_telemetry_file(
    path: str | Path,
    at: datetime,
    window_min: int = 60,
    signals: list[str] | None = None,
) -> dict[str, Any]:
    """Read a JSONL telemetry file and return a ``get_live_telemetry`` result."""
    path = Path(path)
    start = at - timedelta(minutes=window_min)
    series: dict[str, dict[str, Any]] = {}
    alarms = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            ts = _parse(rec["ts"])
            if not start <= ts <= at:
                continue
            if rec["type"] == "reading":
                if signals and rec["signal"] not in signals:
                    continue
                s = series.setdefault(rec["signal"], {"signal": rec["signal"], "unit": rec["unit"], "points": []})
                s["points"].append({"ts": rec["ts"], "value": rec["value"]})
            elif rec["type"] == "alarm":
                alarms.append({k: rec[k] for k in ("code", "ts", "severity", "message") if k in rec})
    return {"asset_id": path.stem, "series": list(series.values()), "alarms": alarms}
