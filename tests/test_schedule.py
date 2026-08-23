from datetime import datetime, timedelta

import pytest

from friction import schedule as S


def at(h, m=0):
    return datetime(2026, 8, 24, h, m)          # a Monday


def targets(items):
    return {i.target for i in items}


# --- scheduled arming ------------------------------------------------------

def test_tier2_armed_during_window(config, state):
    assert "reddit.com" in targets(S.armed(at(12), config, state))


def test_tier2_released_after_1800(config, state):
    assert "reddit.com" not in targets(S.armed(at(18, 1), config, state))


def test_tier3_still_armed_at_1900_when_tier2_is_not(config, state):
    """Tier 3 runs two hours longer. This is the whole point of the tiers."""
    armed = targets(S.armed(at(19), config, state))
    assert "x.com" in armed
    assert "reddit.com" not in armed


def test_nothing_scheduled_armed_overnight(config, state):
    assert S.armed(at(2), config, state) == set()


def test_armed_exactly_at_0600_and_not_at_0559(config, state):
    assert "reddit.com" in targets(S.armed(at(6, 0), config, state))
    assert "reddit.com" not in targets(S.armed(at(5, 59), config, state))


def test_tier1_never_auto_arms(config, state):
    for hour in (2, 6, 12, 19, 23):
        assert "chess.com" not in targets(S.armed(at(hour), config, state))


def test_apps_are_armed_too(config, state):
    assert "com.valvesoftware.steam" in targets(S.armed(at(12), config, state))


# --- passes ----------------------------------------------------------------

def test_pass_unlocks_only_that_item(config, state):
    """Transcribing for one site must not open its neighbours."""
    S.grant_pass(state, "tier2:reddit.com", at(12), 15)
    armed = targets(S.armed(at(12, 5), config, state))
    assert "reddit.com" not in armed
    assert "youtube.com" in armed


def test_pass_expires(config, state):
    S.grant_pass(state, "tier2:reddit.com", at(12), 15)
    assert "reddit.com" not in targets(S.armed(at(12, 14), config, state))
    assert "reddit.com" in targets(S.armed(at(12, 16), config, state))


def test_tier_wide_pass_covers_whole_tier(config, state):
    """Unlocking the tier as a whole opens everything in it."""
    S.set_manual_arm(state, "tier1", at(12), True)
    assert targets(S.armed(at(12), config, state)) >= {"chess.com", "lichess.org"}
    S.grant_pass(state, "tier1", at(12), 30)
    armed = targets(S.armed(at(12, 1), config, state))
    assert "chess.com" not in armed and "lichess.org" not in armed


def test_single_site_unlocks_while_the_whole_tier_stays_locked(config, state):
    """The thing Daksh asked for: tier 1 is no longer all-or-nothing."""
    S.set_manual_arm(state, "tier1", at(12), True)
    S.grant_pass(state, "tier1:chess.com", at(12), 30)
    armed = targets(S.armed(at(12, 1), config, state))
    assert "chess.com" not in armed
    assert "lichess.org" in armed


# --- manual arming ---------------------------------------------------------

def test_manual_arm_works_overnight(config, state):
    """The 'I notice this is pulling at me at 11pm' case."""
    S.set_manual_arm(state, "tier3:x.com", at(23), True)
    assert "x.com" in targets(S.armed(at(23, 30), config, state))


def test_manual_arm_on_scheduled_tier_lapses_at_next_boundary(config, state):
    S.set_manual_arm(state, "tier3:x.com", at(21), True)
    assert "x.com" in targets(S.armed(at(23), config, state))
    # 06:00 next day is the next boundary; the manual arm lapses and the
    # schedule takes over (which happens to also arm it).
    assert not S.manual_arm_active(datetime(2026, 8, 25, 7), "tier3:x.com",
                                   config["tiers"]["tier3"], state)


def test_manual_arm_on_manual_tier_never_lapses(config, state):
    S.set_manual_arm(state, "tier1", at(12), True)
    later = datetime(2026, 9, 30, 3)
    assert "chess.com" in targets(S.armed(later, config, state))


def test_manual_disarm_turns_it_off(config, state):
    S.set_manual_arm(state, "tier1", at(12), True)
    S.set_manual_arm(state, "tier1", at(13), False)
    assert "chess.com" not in targets(S.armed(at(14), config, state))


# --- master toggle ---------------------------------------------------------

def test_master_disarm_beats_everything(config, state):
    S.set_manual_arm(state, "tier1", at(12), True)
    S.disarm_master(state, at(12), 60)
    assert S.armed(at(12, 30), config, state) == set()


def test_master_disarm_expires_after_an_hour(config, state):
    S.disarm_master(state, at(12), 60)
    assert S.armed(at(12, 59), config, state) == set()
    assert "reddit.com" in targets(S.armed(at(13, 1), config, state))


def test_rearm_master_restores_immediately(config, state):
    S.disarm_master(state, at(12), 60)
    S.rearm_master(state)
    assert "reddit.com" in targets(S.armed(at(12, 5), config, state))


# --- window edge cases -----------------------------------------------------

def test_window_wrapping_midnight():
    cfg = {"schedule": {"mode": "daily", "arms": "22:00", "releases": "04:00"}}
    assert S.in_schedule_window(at(23), cfg)
    assert S.in_schedule_window(at(1), cfg)
    assert not S.in_schedule_window(at(12), cfg)


def test_every_item_has_both_an_item_key_and_a_tier_key(config):
    """Both keys exist so a tier can be locked wholly AND item by item."""
    by_target = {i.target: i for i in S.items(config)}
    assert by_target["chess.com"].key == "tier1:chess.com"
    assert by_target["chess.com"].tier_key == "tier1"
    assert by_target["reddit.com"].key == "tier2:reddit.com"
    assert by_target["reddit.com"].tier_key == "tier2"


# --- unlock terms depend on WHY it was locked -------------------------------

def item(config, tier, target):
    return next(i for i in S.items(config) if i.tier == tier and i.target == target)


def test_schedule_lock_grants_the_short_tier_pass(config, state):
    it = item(config, "tier3", "x.com")
    plan = S.unlock_plan(at(12), it, config, state)
    assert plan.minutes == 5 and not plan.clear_manual and not plan.offer_choice


def test_hand_locked_app_has_no_timer(config, state):
    """Beating a by-hand lock on an app must not put you on a clock."""
    S.set_manual_arm(state, "tier3:com.roblox.RobloxPlayer", at(21), True)
    it = item(config, "tier3", "com.roblox.RobloxPlayer")
    plan = S.unlock_plan(at(21, 30), it, config, state)
    assert plan.minutes is None and plan.clear_manual


def test_hand_locked_tier3_site_always_relocks_after_30(config, state):
    config["tiers"]["tier3"]["manual_unlock_mode"] = "always_timed"
    S.set_manual_arm(state, "tier3:x.com", at(21), True)
    plan = S.unlock_plan(at(21, 30), item(config, "tier3", "x.com"), config, state)
    assert plan.minutes == 30 and not plan.offer_choice


def test_hand_locked_tier2_site_offers_a_choice(config, state):
    config["tiers"]["tier2"]["manual_unlock_mode"] = "choice"
    S.set_manual_arm(state, "tier2:reddit.com", at(21), True)
    plan = S.unlock_plan(at(21, 30), item(config, "tier2", "reddit.com"), config, state)
    assert plan.minutes == 30 and plan.offer_choice


def test_scheduled_hours_beat_a_redundant_hand_lock(config, state):
    """Locked by hand during scheduled hours is still a schedule lock."""
    S.set_manual_arm(state, "tier2:reddit.com", at(12), True)
    plan = S.unlock_plan(at(12), item(config, "tier2", "reddit.com"), config, state)
    assert plan.minutes == 15 and not plan.clear_manual


def test_lock_reason_distinguishes_the_two(config, state):
    it = item(config, "tier2", "reddit.com")
    assert S.lock_reason(at(12), it, config, state) == S.BY_SCHEDULE
    assert S.lock_reason(at(21), it, config, state) is None
    S.set_manual_arm(state, "tier2:reddit.com", at(21), True)
    assert S.lock_reason(at(21, 5), it, config, state) == S.BY_HAND


def test_releasing_one_item_from_a_tier_wide_lock_keeps_the_rest_locked(config, state):
    """Splitting the tier lock must not accidentally free everything."""
    S.set_manual_arm(state, "tier1", at(21), True)
    it = item(config, "tier1", "chess.com")
    S.release_manual_lock(state, it, config, at(22))

    armed = targets(S.armed(at(22, 5), config, state))
    assert "chess.com" not in armed
    assert "lichess.org" in armed


def test_releasing_the_whole_tier_frees_everything_in_it(config, state):
    S.set_manual_arm(state, "tier1", at(21), True)
    it = item(config, "tier1", "chess.com")
    S.release_manual_lock(state, it, config, at(22), whole_tier=True)
    assert S.armed(at(22, 5), config, state) == set()


def test_release_preserves_original_lock_timestamps(config, state):
    """Carried-over timestamps keep boundary lapsing honest."""
    S.set_manual_arm(state, "tier2", at(21), True)
    it = item(config, "tier2", "reddit.com")
    S.release_manual_lock(state, it, config, at(23))
    assert state["manual_arms"]["tier2:youtube.com"] == at(21).replace(microsecond=0).isoformat()
