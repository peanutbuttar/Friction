"""Decides what is armed right now. Pure -- no clock, no filesystem, no I/O.

Everything that governs whether a site or app is blocked lives here, so it can be
tested by handing it a fake `now` instead of waiting until 6am. The daemon and the
UI both call `armed()` and act on the answer; neither makes the decision itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from friction.state import parse


@dataclass(frozen=True)
class Item:
    """One blockable thing, and the key under which its unlock is recorded."""
    tier: str
    kind: str      # "site" or "app"
    target: str    # "reddit.com" or "com.valvesoftware.steam"
    key: str       # "tier1" for tier-granularity tiers, else "tier2:reddit.com"


def _hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def items(config: dict[str, Any]) -> list[Item]:
    """Every blockable item across all tiers."""
    out: list[Item] = []
    for tier, cfg in config["tiers"].items():
        per_tier = cfg.get("toggle_granularity") == "tier"
        for kind, field in (("site", "sites"), ("app", "apps")):
            for target in cfg.get(field, []):
                key = tier if per_tier else f"{tier}:{target}"
                out.append(Item(tier=tier, kind=kind, target=target, key=key))
    return out


def in_schedule_window(now: datetime, tier_cfg: dict[str, Any]) -> bool:
    """Is this tier inside its automatic arming window?"""
    sched = tier_cfg.get("schedule", {})
    if sched.get("mode") != "daily":
        return False                       # manual-only tiers are never auto-armed
    arms, releases = _hhmm(sched["arms"]), _hhmm(sched["releases"])
    t = now.time()
    if arms <= releases:
        return arms <= t < releases
    return t >= arms or t < releases       # window wraps past midnight


def next_boundary(after: datetime, tier_cfg: dict[str, Any]) -> datetime | None:
    """The next arm-or-release moment strictly after `after`.

    None for manual-only tiers, which have no boundaries -- a manual arm on those
    lasts until it is manually turned off.
    """
    sched = tier_cfg.get("schedule", {})
    if sched.get("mode") != "daily":
        return None
    candidates = []
    for value in (sched["arms"], sched["releases"]):
        t = _hhmm(value)
        today = after.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        candidates.append(today if today > after else today + timedelta(days=1))
    return min(candidates)


def manual_arm_active(now: datetime, key: str, tier_cfg: dict[str, Any],
                      state: dict[str, Any]) -> bool:
    """A manual arm holds until turned off, or until the next schedule boundary."""
    since = parse(state.get("manual_arms", {}).get(key))
    if since is None:
        return False
    boundary = next_boundary(since, tier_cfg)
    if boundary is None:
        return True                        # manual-only tier: no boundary to lapse at
    return now < boundary


def pass_active(now: datetime, key: str, state: dict[str, Any]) -> bool:
    """Has a passed challenge bought this item time that hasn't run out?"""
    expiry = parse(state.get("passes", {}).get(key))
    return expiry is not None and now < expiry


def master_disarmed(now: datetime, state: dict[str, Any]) -> bool:
    until = parse(state.get("master_disarmed_until"))
    return until is not None and now < until


def armed(now: datetime, config: dict[str, Any], state: dict[str, Any]) -> set[Item]:
    """The set of items that should be blocked at this instant."""
    if master_disarmed(now, state):
        return set()                       # master toggle beats everything

    out: set[Item] = set()
    for item in items(config):
        tier_cfg = config["tiers"][item.tier]
        if pass_active(now, item.key, state):
            continue                       # unlocked, and the clock hasn't run out
        if in_schedule_window(now, tier_cfg) or manual_arm_active(now, item.key, tier_cfg, state):
            out.add(item)
    return out


# --- state mutations, kept here so the rules live in one file ---------------

def grant_pass(state: dict[str, Any], key: str, now: datetime, minutes: int) -> None:
    state.setdefault("passes", {})[key] = (now + timedelta(minutes=minutes)) \
        .replace(microsecond=0).isoformat()


def set_manual_arm(state: dict[str, Any], key: str, now: datetime, on: bool) -> None:
    arms = state.setdefault("manual_arms", {})
    if on:
        arms[key] = now.replace(microsecond=0).isoformat()
    else:
        arms.pop(key, None)


def disarm_master(state: dict[str, Any], now: datetime, minutes: int) -> None:
    state["master_disarmed_until"] = (now + timedelta(minutes=minutes)) \
        .replace(microsecond=0).isoformat()


def rearm_master(state: dict[str, Any]) -> None:
    state["master_disarmed_until"] = None
