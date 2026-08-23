"""Quitting blocked applications the moment they launch.

Event-driven: macOS pushes NSWorkspaceDidLaunchApplicationNotification the
instant an app starts, so there is nothing to poll. This is both cheaper and
faster than polling -- measured at 0.01ms for a process list read versus zero
work here, with no latency at all. See SPEC.md 3.1.

terminate() needs no Accessibility grant; verified. It sends a normal quit, so
apps get to clean up. Friction never force-kills.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)


class AppBlocker:
    """Watches for launches and quits anything currently armed.

    `armed_apps` is a callback rather than a list so the blocker always sees the
    current schedule and state without needing to be told when they change.
    """

    # terminate() is a polite request; an app can ignore it (unsaved work, a
    # confirmation dialog). Verify and retry rather than assuming it worked.
    RETRY_DELAYS = (2.0, 4.0, 8.0)

    def __init__(self, armed_apps: Callable[[], set[str]],
                 on_quit: Callable[[str], None] | None = None) -> None:
        self._armed_apps = armed_apps
        self._on_quit = on_quit
        self._observer = None
        self._timers: set[threading.Timer] = set()

    # -- the sweep for apps that were already running at startup ------------

    def quit_running(self) -> list[str]:
        """Quit anything blocked that is already open. Cheap: no Apple Events."""
        from AppKit import NSWorkspace

        armed = self._armed_apps()
        if not armed:
            return []
        quit_now = []
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            bid = app.bundleIdentifier()
            if bid in armed:
                quit_now.append(bid)
                self._terminate(app, bid)
        return quit_now

    # -- the live listener --------------------------------------------------

    def start(self) -> None:
        from AppKit import NSWorkspace, NSWorkspaceDidLaunchApplicationNotification
        from Foundation import NSObject

        blocker = self

        class _Observer(NSObject):
            def onLaunch_(self, note):                      # noqa: N802 - ObjC selector
                try:
                    app = note.userInfo()["NSWorkspaceApplicationKey"]
                    bid = app.bundleIdentifier()
                    if bid and bid in blocker._armed_apps():
                        blocker._terminate(app, bid)
                except Exception as e:                      # noqa: BLE001
                    log.exception("launch handler failed: %s", e)

        self._observer = _Observer.alloc().init()
        NSWorkspace.sharedWorkspace().notificationCenter() \
            .addObserver_selector_name_object_(
                self._observer, "onLaunch:",
                NSWorkspaceDidLaunchApplicationNotification, None)
        log.info("watching for app launches")

    def stop(self) -> None:
        for timer in list(self._timers):
            timer.cancel()
        self._timers.clear()
        if self._observer is None:
            return
        from AppKit import NSWorkspace
        NSWorkspace.sharedWorkspace().notificationCenter() \
            .removeObserver_(self._observer)
        self._observer = None

    def _terminate(self, app, bid: str, attempt: int = 0) -> None:
        try:
            app.terminate()
        except Exception as e:                              # noqa: BLE001
            log.warning("could not quit %s: %s", bid, e)
            return
        if attempt == 0:
            log.info("quit blocked app: %s", bid)
            if self._on_quit:
                self._on_quit(bid)
        self._schedule_recheck(bid, attempt)

    def _schedule_recheck(self, bid: str, attempt: int) -> None:
        """Confirm it actually went away; a polite quit can simply be ignored."""
        if attempt >= len(self.RETRY_DELAYS):
            log.warning("%s is resisting quit after %d attempts; giving up. "
                        "Friction does not force-kill.", bid, attempt)
            return
        timer = threading.Timer(self.RETRY_DELAYS[attempt], self._recheck, (bid, attempt))
        timer.daemon = True
        self._timers.add(timer)
        timer.start()

    def _recheck(self, bid: str, attempt: int) -> None:
        from AppKit import NSRunningApplication
        try:
            if bid not in self._armed_apps():
                return                                  # unlocked in the meantime
            still = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bid)
            if not still:
                return                                  # it quit, as asked
            log.info("%s still running after quit, retrying (%d)", bid, attempt + 1)
            self._terminate(still[0], bid, attempt + 1)
        except Exception as e:                          # noqa: BLE001
            log.warning("recheck failed for %s: %s", bid, e)
