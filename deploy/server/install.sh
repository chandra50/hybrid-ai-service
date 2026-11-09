#!/usr/bin/env bash
# Install hybrid-ai on an Ubuntu server (24.04 recommended) as two systemd services.
#
#   sudo ./deploy/server/install.sh            install or upgrade, then start
#   sudo ./deploy/server/install.sh --remove   stop and remove the services (keeps /opt/hybrid-ai)
#   sudo ./deploy/server/install.sh --purge    also delete /opt/hybrid-ai and the hybridai user
#
# Run it from the extracted release folder. Needs internet access to PyPI.
set -euo pipefail

APP=/opt/hybrid-ai
SVC_USER=hybridai
UNITS=(hybrid-ai-live.service hybrid-ai-dashboard.service)
SRC="$(cd "$(dirname "$0")/../.." && pwd)"

die() { echo "error: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "run with sudo"

if [[ "${1:-}" == "--remove" || "${1:-}" == "--purge" ]]; then
  systemctl disable --now "${UNITS[@]}" 2>/dev/null || true
  for u in "${UNITS[@]}"; do rm -f "/etc/systemd/system/$u"; done
  systemctl daemon-reload
  if [[ "$1" == "--purge" ]]; then
    rm -rf "$APP" /etc/default/hybrid-ai
    id "$SVC_USER" &>/dev/null && userdel "$SVC_USER"
    echo "removed services, $APP and user $SVC_USER"
  else
    echo "removed services (kept $APP; use --purge to delete it)"
  fi
  exit 0
fi

[[ -f "$SRC/src/hybrid_ai/__init__.py" ]] || die "run this from the extracted hybrid-ai folder"

# 1. Python 3.11+ with venv
PY=python3
ver=$($PY -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0)
$PY -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null \
  || die "Python 3.11+ required (found $ver). Use Ubuntu 24.04, or install python3.11 and edit PY in this script."
if ! $PY -c 'import ensurepip, venv' &>/dev/null; then
  echo "installing python3-venv ..."
  apt-get update -qq && apt-get install -y -qq "python${ver}-venv" || apt-get install -y -qq python3-venv
fi

# 2. service user
id "$SVC_USER" &>/dev/null || useradd --system --home-dir "$APP" --shell /usr/sbin/nologin "$SVC_USER"

# 3. copy the app (code owned by root, data owned by the service user)
systemctl stop "${UNITS[@]}" 2>/dev/null || true
mkdir -p "$APP"
for d in src dashboard models deploy docs tests tools; do
  rm -rf "${APP:?}/$d"; cp -a "$SRC/$d" "$APP/$d"
done
cp -a "$SRC"/README.md "$SRC"/DEPLOY.md "$SRC"/pyproject.toml "$APP/"
mkdir -p "$APP/data"
chown -R root:root "$APP"
chown -R "$SVC_USER:$SVC_USER" "$APP/data"

# 4. virtualenv with pinned dependencies
[[ -x "$APP/.venv/bin/python" ]] || $PY -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -r "$APP/deploy/requirements.txt"

# 5. demo data (fleet, telemetry, plans) baked into the dashboard
(cd "$APP" && PYTHONPATH=src .venv/bin/python -m hybrid_ai.demo.build_data >/dev/null)

# 6. settings file (kept across upgrades)
if [[ ! -f /etc/default/hybrid-ai ]]; then
  cat > /etc/default/hybrid-ai <<'EOF'
# hybrid-ai settings. After editing: sudo systemctl restart hybrid-ai-live hybrid-ai-dashboard
# Address the two web pages listen on. 127.0.0.1 = this server only (use an SSH tunnel).
# 0.0.0.0 = every network interface. The demo has NO login: only do this on a trusted network.
HYBRID_BIND=127.0.0.1

# Manual agent (RAG over the service manuals, written by Claude Opus 5.5).
# Without a key it still answers, retrieval only (manual passages, no LLM).
# ANTHROPIC_API_KEY=sk-ant-...
# HYBRID_LLM=off          # force retrieval only, even with a key
EOF
  chmod 600 /etc/default/hybrid-ai
fi

# 7. services
for u in "${UNITS[@]}"; do install -m 644 "$APP/deploy/server/$u" "/etc/systemd/system/$u"; done
systemctl daemon-reload
systemctl enable --now "${UNITS[@]}" >/dev/null

# 8. wait for the live demo to answer
bind=$(. /etc/default/hybrid-ai; echo "${HYBRID_BIND:-127.0.0.1}")
probe=$([[ "$bind" == "0.0.0.0" ]] && echo 127.0.0.1 || echo "$bind")
for _ in $(seq 1 60); do
  curl -fsS "http://$probe:8803/api/state" >/dev/null 2>&1 && break
  sleep 1
done
systemctl --no-pager --lines=0 status "${UNITS[@]}" | grep -E "●|Active:" || true
echo
echo "hybrid-ai is installed in $APP"
echo "  live demo:            http://$bind:8803/live.html"
echo "  simulated dashboard:  http://$bind:8765"
[[ "$bind" == "127.0.0.1" ]] && echo "  from your laptop:     ssh -L 8803:127.0.0.1:8803 -L 8765:127.0.0.1:8765 <user>@<this-server>"
echo "logs:  journalctl -u hybrid-ai-live -f"
