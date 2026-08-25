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
    """One blockable thing, plus the two keys its lock state can live under.

    A single item can cover several domains. x.com and twitter.com are one
    service reached by two names, so they lock and unlock together rather than
    appearing as two separate things you would have to beat twice.
    """
    tier: str
    kind: str                    # "site" or "app"
    target: str                  # what to show: "x.com / twitter.com"
    domains: tuple[str, ...]     # what to match: ("x.com", "twitter.com")
    key: str                     # this item alone, e.g. "tier2:reddit.com"
    tier_key: str                # the whole tier, e.g. "tier2"

    @property
    def is_app(self) -> bool:
        """True for applications, False for websites. They unlock on different terms."""
        return self.kind == "app"


# Why something is currently locked. The unlock terms depend on it: a lock the
# schedule applied is temporary by nature, one you applied by hand is not.
BY_SCHEDULE = "schedule"
BY_HAND = "manual"

# The one switch that locks every app and site at once. Its pass releases only
# THIS lock -- never a schedule lock or a per-item one. Otherwise a single
# transcription at noon would open all 23 items and bypass the tiers entirely.
GLOBAL_KEY = "all"

# A global or tier-1 lock has no schedule to lapse against, so it holds until
# it is deliberately cleared.
_NO_SCHEDULE = {"schedule": {"mode": "manual"}}


@dataclass(frozen=True)
class UnlockPlan:
    """What beating the challenge actually buys."""
    minutes: int | None      # None = no timer at all
    clear_manual: bool       # drop the by-hand lock rather than timing out
    offer_choice: bool       # let the user pick timed vs untimed


def _hhmm(value: str) -> time:
    """Parse an 'HH:MM' config string into a time."""
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def _entry_domains(entry: Any) -> tuple[str, ...]:
    """A config entry is a single name, or a list of names for one service."""
    if isinstance(entry, str):
        return (entry,)
    return tuple(entry)


def items(config: dict[str, Any]) -> list[Item]:
    """Every blockable item across all tiers.

    Every item carries both an individual key and its tier key, so a tier can be
    locked as a whole AND item by item without the two fighting. The key is the
    entry's FIRST domain, so grouping aliases onto an existing entry does not
    invalidate unlocks already recorded against it.
    """
    out: list[Item] = []
    for tier, cfg in config["tiers"].items():
        for kind, field in (("site", "sites"), ("app", "apps")):
            for entry in cfg.get(field, []):
                domains = _entry_domains(entry)
                if not domains:
                    continue
                out.append(Item(tier=tier, kind=kind,
                                target=" / ".join(domains),
                                domains=domains,
                                key=f"{tier}:{domains[0]}", tier_key=tier))
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
    """Is the master toggle currently switched off?"""
    until = parse(state.get("master_disarmed_until"))
    return until is not None and now < until


def lock_reason(now: datetime, item: Item, config: dict[str, Any],
                state: dict[str, Any]) -> str | None:
    """Why this item is locked right now, or None if it isn't.

    An unlock on either the item or its whole tier releases it, so unlocking
    one site while the tier is locked works, and unlocking the tier releases
    everything in it.
    """
    if master_disarmed(now, state):
        return None
    if pass_active(now, item.key, state) or pass_active(now, item.tier_key, state):
        return None

    tier_cfg = config["tiers"][item.tier]
    if in_schedule_window(now, tier_cfg):
        return BY_SCHEDULE
    if (manual_arm_active(now, item.key, tier_cfg, state)
            or manual_arm_active(now, item.tier_key, tier_cfg, state)):
        return BY_HAND
    if global_lock_active(now, state):
        return BY_HAND
    return None


def global_lock_active(now: datetime, state: dict[str, Any]) -> bool:
    """Is the everything-at-once lock currently holding?"""
    if pass_active(now, GLOBAL_KEY, state):
        return False
    return manual_arm_active(now, GLOBAL_KEY, _NO_SCHEDULE, state)


def set_global_lock(state: dict[str, Any], now: datetime, on: bool) -> None:
    """Turn the everything-at-once lock on or off."""
    set_manual_arm(state, GLOBAL_KEY, now, on)
    if on:
        state.get("passes", {}).pop(GLOBAL_KEY, None)   # a new lock beats an old pass


def global_unlock_plan(config: dict[str, Any]) -> UnlockPlan:
    """Terms for releasing the everything-at-once lock."""
    g = config.get("global_switch", {})
    return UnlockPlan(minutes=int(g.get("unlock_minutes", 30)),
                      clear_manual=False,
                      offer_choice=(g.get("mode", "choice") == "choice"))


def armed(now: datetime, config: dict[str, Any], state: dict[str, Any]) -> set[Item]:
    """The set of items that should be blocked at this instant."""
    if master_disarmed(now, state):
        return set()                       # master toggle beats everything
    return {i for i in items(config) if lock_reason(now, i, config, state)}


def unlock_plan(now: datetime, item: Item, config: dict[str, Any],
                state: dict[str, Any]) -> UnlockPlan:
    """What passing the challenge buys, which depends on why it was locked.

    A schedule lock is inherently temporary, so beating it grants a short pass.
    A lock you applied by hand is not on a clock, so timing the unlock out would
    just mean redoing the challenge all evening -- apps come back untimed, and
    sites come back for a longer window.
    """
    tier_cfg = config["tiers"][item.tier]
    reason = lock_reason(now, item, config, state)

    if reason != BY_HAND:
        return UnlockPlan(minutes=int(tier_cfg.get("unlock_minutes", 15)),
                          clear_manual=False, offer_choice=False)

    if item.is_app:
        # No timer: you did the work, the app is yours until you lock it again
        # or the schedule arms it tomorrow.
        return UnlockPlan(minutes=None, clear_manual=True, offer_choice=False)

    minutes = int(tier_cfg.get("manual_unlock_minutes", 30))
    mode = tier_cfg.get("manual_unlock_mode", "choice")
    return UnlockPlan(minutes=minutes, clear_manual=False,
                      offer_choice=(mode == "choice"))


# --- state mutations, kept here so the rules live in one file ---------------

def grant_pass(state: dict[str, Any], key: str, now: datetime, minutes: int) -> None:
    """Record that a challenge was passed, unlocking `key` for `minutes`."""
    state.setdefault("passes", {})[key] = (now + timedelta(minutes=minutes)) \
        .replace(microsecond=0).isoformat()


def set_manual_arm(state: dict[str, Any], key: str, now: datetime, on: bool) -> None:
    """Lock or unlock `key` by hand."""
    arms = state.setdefault("manual_arms", {})
    if on:
        arms[key] = now.replace(microsecond=0).isoformat()
    else:
        arms.pop(key, None)


def disarm_master(state: dict[str, Any], now: datetime, minutes: int) -> None:
    """Switch everything off for `minutes`."""
    state["master_disarmed_until"] = (now + timedelta(minutes=minutes)) \
        .replace(microsecond=0).isoformat()


def rearm_master(state: dict[str, Any]) -> None:
    """Switch everything back on immediately."""
    state["master_disarmed_until"] = None


def release_manual_lock(state: dict[str, Any], item: Item, config: dict[str, Any],
                        now: datetime, whole_tier: bool = False) -> None:
    """Drop a by-hand lock permanently, rather than timing it out.

    Releasing ONE item while its whole tier is locked by hand needs care: just
    clearing the item's own lock would leave the tier-wide lock still catching
    it. So the tier-wide lock is split into individual locks on everything else,
    which preserves exactly what was locked while letting this one item out.
    Original timestamps are carried over so boundary lapsing is unaffected.
    """
    arms = state.setdefault("manual_arms", {})

    if whole_tier:
        arms.pop(item.tier_key, None)
        for other in items(config):
            if other.tier == item.tier:
                arms.pop(other.key, None)
        return

    arms.pop(item.key, None)

    tier_since = arms.get(item.tier_key)
    if tier_since is None:
        return                              # no tier-wide lock to worry about
    arms.pop(item.tier_key, None)
    for other in items(config):
        if other.tier == item.tier and other.key != item.key:
            arms.setdefault(other.key, tier_since)


def locked_ignoring_passes(now: datetime, item: Item, config: dict[str, Any],
                           state: dict[str, Any]) -> bool:
    """Would this be locked if it had no unlock pass?

    Used to tell a pass that is actually holding something open from a leftover
    pass on something nothing is locking anyway. Only the former deserves a
    countdown; showing one for the latter is just noise.
    """
    if master_disarmed(now, state):
        return False
    tier_cfg = config["tiers"][item.tier]
    return (in_schedule_window(now, tier_cfg)
            or manual_arm_active(now, item.key, tier_cfg, state)
            or manual_arm_active(now, item.tier_key, tier_cfg, state))
