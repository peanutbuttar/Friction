from friction.challenges import run as R
from friction.schedule import Item


def test_whole_tier_label_names_the_tier_not_one_site(config):
    """Opening the whole tier must not be described as opening one site."""
    item = Item("tier1", "site", "chess.com", ("chess.com",),
                "tier1:chess.com", "tier1")
    label = R.label_for(item, config, whole_tier=True)
    assert "chess.com" not in label and "2 items" in label


def test_single_item_label_names_the_site(config):
    item = Item("tier2", "site", "reddit.com", ("reddit.com",),
                "tier2:reddit.com", "tier2")
    assert R.label_for(item, config) == "reddit.com"


# --- the pass must start when the challenge is FINISHED ----------------------

import json
from datetime import datetime, timedelta

import pytest

from friction import schedule as S
from friction import state as st


@pytest.fixture
def clock(monkeypatch):
    """A controllable clock standing in for datetime.now() inside run.py."""
    class Clock:
        current = datetime(2026, 10, 8, 12, 0)          # a Thursday, tiers armed

        @classmethod
        def now(cls):
            return cls.current

        @classmethod
        def advance(cls, **kw):
            cls.current += timedelta(**kw)
    monkeypatch.setattr(R, "datetime", Clock)
    return Clock


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(st, "LOCK_PATH", tmp_path / "state.lock")


def _slow_challenge(clock, gui, minutes):
    """Make every challenge take `minutes` of (fake) wall-clock time to pass."""
    def challenge(*a, **kw):
        clock.advance(minutes=minutes)
        return True
    return challenge


def test_pass_starts_after_a_slow_arithmetic_problem(config, clock, isolated_state, monkeypatch):
    from friction.challenges import gui
    monkeypatch.setattr(gui, "confirm_unlock", lambda *a, **k: gui.TIMED)
    monkeypatch.setattr(gui, "arithmetic", _slow_challenge(clock, gui, 4))

    item = next(i for i in S.items(config) if i.target == "reddit.com")
    assert R.attempt_unlock(item, config)

    expiry = st.parse(st.load()["passes"][item.key])
    finished = datetime(2026, 10, 8, 12, 4)
    assert expiry == finished + timedelta(minutes=15), (
        "the 15-minute pass must start when the problem was solved, not when "
        "the item was clicked")


def test_a_full_transcription_still_buys_its_whole_pass(config, clock, isolated_state, monkeypatch):
    """The bug in its worst form: tier 3 grants 5 minutes and the passage takes ~6.

    Starting the clock at the click meant the pass had expired before the user
    finished typing -- a completed transcription bought nothing.
    """
    from friction.challenges import gui
    monkeypatch.setattr(gui, "confirm_unlock", lambda *a, **k: gui.TIMED)
    monkeypatch.setattr(R, "_transcription", _slow_challenge(clock, gui, 7))

    item = next(i for i in S.items(config) if i.target == "x.com")
    assert R.attempt_unlock(item, config)

    after_typing = clock.current
    assert item not in S.armed(after_typing, config, st.load()), \
        "the item must be open the moment the passage is accepted"
    assert item not in S.armed(after_typing + timedelta(minutes=4, seconds=59), config, st.load())
    assert item in S.armed(after_typing + timedelta(minutes=5, seconds=1), config, st.load())
