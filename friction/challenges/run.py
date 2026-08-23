"""Runs the right challenge for an item and records the pass if it's earned."""

from __future__ import annotations

import logging
from datetime import datetime

from friction import schedule as S
from friction import state as st
from friction.challenges import core as C
from friction.schedule import Item

log = logging.getLogger(__name__)


def label_for(item: Item, cfg: dict) -> str:
    """What to call the thing being unlocked.

    Tier 1 unlocks as a whole, so naming a single site there would be a lie.
    """
    tier_cfg = cfg["tiers"][item.tier]
    if tier_cfg.get("toggle_granularity") == "tier":
        n = len(tier_cfg.get("sites", [])) + len(tier_cfg.get("apps", []))
        return f"{tier_cfg.get('label', item.tier)} ({n} items)"
    return item.target


def attempt_unlock(item: Item, cfg: dict) -> bool:
    """Show the challenge. On success, grant the pass and return True."""
    from friction.challenges import gui

    tier_cfg = cfg["tiers"][item.tier]
    kind = tier_cfg.get("challenge", "confirm")
    minutes = int(tier_cfg.get("unlock_minutes", 15))
    name = label_for(item, cfg)

    if kind == "confirm":
        passed = gui.confirm(name, minutes)

    elif kind == "arithmetic":
        opts = cfg.get("challenges", {}).get("arithmetic", {})
        passed = gui.arithmetic(name, minutes,
                                int(opts.get("digits", 2)),
                                opts.get("operations", ["+", "-", "*"]))

    elif kind == "transcription":
        passed = _transcription(name, minutes, cfg)

    else:
        log.error("unknown challenge %r for %s", kind, item.tier)
        return False

    if passed:
        st.update(lambda s: S.grant_pass(s, item.key, datetime.now(), minutes))
        log.info("unlocked %s for %d minutes", item.key, minutes)
    return passed


def _transcription(name: str, minutes: int, cfg: dict) -> bool:
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
