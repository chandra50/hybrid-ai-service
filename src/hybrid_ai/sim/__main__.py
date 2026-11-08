"""CLI for the simulators.

    python -m hybrid_ai.sim fleet --seed 42 --out data/fleet.json
    python -m hybrid_ai.sim faults --seed 42
    python -m hybrid_ai.sim telemetry AST-00007 --hours-after 48
    python -m hybrid_ai.sim telemetry-files --out data/telemetry --hours 24
    python -m hybrid_ai.sim scenarios
    python -m hybrid_ai.sim scenario remote_site_visit --probe-every 900
"""

from __future__ import annotations

import argparse
import json
from datetime import timedelta

from .fleet import SIM_EPOCH, generate_fleet
from .network import SCENARIOS, Link, NetworkSim
from .telemetry import export_telemetry_files, live_telemetry


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="hybrid-ai-sim", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=42)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fleet", help="generate a fleet and write it as JSON")
    p.add_argument("--out", default="data/fleet.json")

    sub.add_parser("faults", help="list assets with an active (hidden) fault")

    p = sub.add_parser("telemetry", help="print live telemetry for an asset")
    p.add_argument("asset_id")
    p.add_argument("--hours-after", type=float, default=0.0, help="hours after the sim epoch")
    p.add_argument("--window-min", type=int, default=30)

    p = sub.add_parser("telemetry-files", help="export per-asset JSONL telemetry files (edge demo input)")
    p.add_argument("--out", default="data/telemetry")
    p.add_argument("--hours", type=float, default=24.0, help="hours of data starting at the sim epoch")
    p.add_argument("--step-min", type=int, default=1)

    sub.add_parser("scenarios", help="list network scenarios")

    p = sub.add_parser("scenario", help="walk a network scenario and probe each link")
    p.add_argument("name", choices=sorted(SCENARIOS))
    p.add_argument("--probe-every", type=int, default=1800, help="seconds between probes")
    p.add_argument("--bytes", type=int, default=4_000, help="probe payload size")

    args = ap.parse_args(argv)

    if args.cmd == "fleet":
        fleet = generate_fleet(seed=args.seed)
        path = fleet.save(args.out)
        print(f"wrote {path}: {len(fleet.sites)} sites, {len(fleet.assets)} assets, "
              f"{len(fleet.technicians)} technicians, {len(fleet.repair_history)} repairs, "
              f"{len(fleet.manuals)} manual sections, {len(fleet.work_orders)} open work orders")

    elif args.cmd == "faults":
        fleet = generate_fleet(seed=args.seed)
        reported = {w.asset_id for w in fleet.work_orders}
        for aid, f in fleet.active_faults.items():
            a = fleet.asset(aid)
            tag = "reported" if aid in reported else "silent  "
            print(f"{aid}  {a.model:<13} {fleet.site(a.site_id).region:<18} {tag}  {f['cause_code']}")

    elif args.cmd == "telemetry":
        fleet = generate_fleet(seed=args.seed)
        at = SIM_EPOCH + timedelta(hours=args.hours_after)
        print(json.dumps(live_telemetry(fleet, args.asset_id, at, window_min=args.window_min), indent=2))

    elif args.cmd == "telemetry-files":
        fleet = generate_fleet(seed=args.seed)
        paths = export_telemetry_files(fleet, args.out, SIM_EPOCH, hours=args.hours, step_min=args.step_min)
        print(f"wrote {len(paths)} files to {args.out} ({args.hours} h at {args.step_min}-min resolution)")

    elif args.cmd == "scenarios":
        for s in SCENARIOS.values():
            print(f"{s.name:<20} {s.duration_s // 3600:>3} h  {s.description}")

    elif args.cmd == "scenario":
        sim = NetworkSim(SCENARIOS[args.name], seed=args.seed)
        links = list(Link)
        print("t(h)  mode  M6  " + "  ".join(f"{l.value:>12}" for l in links))
        for t in range(0, sim.scenario.duration_s, args.probe_every):
            cells = []
            for link in links:
                d = sim.transmit(link, args.bytes, t, deadline_ms=10_000)
                cells.append(f"{(f'{d.latency_ms:.0f}ms' if d.ok else d.reason):>12}")
            print(f"{t / 3600:4.1f}  {sim.mode_at(t).value:<4}  {'Y' if sim.telemetry_lost_at(t) else '-'}   "
                  + "  ".join(cells))


if __name__ == "__main__":
    main()
