"""Config loading, and surviving a broken one.

A single missing comma in config.local.json used to crash both processes on
startup. Because they crashed immediately, launchd gave up retrying and
enforcement silently stopped -- the worst outcome for a typo.
"""
import json

import pytest

from friction import config as C


@pytest.fixture
def paths(tmp_path, monkeypatch, config):
    local = tmp_path / "config.local.json"
    local.write_text(json.dumps(config))
    monkeypatch.setattr(C, "LOCAL", local)
    monkeypatch.setattr(C, "LAST_GOOD", tmp_path / "last-good.json")
    return local


def test_load_snapshots_a_config_that_parsed(paths):
    C.load()
    assert C.LAST_GOOD.exists()
    assert "tiers" in json.loads(C.LAST_GOOD.read_text())


def test_snapshot_is_not_rewritten_when_unchanged(paths):
    C.load()
    first = C.LAST_GOOD.stat().st_mtime_ns
    C.load()
    assert C.LAST_GOOD.stat().st_mtime_ns == first


def test_resilient_load_is_clean_when_config_is_fine(paths):
    cfg, err = C.load_resilient()
    assert err is None and "tiers" in cfg


def test_resilient_load_survives_a_missing_comma(paths):
    """The exact failure: valid config, snapshot taken, then a typo."""
    C.load()                                     # snapshot the good version
    paths.write_text('{"tiers": {"tier1": {}}')  # unclosed brace

    cfg, err = C.load_resilient()

    assert err is not None and "not valid JSON" in err
    assert cfg["tiers"]["tier2"]["sites"], "should be the last good config, not the broken one"


def test_resilient_load_survives_a_semantically_invalid_config(paths):
    C.load()
    paths.write_text(json.dumps({"tiers": {"t": {"schedule": {"mode": "daily"}}}}))

    cfg, err = C.load_resilient()

    assert "needs both" in err
    assert "tier1" in cfg["tiers"]


def test_recovers_once_the_config_is_fixed(paths, config):
    C.load()
    paths.write_text("{ broken")
    assert C.load_resilient()[1] is not None
    paths.write_text(json.dumps(config))
    assert C.load_resilient()[1] is None


def test_raises_when_there_is_no_usable_config_at_all(paths):
    """A fresh install that was never configured should still fail loudly."""
    paths.write_text("{ broken")
    with pytest.raises(C.ConfigError):
        C.load_resilient()


def test_broken_snapshot_does_not_mask_the_real_error(paths):
    C.LAST_GOOD.write_text("{ also broken")
    paths.write_text("{ broken")
    with pytest.raises(C.ConfigError):
        C.load_resilient()
