"""Tier header text. Pure function, so no window has to be opened to test it."""
from datetime import datetime

from friction.ui import _tier_window_label

THU = datetime(2026, 10, 8, 12)     # weekday
SAT = datetime(2026, 10, 10, 12)
SUN = datetime(2026, 10, 11, 12)


def daily(label, releases, weekend_releases=None):
    sched = {"mode": "daily", "arms": "06:00", "releases": releases}
    if weekend_releases:
        sched["weekend"] = {"releases": weekend_releases}
    return {"label": label, "schedule": sched}


def test_the_fixture_dates_are_what_we_think():
    assert THU.weekday() == 3 and SAT.weekday() == 5 and SUN.weekday() == 6


def test_weekday_shows_the_weekday_hours():
    out = _tier_window_label(daily("Bad", "19:00", "17:00"), "tier2", THU)
    assert "06:00–19:00" in out and "weekend" not in out


def test_saturday_shows_the_weekend_hours():
    out = _tier_window_label(daily("Bad", "19:00", "17:00"), "tier2", SAT)
    assert "06:00–17:00" in out and "weekend" in out


def test_sunday_matches_saturday():
    cfg = daily("Worst", "21:00", "19:00")
    assert _tier_window_label(cfg, "tier3", SUN) == _tier_window_label(cfg, "tier3", SAT)


def test_tier_without_a_weekend_block_reads_the_same_all_week():
    cfg = daily("Bad", "19:00")
    assert _tier_window_label(cfg, "tier2", SAT) == _tier_window_label(cfg, "tier2", THU)
    assert "weekend" not in _tier_window_label(cfg, "tier2", SAT)


def test_manual_tier_says_manual_not_hours():
    cfg = {"label": "Mild", "schedule": {"mode": "manual"}}
    out = _tier_window_label(cfg, "tier1", SAT)
    assert "manual" in out and ":" not in out.split("·")[1]


def test_the_label_is_kept():
    assert _tier_window_label(daily("Worst", "21:00", "19:00"), "tier3", THU).startswith("Worst")
