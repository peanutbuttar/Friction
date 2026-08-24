"""Closing blocked browser tabs via ScriptingBridge.

ScriptingBridge rather than shelling out to osascript: it keeps a persistent
connection, saving ~21ms of process spawn per sweep (measured; see SPEC.md 3).
It does not avoid the ~86ms Apple Event round trip, which is why sweeps are
every 10s rather than every second.

IMPORTANT: an unanswered TCC consent dialog blocks these calls indefinitely
(SPEC.md 3.2). Callers must run sweeps off any thread that matters.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from friction.match import hostname, url_matches_any

log = logging.getLogger(__name__)

BROWSERS = {
    "safari": ("Safari", "com.apple.Safari"),
    "chrome": ("Google Chrome", "com.google.Chrome"),
    "arc": ("Arc", "company.thebrowser.Browser"),
}


@dataclass
class Closed:
    """One tab that was closed (or would be, in a dry run), and the rule it tripped."""
    browser: str
    url: str
    rule: str


def _app(bundle_id: str):
    """A ScriptingBridge handle, or None if the browser isn't running.

    Checking isRunning() first matters: touching a stopped SBApplication would
    launch the browser, which is the opposite of what a blocker should do.
    """
    try:
        from ScriptingBridge import SBApplication
    except ImportError:
        log.error("ScriptingBridge unavailable; cannot sweep browsers")
        return None
    app = SBApplication.applicationWithBundleIdentifier_(bundle_id)
    if app is None or not app.isRunning():
        return None
    return app


def _tabs(app):
    """Every (window, tab) pair. Tolerates browsers that disagree on shape."""
    try:
        windows = app.windows() or []
    except Exception as e:  # noqa: BLE001 - Apple Events fail in creative ways
        log.warning("could not list windows: %s", e)
        return
    for window in windows:
        try:
            for tab in (window.tabs() or []):
                yield window, tab
        except Exception as e:  # noqa: BLE001
            log.debug("could not list tabs: %s", e)


def sweep_browser(key: str, rules: list[str], dry_run: bool = False) -> list[Closed]:
    """Close every tab in one browser matching `rules`. Returns what it closed."""
    name, bundle_id = BROWSERS[key]
    app = _app(bundle_id)
    if app is None:
        return []

    hits: list[Closed] = []
    for _window, tab in _tabs(app):
        try:
            url = tab.URL()
        except Exception:  # noqa: BLE001
            continue
        rule = url_matches_any(url or "", rules)
        if rule is None:
            continue
        hits.append(Closed(browser=name, url=url, rule=rule))
        if dry_run:
            continue
        try:
            tab.close()
        except Exception as e:  # noqa: BLE001
            log.warning("%s: could not close %s: %s", name, url, e)
    return hits


def sweep(rules: list[str], enabled: dict[str, bool], dry_run: bool = False) -> list[Closed]:
    """Sweep every enabled, running browser."""
    if not rules:
        return []
    out: list[Closed] = []
    for key, on in enabled.items():
        if on and key in BROWSERS:
            out.extend(sweep_browser(key, rules, dry_run=dry_run))
    return out


def list_open_tabs(enabled: dict[str, bool]) -> list[tuple[str, str]]:
    """(browser, url) for every open tab. Diagnostics only."""
    out = []
    for key, on in enabled.items():
        if not on or key not in BROWSERS:
            continue
        name, bundle_id = BROWSERS[key]
        app = _app(bundle_id)
        if app is None:
            continue
        for _w, tab in _tabs(app):
            try:
                if (h := hostname(tab.URL() or "")):
                    out.append((name, h))
            except Exception:  # noqa: BLE001
                continue
    return out
