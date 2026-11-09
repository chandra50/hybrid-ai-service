"""Start the live demo: four real processes.

    .venv/bin/python -m hybrid_ai.live          (with PYTHONPATH=src)

Ctrl+C stops all of them.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request

from .common import HOST, PORT, ROOT

PROCS = ["netsim", "cloud", "edge", "device"]


def start(env: dict | None = None) -> list[subprocess.Popen]:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), **(env or {})}
    procs = []
    for name in PROCS:
        procs.append(subprocess.Popen([sys.executable, "-m", f"hybrid_ai.live.{name}"], env=env, cwd=ROOT))
        time.sleep(0.3)
    return procs


def wait_ready(port: int, timeout: float = 60) -> bool:
    t = time.time()
    while time.time() - t < timeout:
        try:
            with urllib.request.urlopen(f"http://{HOST}:{port}/api/state", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    return False


def stop(procs: list[subprocess.Popen]) -> None:
    for p in procs:
        if p.poll() is None:
            p.send_signal(signal.SIGINT)
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


def _term(signum, frame):  # noqa: ARG001
    raise KeyboardInterrupt


def main() -> None:
    signal.signal(signal.SIGTERM, _term)
    procs = start()
    try:
        if not wait_ready(PORT["device"]):
            print("device backend did not come up; check the output above", flush=True)
            return
        print(f"\nlive demo ready: http://{HOST}:{PORT['device']}/live.html   (Ctrl+C to stop)\n", flush=True)
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        print("a process exited; stopping the others", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        stop(procs)


if __name__ == "__main__":
    main()
