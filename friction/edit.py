"""Adding and removing blocklist entries from config.local.json.

Deliberately asymmetric: adding is easy and can be done from the menu bar in
the moment you notice something pulling at you. Removing is not offered in the
UI at all -- you edit the file. That is the same principle as the rest of
Friction: getting stricter is free, getting laxer should take effort.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from friction import config as cfgmod
from friction.match import host_matches


class EditError(Exception):
    """Raised when a blocklist edit cannot be applied."""


def rule_from_url(raw: str) -> str:
    """Turn anything a person might paste into a block rule.

    Accepts a full URL, a bare domain, or something with a path attached, and
    returns the domain to match on.

    Strips a leading 'www.' on purpose. Subdomain matching runs downwards, so a
    rule of 'reddit.com' covers 'www.reddit.com' -- but a rule of
    'www.reddit.com' would NOT cover the bare 'reddit.com', which is exactly the
    hole someone would find by accident.
    """
    text = (raw or "").strip()
    if not text:
        raise EditError("no URL given")
    if "://" not in text:
        text = "https://" + text          # urlparse needs a scheme to find a host

    host = (urlparse(text).hostname or "").lower().rstrip(".")
    if not host:
        raise EditError(f"could not read a domain from {raw!r}")
    if "." not in host:
        raise EditError(f"{host!r} doesn't look like a domain")

    if host.startswith("www."):
        host = host[4:]
    return host


def covered_by(rule: str, config: dict) -> tuple[str, str] | None:
    """If this rule is already blocked, say which tier and which existing rule.

    Catches both the exact duplicate and the subtler case of adding
    'old.reddit.com' when 'reddit.com' is already covering it.
    """
    for tier, tier_cfg in config["tiers"].items():
        for existing in tier_cfg.get("sites", []):
            if host_matches(rule, existing):
                return tier, existing
    return None


def add_site(raw_url: str, tier: str, path: Path | None = None) -> str:
    """Add a site to a tier's blocklist. Returns the rule that was added."""
    path = path or cfgmod.LOCAL
    if not path.exists():
        raise EditError(f"{path.name} does not exist; run ./install.sh first")

    rule = rule_from_url(raw_url)
    config = json.loads(path.read_text())

    if tier not in config["tiers"]:
        raise EditError(f"no tier named {tier!r} "
                        f"(have: {', '.join(config['tiers'])})")

    if (hit := covered_by(rule, config)) is not None:
        found_tier, found_rule = hit
        if found_rule == rule:
            raise EditError(f"{rule} is already blocked in {found_tier}")
        raise EditError(f"{rule} is already covered by {found_rule!r} in {found_tier}")

    config["tiers"][tier].setdefault("sites", []).append(rule)
    config["tiers"][tier]["sites"].sort()
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    return rule
