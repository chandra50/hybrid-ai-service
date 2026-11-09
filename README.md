# hybrid-ai

MCP-based agents for maintaining a fleet of industrial compressors across
California. The system keeps working when the network is slow, intermittent, or
gone, and when the cloud AI is unavailable.

See [docs/DESIGN.md](docs/DESIGN.md) for the architecture and the demo-scope decisions (§11): three places
(cloud, edge, device) that agents move between, one MCP contract shared by all of them, and three operating
modes (Online, Limited, Offline) plus two events (cloud AI outage, sensors lost).

## What's here

| Piece | Where | What it does |
|-------|-------|-------------|
| MCP tool contracts | `src/hybrid_ai/contracts/tools.json` | JSON Schemas for the 8 tools, shared by every tier |
| Contract helpers | `src/hybrid_ai/contracts/__init__.py` | Validate inputs/responses; wrap results in the provenance envelope (`source_tier`, `as_of`, `staleness_s`, `confidence`, `authoritative`) |
| Fleet simulator | `src/hybrid_ai/sim/fleet.py`, `catalog.py` | Deterministic CA fleet sized for the demo (6 depots with edge servers, 12 sites, ~30 compressors, 12 technicians), sites with coverage quality, 5 compressor types with failure modes, technicians with skills, stock in the vans/depots/warehouse, repair history, manuals, open work orders, hidden ground-truth faults |
| Telemetry simulator | `src/hybrid_ai/sim/telemetry.py` | Sensor readings with faults that drift in over time, plus warn/trip alarms. Exports per-asset JSONL files that the edge server replays (the demo stand-in for OPC-UA/Modbus/MQTT) |
| Repair recommendation model | `src/hybrid_ai/models/`, `models/repair-rec-1.0.json` | Small trained model (logistic regression per compressor type) that ranks causes from telemetry, symptoms and history. 9 KB, 94.5% top-1 on held-out simulated data; the same weights run in the cloud, at the edge, on the device and in the dashboard. Retrain with `PYTHONPATH=src python3 -m hybrid_ai.models` |
| Network fault injector | `src/hybrid_ai/sim/network.py` | Online / Limited / Offline per link, cloud-AI-outage and sensors-lost events, and named scenarios (remote site visit, PSPS outage, cloud AI outage, satellite backup, sensor failure) |

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
python3 -m hybrid_ai.sim telemetry-files --out data/telemetry --hours 24
```

```bash
python3 -m hybrid_ai.sim scenario psps_outage --probe-every 3600
```

Or install it as a package with `pip install -e .[dev]` and use the `hybrid-ai-sim` command.

## Live demo: real cloud, edge and device processes

Cloud and edge MCP servers, the device's router/outbox and a fault-injecting network proxy, as four real processes. See [docs/TECHNICAL.md](docs/TECHNICAL.md).

```bash
python3 -m venv .venv && .venv/bin/pip install -r deploy/requirements.txt
```

```bash
PYTHONPATH=src .venv/bin/python -m hybrid_ai.live
```

Open http://127.0.0.1:8803/live.html and click **Run the repair story**.

**Deploy on an Ubuntu server:** build a tarball with `tools/make_release.sh` and follow [DEPLOY.md](DEPLOY.md).

**Deploy on this machine** as two systemd user services (live demo + simulated dashboard, localhost only):

```bash
deploy/install.sh
```

## Demo dashboard

Presenting? Follow the 5-minute run sheet in [docs/DEMO.md](docs/DEMO.md).

A web dashboard on OpenStreetMap (Leaflet) with three personas:

- **Supervisor:** fleet map, KPIs, the work-order queue, and each order's agent plan (W1 diagnosis, W2 technician ranking, W3 repair location, W4 parts) with rule-based approvals. Every answer shows which tier answered, its confidence and its age.
- **Technician:** the assigned job with its **repair plan from the database** (lockout, verify, repair, test, close-out steps), plus diagnosis, mission pack, parts vs van stock, live data over the local link, close-out and an outbox.
- **Assigned tech walkthrough:** the assigned technician repairs a compressor step by step, from the depot, through a dead zone and back into coverage, following the database plan. Steps done offline reach the database when the link returns.

Also on every view:

- **Where agents run** (default tab next to the map): the Device, Edge and Cloud places with their agents and databases. Agents move between places as the mode changes and as requests run; requests and syncs animate along the links, and the database each request touches lights up.
- **Assistant** ("Ask" button): a minimal chat about the selected job. Each answer shows where it ran (cloud, edge or device model) and what it cost.
- **Live requests panel:** every request (screen actions, assistant questions, outbox replays) with the tool, where it ran, why it ran there, time taken and tokens in/out, plus totals by tier.
- **Hybrid modes:** switch Online / Limited / Offline, toggle the two events, or play a simulator scenario.

Run it with the API server, which builds the repair recommendations database (SQLite, `data/repair_recommendations.db`) on first start:

```bash
PYTHONPATH=src python3 -m hybrid_ai.demo.server --port 8765
```

Then open http://localhost:8765. Add `--reset` to rebuild the database. Map tiles need an internet connection. Without the server (for example a plain static server), the dashboard falls back to the plans embedded in `dashboard/data.js`. Regenerate that file with `PYTHONPATH=src python3 -m hybrid_ai.demo.build_data`.

## Slide decks

- [docs/hybrid-ai-brief.pptx](docs/hybrid-ai-brief.pptx): 8-slide brief covering the situation, the challenges and the solution, from the supervisor's and the repairing technician's points of view. [PDF version](docs/hybrid-ai-brief.pdf): the animated slide 5 is shown in its starting state. Rebuild the PDF from `python tools/build_brief_deck.py <out.pptx> --static`, then convert it.
- [docs/hybrid-ai-design.pptx](docs/hybrid-ai-design.pptx): 23-slide design overview, including how each hybrid mode is handled and the live demo (slide 13).

- [docs/agent-movement.pptx](docs/agent-movement.pptx): one animated slide (also slide 12 of the design deck and slide 5 of the brief; click through in Slide Show) of agents moving between device, edge and cloud as the mode changes; [docs/agent-movement.gif](docs/agent-movement.gif) is a preview. Rebuild with `python tools/build_agent_motion.py`.

Rebuild them with `pip install python-pptx`, then `python tools/build_brief_deck.py` and `python tools/build_deck.py`.

## Next

Replace the templated answers with real LLM agents on the same MCP tools, then pilot on real hardware (edge gateway, tablets).

### Earlier plan for phase 2

A cloud MVP for the Online mode. Our own MCP servers (the system of record for the demo,
built on the official SDK and seeded from the simulated fleet), rule-based approvals, an orchestrator, and specialist agents running
workflows W1–W4 end to end with human approval.
