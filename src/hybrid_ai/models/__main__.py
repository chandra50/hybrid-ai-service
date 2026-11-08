"""Train the repair recommendation model and export it.

    PYTHONPATH=src python3 -m hybrid_ai.models [--seed 42] [--out models/repair-rec-1.0.json]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ..sim.fleet import generate_fleet
from .repair_model import VERSION, train

ROOT = Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=str(ROOT / "models" / f"{VERSION}.json"))
    args = ap.parse_args(argv)
    t = time.time()
    fleet = generate_fleet(seed=args.seed)
    model = train(seed=args.seed, repair_history=fleet.repair_history)
    path = model.save(args.out)
    print(f"trained {model.version} in {time.time() - t:.1f} s -> {path} ({path.stat().st_size // 1024} KB)")
    print(json.dumps(model.metrics, indent=2))


if __name__ == "__main__":
    main()
