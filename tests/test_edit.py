import json

import pytest

from friction.edit import EditError, add_site, covered_by, rule_from_url


@pytest.mark.parametrize("raw,expected", [
    ("https://www.reddit.com/r/all",  "reddit.com"),
    ("reddit.com",                    "reddit.com"),
    ("www.reddit.com",                "reddit.com"),
    ("http://reddit.com",             "reddit.com"),
    ("https://old.reddit.com/r/x",    "old.reddit.com"),
    ("  https://x.com/home  ",        "x.com"),
    ("https://sub.domain.co.uk/a/b",  "sub.domain.co.uk"),
    ("HTTPS://WWW.REDDIT.COM",        "reddit.com"),
])
def test_rule_from_url(raw, expected):
    assert rule_from_url(raw) == expected


def test_www_is_stripped_because_it_would_leave_a_hole():
    """'www.reddit.com' as a rule would not match the bare 'reddit.com'."""
    from friction.match import host_matches
    assert not host_matches("reddit.com", "www.reddit.com")
    assert host_matches("reddit.com", rule_from_url("https://www.reddit.com"))


@pytest.mark.parametrize("bad", ["", "   ", "localhost", "not a url", "https://"])
def test_rejects_junk(bad):
    with pytest.raises(EditError):
        rule_from_url(bad)


def test_detects_exact_duplicate(config):
    assert covered_by("reddit.com", config) == ("tier2", "reddit.com")


def test_detects_subdomain_already_covered(config):
    """Adding old.reddit.com when reddit.com is already blocked is a no-op."""
    assert covered_by("old.reddit.com", config) == ("tier2", "reddit.com")


def test_unknown_site_is_not_covered(config):
    assert covered_by("example.com", config) is None


def _cfg_file(tmp_path, config):
    p = tmp_path / "config.local.json"
    p.write_text(json.dumps(config))
    return p


def test_add_site_writes_the_rule(tmp_path, config):
    p = _cfg_file(tmp_path, config)
    assert add_site("https://www.example.com/page", "tier3", p) == "example.com"
    assert "example.com" in json.loads(p.read_text())["tiers"]["tier3"]["sites"]


def test_add_site_keeps_the_list_sorted(tmp_path, config):
    p = _cfg_file(tmp_path, config)
    add_site("aaa.com", "tier2", p)
    sites = json.loads(p.read_text())["tiers"]["tier2"]["sites"]
    assert sites == sorted(sites)


def test_add_site_refuses_a_duplicate(tmp_path, config):
    p = _cfg_file(tmp_path, config)
    with pytest.raises(EditError, match="already blocked"):
        add_site("reddit.com", "tier2", p)


def test_add_site_refuses_an_already_covered_subdomain(tmp_path, config):
    p = _cfg_file(tmp_path, config)
    with pytest.raises(EditError, match="already covered"):
        add_site("https://old.reddit.com", "tier3", p)


def test_add_site_refuses_an_unknown_tier(tmp_path, config):
    p = _cfg_file(tmp_path, config)
    with pytest.raises(EditError, match="no tier named"):
        add_site("example.com", "tier9", p)


def test_add_site_leaves_the_file_valid_json(tmp_path, config):
    p = _cfg_file(tmp_path, config)
    add_site("example.com", "tier1", p)
    json.loads(p.read_text())      # raises if we corrupted it
