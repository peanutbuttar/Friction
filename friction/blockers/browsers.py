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


# Safari's scripting dictionary gives its tab class properties but no close
# command, and ScriptingBridge exposes no way to close one -- tab.close() raises
# and closeSaving:savingIn: silently does nothing. AppleScript CAN close a Safari
# tab, so that is the route for Safari alone. URLs are passed as arguments rather
# than pasted into the script, so a URL containing a quote cannot break it.
_SAFARI_CLOSE = [
    "-e", "on run argv",
    "-e", 'tell application "Safari"',
    "-e", "repeat with w in windows",
    # Backwards: closing a tab renumbers the ones after it.
    "-e", "repeat with i from (count of tabs of w) to 1 by -1",
    "-e", "set t to tab i of w",
    "-e", "if (URL of t) is in argv then close t",
    "-e", "end repeat",
    "-e", "end repeat",
    "-e", "end tell",
    "-e", "end run",
]


def _tab_urls(app) -> set[str]:
    """Every URL currently open, for confirming what actually closed."""
    out = set()
    for _w, tab in _tabs(app):
        try:
            out.add(tab.URL() or "")
        except Exception:  # noqa: BLE001
            continue
    return out


def _close_safari(urls: list[str]) -> None:
    import subprocess
    try:
        p = subprocess.run(["osascript", *_SAFARI_CLOSE, *urls],
                           capture_output=True, text=True, timeout=30)
        if p.returncode != 0:
            log.warning("Safari: close failed: %s", (p.stderr or p.stdout).strip())
    except subprocess.TimeoutExpired:
        log.warning("Safari: close timed out")


def sweep_browser(key: str, rules: list[str], dry_run: bool = False) -> list[Closed]:
    """Close every tab in one browser matching `rules`.

    Returns only the tabs that actually went away. Reporting a tab as closed
    without checking is how Safari looked like it was working for weeks while
    closing nothing at all.
    """
    name, bundle_id = BROWSERS[key]
    app = _app(bundle_id)
    if app is None:
        return []

    matches: list[tuple[object, str, str]] = []
    for _window, tab in _tabs(app):
        try:
            url = tab.URL()
        except Exception:  # noqa: BLE001
            continue
        rule = url_matches_any(url or "", rules)
        if rule is not None:
            matches.append((tab, url, rule))

    if not matches:
        return []
    if dry_run:
        return [Closed(browser=name, url=u, rule=r) for _t, u, r in matches]

    if key == "safari":
        _close_safari([u for _t, u, _r in matches])
    else:
        for tab, url, _rule in matches:
            try:
                tab.close()
            except Exception as e:  # noqa: BLE001
                log.warning("%s: could not close %s: %s", name, url, e)

    still_open = _tab_urls(app)
    closed = [Closed(browser=name, url=u, rule=r)
              for _t, u, r in matches if u not in still_open]
    if len(closed) < len(matches):
        survived = [u for _t, u, _r in matches if u in still_open]
        log.warning("%s: %d tab(s) would not close: %s", name, len(survived),
                    ", ".join(s[:60] for s in survived))
    return closed


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
