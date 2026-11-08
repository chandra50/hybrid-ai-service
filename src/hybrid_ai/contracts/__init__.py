"""MCP tool contracts shared by every tier.

``tools.json`` is the single source of truth (language-neutral, so edge
gateways or non-Python services can use it too). This module loads it,
builds the provenance-wrapped response schema for each tool, and validates
payloads.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

__all__ = [
    "ContractError",
    "Tool",
    "TIERS",
    "contract_version",
    "envelope",
    "get_tool",
    "list_tools",
    "validate_input",
    "validate_response",
]

TIERS = ("edge", "field", "hub", "cloud")
_PROVENANCE_KEYS = ("source_tier", "as_of", "staleness_s", "confidence", "authoritative")


class ContractError(ValueError):
    """A payload does not match its tool contract."""

    def __init__(self, tool: str, kind: str, errors: list[str]):
        self.tool, self.kind, self.errors = tool, kind, errors
        super().__init__(f"{tool} {kind} invalid: " + "; ".join(errors))


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    response_schema: dict[str, Any]


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    text = resources.files(__package__).joinpath("tools.json").read_text(encoding="utf-8")
    return json.loads(text)


def contract_version() -> str:
    return _raw()["version"]


def _with_defs(schema: dict[str, Any]) -> dict[str, Any]:
    """Attach the shared $defs so local '#/$defs/..' refs resolve standalone."""
    out = copy.deepcopy(schema)
    out["$defs"] = copy.deepcopy(_raw()["$defs"])
    return out


def _response_schema(output: dict[str, Any]) -> dict[str, Any]:
    prov = _raw()["$defs"]["Provenance"]
    return {
        "type": "object",
        "required": ["result", *prov["required"]],
        "properties": {"result": output, **prov["properties"]},
        "additionalProperties": False,
    }


@lru_cache(maxsize=None)
def get_tool(name: str) -> Tool:
    tools = _raw()["tools"]
    if name not in tools:
        raise KeyError(f"unknown tool {name!r}; known: {sorted(tools)}")
    spec = tools[name]
    return Tool(
        name=name,
        description=spec["description"],
        input_schema=_with_defs(spec["input"]),
        output_schema=_with_defs(spec["output"]),
        response_schema=_with_defs(_response_schema(spec["output"])),
    )


def list_tools() -> list[str]:
    return sorted(_raw()["tools"])


@lru_cache(maxsize=None)
def _validator(name: str, kind: str) -> Draft202012Validator:
    tool = get_tool(name)
    schema = tool.input_schema if kind == "input" else tool.response_schema
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _check(name: str, kind: str, payload: Any) -> None:
    errors = sorted(_validator(name, kind).iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        msgs = [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors]
        raise ContractError(name, kind, msgs)


def validate_input(name: str, args: dict[str, Any]) -> None:
    _check(name, "input", args)


def validate_response(name: str, response: dict[str, Any]) -> None:
    _check(name, "response", response)


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def envelope(
    result: dict[str, Any],
    *,
    source_tier: str,
    as_of: datetime,
    now: datetime | None = None,
    authoritative: bool | None = None,
    confidence: str | None = None,
) -> dict[str, Any]:
    """Wrap a tool result with provenance.

    Defaults: only the cloud is authoritative; non-authoritative answers are
    'provisional'; authoritative ones are 'confirmed'.
    """
    if source_tier not in TIERS:
        raise ValueError(f"source_tier must be one of {TIERS}")
    now = now or datetime.now(timezone.utc)
    if as_of.tzinfo is None or now.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    staleness = max(0, int((now - as_of).total_seconds()))
    if authoritative is None:
        authoritative = source_tier == "cloud"
    if confidence is None:
        confidence = "confirmed" if authoritative else "provisional"
    return {
        "result": result,
        "source_tier": source_tier,
        "as_of": _iso(as_of),
        "staleness_s": staleness,
        "confidence": confidence,
        "authoritative": authoritative,
    }
