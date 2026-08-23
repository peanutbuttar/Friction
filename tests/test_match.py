import pytest

from friction.match import host_matches, hostname, url_matches_any

RULES = ["reddit.com", "x.com", "youtube.com", "itch.io"]


@pytest.mark.parametrize("url,expected", [
    ("https://reddit.com/r/all",          "reddit.com"),
    ("https://www.reddit.com/",           "reddit.com"),
    ("https://old.reddit.com/r/all",      "reddit.com"),   # the classic workaround
    ("https://m.reddit.com/",             "reddit.com"),
    ("http://reddit.com:8080/x",          "reddit.com"),
    ("https://x.com/home",                "x.com"),
    ("https://itch.io/games",             "itch.io"),
    ("https://REDDIT.COM/",               "reddit.com"),   # case insensitive
])
def test_blocked_urls(url, expected):
    assert url_matches_any(url, RULES) == expected


@pytest.mark.parametrize("url", [
    "https://notreddit.com/",       # suffix without a dot boundary must NOT match
    "https://reddit.com.evil.net/", # rule appearing mid-host must NOT match
    "https://github.com/",
    "https://myx.com/",
])
def test_allowed_urls(url):
    assert url_matches_any(url, RULES) is None


@pytest.mark.parametrize("url", [
    "about:blank", "chrome://settings", "file:///Users/x/notes.txt", "", "   ",
])
def test_non_web_urls_are_ignored(url):
    """Closing a blank or settings tab would be pointless and confusing."""
    assert hostname(url) is None
    assert url_matches_any(url, RULES) is None


def test_dot_boundary_is_what_makes_this_safe():
    assert host_matches("old.reddit.com", "reddit.com")
    assert not host_matches("notreddit.com", "reddit.com")
    assert not host_matches("reddit.com.evil.net", "reddit.com")


def test_trailing_dot_fqdn():
    assert host_matches("reddit.com.", "reddit.com")
