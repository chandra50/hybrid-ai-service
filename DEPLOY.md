# Deploying hybrid-ai on an Ubuntu server

This package installs the hybrid-ai demo as two systemd services:

| Service | What it runs | Port |
|---|---|---|
| `hybrid-ai-live` | Live demo: cloud and edge MCP servers, the device backend, and a network simulator (four processes) | **8803** web page; 8801–8813 internal, localhost only |
| `hybrid-ai-dashboard` | Simulated dashboard and the repair recommendations API | **8765** |

Everything runs as an unprivileged `hybridai` user from `/opt/hybrid-ai`. By default **nothing is reachable from outside the server** (see step 4).

---

## 1. Requirements

| | |
|---|---|
| OS | **Ubuntu 24.04 LTS** (Python 3.12). Ubuntu 22.04 ships Python 3.10, which is too old: Starlette needs 3.11+. |
| CPU | x86_64 or arm64. Dependencies are installed from PyPI for the server's own CPU. |
| Memory / disk | About 300 MB RAM; about 250 MB disk including the virtualenv |
| Network | Outbound HTTPS to pypi.org during install. Map tiles in the dashboard load from tile.openstreetmap.org in the viewer's browser. |
| Access | A user with `sudo` |
| Free ports | 8765, 8801–8803, 8810–8813 |

No GPU, database server or LLM key is needed: the demo makes no LLM calls.

## 2. Copy the package to the server

```bash
scp hybrid-ai-*.tar.gz <user>@<server>:/tmp/
```

On the server, check the archive against its checksum, then unpack it:

```bash
cd /tmp && sha256sum -c hybrid-ai-*.tar.gz.sha256
```

```bash
tar -xzf hybrid-ai-*.tar.gz && cd hybrid-ai
```

## 3. Install

```bash
sudo ./deploy/server/install.sh
```

The installer:

1. Checks for Python 3.11+ and installs `python3-venv` if it's missing.
2. Creates the system user `hybridai`.
3. Copies the app to `/opt/hybrid-ai`. Code is owned by root; only `/opt/hybrid-ai/data` is writable by the service.
4. Creates `/opt/hybrid-ai/.venv` and installs the pinned dependencies from `deploy/requirements.txt`.
5. Generates the demo data (fleet, telemetry, repair plans).
6. Writes `/etc/default/hybrid-ai` (settings) if it doesn't exist yet.
7. Installs, enables and starts both services, then waits for the live demo to answer.

Running it again upgrades in place and keeps your settings file.

## 4. Open the demo

The pages listen on **127.0.0.1** by default. Pick one way to reach them.

### Option A: SSH tunnel (recommended)

On your laptop:

```bash
ssh -L 8803:127.0.0.1:8803 -L 8765:127.0.0.1:8765 <user>@<server>
```

Then open, on your laptop:

- Live demo: http://localhost:8803/live.html
- Simulated dashboard: http://localhost:8765

### Option B: open the ports on a trusted network

> The demo has **no login**. Anyone who can reach the ports can change the simulated network and write to the demo database. Only do this on a private network.

```bash
sudo sed -i 's/^HYBRID_BIND=.*/HYBRID_BIND=0.0.0.0/' /etc/default/hybrid-ai
```

```bash
sudo systemctl restart hybrid-ai-live hybrid-ai-dashboard
```

If `ufw` is active, allow only your network, for example:

```bash
sudo ufw allow from 10.0.0.0/8 to any port 8765,8803 proto tcp
```

Only the two web pages are exposed. The internal ports 8801–8813 always stay on localhost.

### Option C: behind nginx with a login

Keep `HYBRID_BIND=127.0.0.1` and proxy `/` to `http://127.0.0.1:8803` (or 8765) with `auth_basic` and TLS.

## 5. Check it's working

```bash
systemctl status hybrid-ai-live hybrid-ai-dashboard
```

```bash
curl -s http://127.0.0.1:8803/api/state | head -c 300; echo
```

```bash
curl -s http://127.0.0.1:8765/api/health
```

In the browser, open the live page and click **Run the repair story**. It takes about 40 seconds and ends with the work order completed in the cloud database.

Optional, the full test suite (about 25 s; runs the live stack on ports 9100+):

```bash
cd /opt/hybrid-ai && sudo -u hybridai env PYTHONPATH=src HYBRID_LIVE_DIR=/opt/hybrid-ai/data/test .venv/bin/python -m unittest discover -s tests
```

## 6. Operate

| Task | Command |
|---|---|
| Restart (fresh demo state) | `sudo systemctl restart hybrid-ai-live hybrid-ai-dashboard` |
| Follow logs | `journalctl -u hybrid-ai-live -f` |
| Stop | `sudo systemctl stop hybrid-ai-live hybrid-ai-dashboard` |
| Change settings | edit `/etc/default/hybrid-ai`, then restart |
| Upgrade | unpack the new release, run `sudo ./deploy/server/install.sh` again |
| Remove services, keep files | `sudo /opt/hybrid-ai/deploy/server/install.sh --remove` |
| Remove everything | `sudo /opt/hybrid-ai/deploy/server/install.sh --purge` |

Data lives in `/opt/hybrid-ai/data` and is rebuilt from the simulator on every restart, so there is nothing to back up.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `Python 3.11+ required` | Use Ubuntu 24.04, or install `python3.11` and `python3.11-venv` and set `PY=python3.11` at the top of the installer. |
| `pip` can't download | The server needs HTTPS to pypi.org. Behind a proxy, set `HTTPS_PROXY` before running the installer. |
| `address already in use` | Something else uses 8765 or 8801–8813: `sudo ss -ltnp \| grep -E ':(87|88)[0-9]{2}'`. |
| Live page says the device backend isn't reachable | `journalctl -u hybrid-ai-live -n 50`. The first start takes about 10–15 s while the edge writes its telemetry files. |
| Map is grey | The viewer's browser can't reach tile.openstreetmap.org. Everything else works; use the **Where agents run** tab. |

## 8. What's inside

```
hybrid-ai/
├── DEPLOY.md              this file
├── README.md              project overview
├── deploy/server/         installer + systemd units for a server
├── deploy/requirements.txt  pinned Python dependencies
├── src/hybrid_ai/         application code (live demo, simulators, model, repair DB)
├── dashboard/             web pages (live.html, index.html) and generated demo data
├── models/                trained repair recommendation model (9 KB)
├── docs/                  design, technical description, demo script, slide decks
├── tests/                 unit and live integration tests
└── tools/                 slide-deck builders (not needed on the server)
```

See `docs/TECHNICAL.md` for how the processes talk to each other, and `docs/DEMO.md` for the 5-minute demo script.
