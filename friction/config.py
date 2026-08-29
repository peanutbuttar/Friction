"""Loads config.local.json, falling back to the example if it's absent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
LOCAL = REPO / "config.local.json"
EXAMPLE = REPO / "config.example.json"

# A copy of the last config that parsed. A single missing comma in
# config.local.json used to crash both processes on startup -- and because they
# crashed immediately, launchd gave up retrying and enforcement silently
# stopped. A typo should cost you the menu bar, not your blocking.
LAST_GOOD = Path.home() / "Library" / "Application Support" / "Friction" / "config.last-good.json"


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

    _snapshot(cfg)
    return cfg


def _snapshot(cfg: dict[str, Any]) -> None:
    """Remember a config that parsed, so a later typo isn't fatal.

    Best effort: failing to write the snapshot must never stop Friction working.
    """
    try:
        text = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
        if LAST_GOOD.exists() and LAST_GOOD.read_text() == text:
            return                                   # unchanged, skip the write
        LAST_GOOD.parent.mkdir(parents=True, exist_ok=True)
        LAST_GOOD.write_text(text)
    except OSError:
        pass


def load_resilient() -> tuple[dict[str, Any], str | None]:
    """Load the config, falling back to the last one that parsed.

    Returns (config, error). A non-None error means the real config is broken
    and these are stale settings -- callers should say so loudly, but carry on.
    Only raises if there is no usable config at all.
    """
    try:
        return load(), None
    except ConfigError as e:
        try:
            cfg = json.loads(LAST_GOOD.read_text())
        except (OSError, json.JSONDecodeError):
            raise e from None
        return cfg, str(e)
