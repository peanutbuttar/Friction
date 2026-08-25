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


def test_choosing_timed_still_offers_the_choice_next_time(config, state):
    """Picking '30 minutes' must not silently become a permanent decision.

    The by-hand lock stays underneath the timed pass, so when it expires the
    next unlock is still a by-hand lock and the choice comes back.
    """
    it = item(config, "tier2", "reddit.com")
    S.set_manual_arm(state, "tier2:reddit.com", at(21), True)

    first = S.unlock_plan(at(21), it, config, state)
    assert first.offer_choice and first.minutes == 30

    S.grant_pass(state, "tier2:reddit.com", at(21), 30)          # chose "timed"
    assert "reddit.com" not in targets(S.armed(at(21, 15), config, state))  # open
    assert "reddit.com" in targets(S.armed(at(21, 31), config, state))      # re-locked

    second = S.unlock_plan(at(21, 31), it, config, state)
    assert second.offer_choice and second.minutes == 30, "choice must come back"


def test_choosing_untimed_does_not_come_back(config, state):
    """The other branch: untimed clears the lock, so there is nothing to re-offer."""
    it = item(config, "tier2", "reddit.com")
    S.set_manual_arm(state, "tier2:reddit.com", at(21), True)
    S.release_manual_lock(state, it, config, at(21))             # chose "untimed"
    assert "reddit.com" not in targets(S.armed(at(23, 59), config, state))


# --- the everything-at-once switch -----------------------------------------

def test_global_lock_locks_everything(config, state):
    S.set_global_lock(state, at(21), True)          # 21:00, nothing scheduled
    assert len(S.armed(at(21, 5), config, state)) == len(S.items(config))


def test_global_unlock_releases_only_the_global_lock(config, state):
    """The important one: a global pass must not open schedule-locked items."""
    S.set_global_lock(state, at(12), True)
    S.grant_pass(state, S.GLOBAL_KEY, at(12), 30)   # unlocked the global lock

    armed = targets(S.armed(at(12, 5), config, state))
    assert "reddit.com" in armed, "tier 2 is scheduled at noon; must stay locked"
    assert "x.com" in armed, "tier 3 is scheduled at noon; must stay locked"
    assert "chess.com" not in armed, "tier 1 has no schedule; global lock was its only one"


def test_global_unlock_does_not_override_a_per_item_lock(config, state):
    S.set_global_lock(state, at(21), True)
    S.set_manual_arm(state, "tier2:reddit.com", at(21), True)
    S.grant_pass(state, S.GLOBAL_KEY, at(21), 30)

    armed = targets(S.armed(at(21, 5), config, state))
    assert "reddit.com" in armed, "its own lock outlives the global one"
    assert "youtube.com" not in armed


def test_global_lock_does_not_lapse_at_a_schedule_boundary(config, state):
    """It has no schedule of its own, so it holds until deliberately cleared."""
    S.set_global_lock(state, at(21), True)
    assert S.global_lock_active(datetime(2026, 8, 27, 3), state)


def test_relocking_globally_beats_a_live_pass(config, state):
    S.set_global_lock(state, at(21), True)
    S.grant_pass(state, S.GLOBAL_KEY, at(21), 30)
    assert not S.global_lock_active(at(21, 5), state)
    S.set_global_lock(state, at(21, 10), True)      # changed your mind
    assert S.global_lock_active(at(21, 15), state)


def test_global_unlock_terms_come_from_config(config):
    config["global_switch"] = {"unlock_minutes": 30, "mode": "choice"}
    plan = S.global_unlock_plan(config)
    assert plan.minutes == 30 and plan.offer_choice


# --- one lock covering several domains --------------------------------------

def test_grouped_domains_are_a_single_item(config):
    """x.com and twitter.com are one service; they must be one lock."""
    config["tiers"]["tier3"]["sites"] = [["x.com", "twitter.com"], "tiktok.com"]
    sites = [i for i in S.items(config) if i.tier == "tier3" and i.kind == "site"]
    assert len(sites) == 2
    grouped = next(i for i in sites if "x.com" in i.domains)
    assert grouped.domains == ("x.com", "twitter.com")
    assert grouped.target == "x.com / twitter.com"


def test_group_key_is_the_first_domain(config):
    """Keeps unlocks recorded before the grouping still valid."""
    config["tiers"]["tier3"]["sites"] = [["x.com", "twitter.com"]]
    it = next(i for i in S.items(config) if i.kind == "site" and i.tier == "tier3")
    assert it.key == "tier3:x.com"


def test_unlocking_a_group_unlocks_every_domain_in_it(config, state):
    config["tiers"]["tier3"]["sites"] = [["x.com", "twitter.com"]]
    it = next(i for i in S.items(config) if i.kind == "site" and i.tier == "tier3")
    assert it in S.armed(at(12), config, state)
    S.grant_pass(state, it.key, at(12), 5)
    assert it not in S.armed(at(12, 1), config, state)


def test_plain_string_entries_still_work(config):
    config["tiers"]["tier2"]["sites"] = ["reddit.com"]
    it = next(i for i in S.items(config) if i.tier == "tier2" and i.kind == "site")
    assert it.domains == ("reddit.com",) and it.target == "reddit.com"


def test_empty_group_is_skipped(config):
    config["tiers"]["tier2"]["sites"] = [[], "reddit.com"]
    sites = [i for i in S.items(config) if i.tier == "tier2" and i.kind == "site"]
    assert len(sites) == 1


def test_matcher_rules_are_flattened_not_the_display_label(config, state):
    """The daemon feeds domains to the matcher, never the joined label.

    Passing item.target would produce the rule "x.com / twitter.com", which
    matches nothing at all -- a silent unblock of both.
    """
    config["tiers"]["tier3"]["sites"] = [["x.com", "twitter.com"]]
    armed = S.armed(at(12), config, state)
    rules = [d for i in armed if i.kind == "site" for d in i.domains]
    assert "x.com" in rules and "twitter.com" in rules
    assert not any("/" in r for r in rules)
