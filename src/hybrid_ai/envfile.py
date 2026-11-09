"""Load private settings (such as ANTHROPIC_API_KEY) from a file, so keys never go on a command line.

File: $HYBRID_ENV_FILE, or ~/.config/hybrid-ai/env by default. One KEY=VALUE per line; # starts a
comment; surrounding quotes are stripped. Values already set in the environment always win.
"""

from __future__ import annotations

import os
from pathlib import Path


def env_file() -> Path:
    return Path(os.environ.get("HYBRID_ENV_FILE", Path.home() / ".config" / "hybrid-ai" / "env"))


def load_env_file() -> list[str]:
    """Apply the file's settings to os.environ; return the names that were set (never the values)."""
    path, loaded = env_file(), []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return loaded
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
