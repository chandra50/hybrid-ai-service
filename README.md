# hybrid-ai

MCP-based agents for maintaining a large fleet of industrial equipment across
California. The system keeps working when the network is slow, intermittent, or
gone, and when the cloud AI is unavailable.

See [docs/DESIGN.md](docs/DESIGN.md) for the architecture: four tiers (edge,
field, hub, cloud), one MCP contract shared by all of them, and operating modes
M0–M6.

## Status: phase 1, contracts and simulators

| Piece | Where | What it does |
|-------|-------|-------------|
| MCP tool contracts | `src/hybrid_ai/contracts/tools.json` | JSON Schemas for the 8 tools, shared by every tier |
| Contract helpers | `src/hybrid_ai/contracts/__init__.py` | Validate inputs/responses; wrap results in the provenance envelope (`source_tier`, `as_of`, `staleness_s`, `confidence`, `authoritative`) |
| Fleet simulator | `src/hybrid_ai/sim/fleet.py`, `catalog.py` | Deterministic CA fleet: 6 depots, sites with coverage quality, 5 equipment models with failure modes, technicians with skills, stock on trucks/depots/warehouse, repair history, manuals, open work orders, hidden ground-truth faults |
| Telemetry simulator | `src/hybrid_ai/sim/telemetry.py` | Sensor readings with faults that drift in over time, plus warn/trip alarms |
| Network fault injector | `src/hybrid_ai/sim/network.py` | Modes M0–M5 per link, an M6 sensor-loss overlay, and named scenarios (remote site visit, PSPS outage, cloud model outage, satellite backup, sensor failure) |

## Quick start

Requires Python 3.11+ and `jsonschema`.

```bash
export PYTHONPATH=src
```

```bash
python3 -m unittest discover -s tests
```

```bash
python3 -m hybrid_ai.sim fleet --out data/fleet.json
```

```bash
python3 -m hybrid_ai.sim faults
```

```bash
python3 -m hybrid_ai.sim telemetry AST-00004 --hours-after 48 --window-min 10
```

```bash
python3 -m hybrid_ai.sim scenario psps_outage --probe-every 3600
```

Or install it as a package with `pip install -e .[dev]` and use the `hybrid-ai-sim` command.

## Next: phase 2

A cloud-tier MVP in mode M0. Real MCP servers built on the official SDK and
backed by the simulated fleet, an orchestrator, and specialist agents running
workflows W1–W4 end to end with human approval.
