import pytest


@pytest.fixture
def config():
    """Mirrors the real config shape: one manual tier, two scheduled tiers."""
    return {
        "tiers": {
            "tier1": {
                "schedule": {"mode": "manual"},
                "challenge": "confirm",
                "unlock_minutes": 30,
                "manual_unlock_minutes": 30,
                "manual_unlock_mode": "choice",
                "sites": ["chess.com", "lichess.org"],
                "apps": [],
            },
            "tier2": {
                "schedule": {"mode": "daily", "arms": "06:00", "releases": "18:00"},
                "challenge": "arithmetic",
                "unlock_minutes": 15,
                "manual_unlock_minutes": 30,
                "manual_unlock_mode": "choice",
                "sites": ["reddit.com", "youtube.com"],
                "apps": ["com.valvesoftware.steam"],
            },
            "tier3": {
                "schedule": {"mode": "daily", "arms": "06:00", "releases": "20:00"},
                "challenge": "transcription",
                "unlock_minutes": 5,
                "manual_unlock_minutes": 30,
                "manual_unlock_mode": "always_timed",
                "sites": ["x.com"],
                "apps": ["com.roblox.RobloxPlayer"],
            },
        }
    }


@pytest.fixture
def state():
    from friction.state import DEFAULT_STATE
    import json
    return json.loads(json.dumps(DEFAULT_STATE))
