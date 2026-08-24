"""Runs the right challenge for an item and records the pass if it's earned."""

from __future__ import annotations

import logging
from datetime import datetime

from friction import schedule as S
from friction import state as st
from friction.challenges import core as C
from friction.schedule import Item

log = logging.getLogger(__name__)


def label_for(item: Item, cfg: dict, whole_tier: bool = False) -> str:
    """What to call the thing being unlocked.

    Every tier can now be unlocked either as a whole or item by item, so the
    name depends on which the user actually clicked -- naming one site when
    the whole tier is about to open would be a lie.
    """
    tier_cfg = cfg["tiers"][item.tier]
    if whole_tier:
        n = len(tier_cfg.get("sites", [])) + len(tier_cfg.get("apps", []))
        return f"all of {tier_cfg.get('label', item.tier)} ({n} items)"
    return item.target


# What the confirm dialog warns you is coming. None means the confirm IS the
# whole challenge, which is tier 1.
NEXT_STEP = {
    "confirm": None,
    "arithmetic": "solve an arithmetic problem",
    "transcription": "transcribe a passage of a few hundred words",
}


def attempt_unlock(item: Item, cfg: dict, whole_tier: bool = False) -> bool:
    """Confirm, then the tier's extra friction, then apply the unlock.

    Every tier confirms first -- that was in the original spec and is the point
    of the exercise: making it a decision rather than a reflex.
    """
    from friction.challenges import gui

    now = datetime.now()
    state = st.load()
    tier_cfg = cfg["tiers"][item.tier]
    kind = tier_cfg.get("challenge", "confirm")
    plan = S.unlock_plan(now, item, cfg, state)
    name = label_for(item, cfg, whole_tier=whole_tier)

    choice = gui.confirm_unlock(name, plan, NEXT_STEP.get(kind))
    if choice is gui.CANCELLED:
        return False

    if kind == "arithmetic":
        opts = cfg.get("challenges", {}).get("arithmetic", {})
        passed = gui.arithmetic(name, plan.minutes or 0,
                                int(opts.get("digits", 2)),
                                opts.get("operations", ["+", "-", "*"]))
    elif kind == "transcription":
        passed = _transcription(name, plan.minutes or 0, cfg)
    elif kind == "confirm":
        passed = True                       # the confirm was the challenge
    else:
        log.error("unknown challenge %r for %s", kind, item.tier)
        return False

    if not passed:
        return False

    key = item.tier_key if whole_tier else item.key
    if choice is gui.UNTIMED:
        st.update(lambda s: S.release_manual_lock(s, item, cfg, now,
                                                  whole_tier=whole_tier))
        log.info("unlocked %s with no time limit", key)
    else:
        minutes = plan.minutes or int(tier_cfg.get("unlock_minutes", 15))
        st.update(lambda s: S.grant_pass(s, key, now, minutes))
        log.info("unlocked %s for %d minutes", key, minutes)
    return True


def attempt_global_unlock(cfg: dict) -> bool:
    """Release the everything-at-once lock. Confirm plus the tier-3 friction.

    Releases only the global lock; schedule locks and per-item locks survive it,
    so this is not a cheap way past the tiers.
    """
    from friction.challenges import gui

    now = datetime.now()
    plan = S.global_unlock_plan(cfg)
    kind = cfg.get("global_switch", {}).get("challenge", "transcription")
    n = len(S.items(cfg))
    name = f"everything ({n} items)"

    choice = gui.confirm_unlock(name, plan, NEXT_STEP.get(kind))
    if choice is gui.CANCELLED:
        return False

    if kind == "transcription":
        passed = _transcription(name, plan.minutes or 0, cfg)
    elif kind == "arithmetic":
        opts = cfg.get("challenges", {}).get("arithmetic", {})
        passed = gui.arithmetic(name, plan.minutes or 0, int(opts.get("digits", 2)),
                                opts.get("operations", ["+", "-", "*"]))
    else:
        passed = True
    if not passed:
        return False

    if choice is gui.UNTIMED:
        st.update(lambda s: S.set_global_lock(s, now, False))
        log.info("released the global lock with no time limit")
    else:
        st.update(lambda s: S.grant_pass(s, S.GLOBAL_KEY, now, plan.minutes))
        log.info("released the global lock for %d minutes", plan.minutes)
    return True


def _transcription(name: str, minutes: int, cfg: dict) -> bool:
    """Run the transcription challenge, re-offering it until passed or abandoned."""
    from friction.challenges import gui

    opts = cfg.get("challenges", {}).get("transcription", {})
    state = st.load()
    passage_name = C.pick_passage(
        opts.get("passages", C.available_passages()),
        state.get("next_passage"),
        opts.get("rotate", "alternate"))
    passage = C.load_passage(passage_name)

    carried = ""
    while True:
        passed, carried = gui.transcription(
            name, minutes, passage_name, passage,
            typo_budget_ratio=float(opts.get("typo_budget_ratio", 0.02)),
            case=bool(opts.get("normalize_case", True)),
            whitespace=bool(opts.get("normalize_whitespace", True)),
            punctuation=bool(opts.get("normalize_punctuation", True)),
            carried_text=carried)
        if passed:
            # Only advance the rotation on success, so giving up doesn't let you
            # shop for whichever passage you find easier.
            st.update(lambda s: s.update({"next_passage": passage_name}))
            return True
        if not carried:
            return False        # gave up
