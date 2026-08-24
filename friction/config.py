"""Loads config.local.json, falling back to the example if it's absent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
LOCAL = REPO / "config.local.json"
EXAMPLE = REPO / "config.example.json"


class ConfigError(Exception):
    """Raised when the config is missing, malformed, or internally inconsistent."""
    pass


def load(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the config, preferring config.local.json.

    Falls back to the example so a fresh clone can still start up.
    """
    p = path or (LOCAL if LOCAL.exists() else EXAMPLE)
    if not p.exists():
        raise ConfigError(f"no config found; copy {EXAMPLE.name} to {LOCAL.name}")
    try:
        cfg = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"{p.name} is not valid JSON: {e}") from e

    if "tiers" not in cfg:
        raise ConfigError(f"{p.name} has no 'tiers' section")
    for tier, tc in cfg["tiers"].items():
        sched = tc.get("schedule", {})
        if sched.get("mode") == "daily" and not (sched.get("arms") and sched.get("releases")):
            raise ConfigError(f"{tier}: daily schedule needs both 'arms' and 'releases'")
    return cfg
