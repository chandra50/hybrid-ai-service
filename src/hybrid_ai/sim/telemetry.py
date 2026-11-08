"""Synthetic equipment telemetry with injectable faults.

Readings are deterministic for (seed, asset, signal, minute), so the same
query always returns the same data. Assets with an active fault drift
linearly from onset to full effect over ``hours_to_full``; alarms fire when
warn/trip thresholds are crossed.

Output matches the ``get_live_telemetry`` contract result.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
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
