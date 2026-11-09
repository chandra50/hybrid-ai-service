#!/usr/bin/env bash
# Deploy hybrid-ai on this machine as two systemd user services (localhost only).
#   deploy/install.sh            install / update and (re)start
#   deploy/install.sh --remove   stop, disable and remove the services
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
UNITS=(hybrid-ai-live.service hybrid-ai-dashboard.service)
DEST="$HOME/.config/systemd/user"

if [[ "${1:-}" == "--remove" ]]; then
  systemctl --user disable --now "${UNITS[@]}" || true
  for u in "${UNITS[@]}"; do rm -f "$DEST/$u"; done
  systemctl --user daemon-reload
  echo "removed"; exit 0
fi

if [[ "$REPO" != "$HOME/hybrid-ai" ]]; then
  echo "The unit files expect the repo at \$HOME/hybrid-ai (found $REPO)."; exit 1
fi
if [[ ! -x "$REPO/.venv/bin/python" ]]; then
  python3 -m venv "$REPO/.venv"
fi
"$REPO/.venv/bin/pip" install -q -r "$REPO/deploy/requirements.txt"
(cd "$REPO" && PYTHONPATH=src .venv/bin/python -m hybrid_ai.demo.build_data >/dev/null)

mkdir -p "$DEST"
for u in "${UNITS[@]}"; do install -m 644 "$REPO/deploy/$u" "$DEST/$u"; done
systemctl --user daemon-reload
systemctl --user enable "${UNITS[@]}" >/dev/null
systemctl --user restart "${UNITS[@]}"
echo "deployed:"
echo "  live demo (real processes):  http://127.0.0.1:8803/live.html"
echo "  simulated dashboard:         http://localhost:8765"
echo "status:  systemctl --user status hybrid-ai-live hybrid-ai-dashboard"
echo "logs:    journalctl --user -u hybrid-ai-live -f"
