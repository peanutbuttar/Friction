"""The enforcement daemon.

Threading matters here. An unanswered TCC consent dialog blocks an Apple Event
call indefinitely (SPEC.md 3.2), so browser sweeps run on their own thread. If
they ran on the main thread, one unanswered dialog would freeze app blocking too
-- and Friction would look alive while enforcing nothing.

  main thread   NSRunLoop + NSWorkspace launch notifications  (app blocking)
  sweep thread  browser tab sweep every N seconds             (site blocking)
"""

from __future__ import annotations

import logging
import signal
import threading
from datetime import datetime
from pathlib import Path

from friction import config as cfgmod
from friction import schedule as S
from friction import state as st
from friction.blockers import browsers
from friction.blockers.apps import AppBlocker

log = logging.getLogger("frictiond")

LOG_PATH = st.STATE_DIR / "frictiond.log"


def _setup_logging(verbose: bool = False) -> None:
    """Send logs to both a file and stdout (which launchd captures)."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
    )


class Daemon:
    """Owns the enforcement loop and the two blockers."""
    def __init__(self, dry_run: bool = False) -> None:
        """Load config and prepare the app blocker. Nothing starts until run()."""
        self.dry_run = dry_run
        self._stop = threading.Event()
        self._cfg = cfgmod.load()
        self._cfg_mtime = self._config_mtime()
        self._app_blocker = AppBlocker(armed_apps=self.armed_apps)

    # -- current decisions, recomputed on demand ----------------------------

    def _config_mtime(self) -> float:
        """Modification time of the active config, used to detect edits."""
        p = cfgmod.LOCAL if cfgmod.LOCAL.exists() else cfgmod.EXAMPLE
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    def _maybe_reload_config(self) -> None:
        """Pick up config edits without needing a restart."""
        mtime = self._config_mtime()
        if mtime != self._cfg_mtime:
            try:
                self._cfg = cfgmod.load()
                self._cfg_mtime = mtime
                log.info("config reloaded")
            except cfgmod.ConfigError as e:
                log.error("config reload failed, keeping previous: %s", e)

    def _armed(self, now: datetime | None = None):
        # State is re-read every time: the UI writes it, and a stale read here
        # would either enforce through a valid pass or miss a new arm.
        """The set of items that should be blocked right now."""
        return S.armed(now or datetime.now(), self._cfg, st.load())

    def armed_apps(self) -> set[str]:
        """Bundle IDs that should be blocked right now."""
        return {d for i in self._armed() if i.kind == "app" for d in i.domains}

    def armed_sites(self) -> list[str]:
        """Domain rules that should be blocked right now."""
        # Flattened: an item may cover several domains (x.com AND twitter.com),
        # and the matcher needs each one, not the display label joining them.
        return [d for i in self._armed() if i.kind == "site" for d in i.domains]

    # -- the browser thread -------------------------------------------------

    def _sweep_loop(self) -> None:
        """Browser sweep loop. Runs on its own thread; see the module docstring."""
        interval = self._cfg.get("poll", {}).get("browser_sweep_seconds", 10)
        enabled = {k: v for k, v in self._cfg.get("browsers", {}).items()
                   if not k.startswith("_")}
        log.info("browser sweep every %ss (%s)", interval,
                 ", ".join(k for k, v in enabled.items() if v) or "none enabled")

        while not self._stop.is_set():
            try:
                self._maybe_reload_config()
                rules = self.armed_sites()
                if rules:
                    closed = browsers.sweep(rules, enabled, dry_run=self.dry_run)
                    for c in closed:
                        verb = "would close" if self.dry_run else "closed"
                        log.info("%s %s tab: %s (rule %s)", verb, c.browser,
                                 c.url[:80], c.rule)
            except Exception as e:  # noqa: BLE001 - the loop must never die
                log.exception("sweep failed: %s", e)
            self._stop.wait(interval)

    # -- lifecycle ----------------------------------------------------------

    def run(self) -> int:
        """Start enforcement and block until stopped."""
        from Foundation import NSRunLoop
        from AppKit import NSApplication, NSApplicationActivationPolicyProhibited

        # Without this the daemon registers as a REGULAR application, so macOS
        # asks it to quit at logout and waits for an answer it cannot give --
        # it has no bundle, so the quit Apple Event is never delivered. Result:
        # shutdown stalls and offers to force quit "Python". It has no UI, so
        # Prohibited is what it should have been. launchd still stops it with
        # SIGTERM, which it handles in ~0.4s.
        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyProhibited)

        log.info("frictiond starting%s", " (DRY RUN)" if self.dry_run else "")
        log.info("%d items armed right now", len(self._armed()))

        if not self.dry_run:
            already = self._app_blocker.quit_running()
            if already:
                log.info("quit already-running blocked apps: %s", ", ".join(already))

        self._app_blocker.start()

        sweeper = threading.Thread(target=self._sweep_loop, name="sweep", daemon=True)
        sweeper.start()

        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: self._stop.set())

        loop = NSRunLoop.currentRunLoop()
        while not self._stop.is_set():
            # Short slices so the stop flag is noticed promptly.
            loop.runUntilDate_(__import__("Foundation").NSDate
                               .dateWithTimeIntervalSinceNow_(0.5))

        log.info("frictiond stopping")
        self._app_blocker.stop()
        return 0


def run(dry_run: bool = False, verbose: bool = False) -> int:
    """Start enforcement and block until stopped."""
    _setup_logging(verbose)
    try:
        return Daemon(dry_run=dry_run).run()
    except cfgmod.ConfigError as e:
        log.error("cannot start: %s", e)
        return 1
