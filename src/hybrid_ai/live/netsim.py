"""Network simulator: a real TCP proxy between the places.

Each route listens on its own port and forwards to the target process. The mode
decides, per route, whether a new connection is accepted, how much latency each
chunk gets, and whether the link flaps. When a route goes down, open connections
on it are cut, so in-flight requests really fail.

    ONLINE   WAN up, ~40 ms each way
    LIMITED  WAN flaps (up ~55% of the time in 3-9 s windows), ~250 ms each way
    OFFLINE  WAN down; device <-> edge (local) still up
    sensors_lost  the edge is dark: device <-> edge and edge -> cloud are down

Control (not subject to faults):  GET/POST http://127.0.0.1:<base+10>/state
"""

from __future__ import annotations

import asyncio
import json
import random
import time

from .common import HOST, PORT

ROUTES = {  # name: (listen port, target port, kind)
    "device-cloud": (PORT["device-cloud"], PORT["cloud"], "wan"),
    "device-edge": (PORT["device-edge"], PORT["edge"], "local"),
    "edge-cloud": (PORT["edge-cloud"], PORT["cloud"], "wan"),
}


class Net:
    def __init__(self):
        self.mode = "ONLINE"
        self.sensors_lost = False
        self.rng = random.Random(7)
        self.windows: dict[str, tuple[float, bool]] = {}   # route -> (until, up) for LIMITED flapping
        self.conns: dict[str, set[asyncio.StreamWriter]] = {r: set() for r in ROUTES}
        self.stats = {r: {"accepted": 0, "refused": 0, "cut": 0, "bytes": 0} for r in ROUTES}

    def latency(self, route: str) -> float:
        if ROUTES[route][2] == "local":
            return 0.005
        return {"ONLINE": 0.04, "LIMITED": 0.25}.get(self.mode, 0.0)

    def up(self, route: str) -> bool:
        kind = ROUTES[route][2]
        if self.sensors_lost and route in ("device-edge", "edge-cloud"):
            return False
        if kind == "local":
            return True
        if self.mode == "OFFLINE":
            return False
        if self.mode == "LIMITED":
            until, state = self.windows.get(route, (0.0, True))
            if time.monotonic() >= until:
                state = self.rng.random() < 0.55
                self.windows[route] = (time.monotonic() + self.rng.uniform(3, 9), state)
            return self.windows[route][1]
        return True

    def describe(self) -> dict:
        return {"mode": self.mode, "sensors_lost": self.sensors_lost,
                "links": {r: {"up": self.up(r), "latency_ms": round(self.latency(r) * 1000), "kind": ROUTES[r][2], **self.stats[r]}
                          for r in ROUTES}}

    def cut_down_routes(self) -> None:
        for r, writers in self.conns.items():
            if not self.up(r):
                for w in list(writers):
                    self.stats[r]["cut"] += 1
                    w.close()
                writers.clear()


NET = Net()


async def _pipe(route: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            if not NET.up(route):
                break
            await asyncio.sleep(NET.latency(route))
            NET.stats[route]["bytes"] += len(chunk)
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass


def _handler(route: str, target_port: int):
    async def handle(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
        if not NET.up(route):
            NET.stats[route]["refused"] += 1
            client_w.close()
            return
        try:
            up_r, up_w = await asyncio.open_connection(HOST, target_port)
        except OSError:
            NET.stats[route]["refused"] += 1
            client_w.close()
            return
        NET.stats[route]["accepted"] += 1
        NET.conns[route].update({client_w, up_w})
        await asyncio.gather(_pipe(route, client_r, up_w), _pipe(route, up_r, client_w))
        NET.conns[route].difference_update({client_w, up_w})
    return handle


async def _control(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Tiny HTTP endpoint: GET /state, POST /state {"mode", "sensors_lost"}."""
    try:
        head = await reader.readuntil(b"\r\n\r\n")
        lines = head.decode().split("\r\n")
        method = lines[0].split(" ")[0]
        length = next((int(x.split(":")[1]) for x in lines if x.lower().startswith("content-length:")), 0)
        body = await reader.readexactly(length) if length else b""
        if method == "POST" and body:
            req = json.loads(body)
            if req.get("mode") in ("ONLINE", "LIMITED", "OFFLINE"):
                NET.mode = req["mode"]
                NET.windows.clear()
            if "sensors_lost" in req:
                NET.sensors_lost = bool(req["sensors_lost"])
            NET.cut_down_routes()
        out = json.dumps(NET.describe()).encode()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\n"
                     b"Content-Length: " + str(len(out)).encode() + b"\r\nConnection: close\r\n\r\n" + out)
        await writer.drain()
    except Exception:  # noqa: BLE001
        pass
    finally:
        writer.close()


async def _flapper() -> None:
    """In LIMITED, windows open and close by themselves; cut connections when a window closes."""
    while True:
        await asyncio.sleep(0.5)
        NET.cut_down_routes()


async def main() -> None:
    servers = [await asyncio.start_server(_handler(name, tgt), HOST, lp) for name, (lp, tgt, _) in ROUTES.items()]
    servers.append(await asyncio.start_server(_control, HOST, PORT["netsim"]))
    print(f"netsim: routes {', '.join(f'{n} :{lp}->{t}' for n, (lp, t, _) in ROUTES.items())}; control :{PORT['netsim']}", flush=True)
    asyncio.create_task(_flapper())
    await asyncio.gather(*(s.serve_forever() for s in servers))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:  # stopped by the launcher
        pass
