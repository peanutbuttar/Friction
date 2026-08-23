"""Deciding whether a URL matches a block rule.

Kept separate and pure because the cost of getting it wrong runs both ways: too
loose and Friction closes tabs it shouldn't, too tight and the block has a hole
the reflex will find on its own.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Schemes that can't be a distraction and must never be touched. Closing a
# blank or settings tab would be confusing and pointless.
IGNORED_SCHEMES = {"about", "chrome", "chrome-extension", "safari-web-extension",
                   "file", "data", "javascript", "arc", "edge", ""}


def hostname(url: str) -> str | None:
    """Bare lowercase host, or None if this URL isn't worth considering."""
    if not url:
        return None
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme.lower() in IGNORED_SCHEMES:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    return host or None


def host_matches(host: str, rule: str) -> bool:
    """True if `host` is `rule` or a subdomain of it.

    'reddit.com' matches reddit.com, www.reddit.com and old.reddit.com, but not
    notreddit.com -- the dot boundary is what stops the suffix check being wrong.
    """
    host, rule = host.lower().rstrip("."), rule.lower().rstrip(".").lstrip("*.")
    return host == rule or host.endswith("." + rule)


def url_matches_any(url: str, rules: list[str]) -> str | None:
    """The first rule this URL trips, or None."""
    host = hostname(url)
    if host is None:
        return None
    for rule in rules:
        if host_matches(host, rule):
            return rule
    return None
