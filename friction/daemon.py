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
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
    )


class Daemon:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self._stop = threading.Event()
        self._cfg = cfgmod.load()
        self._cfg_mtime = self._config_mtime()
        self._app_blocker = AppBlocker(armed_apps=self.armed_apps)

    # -- current decisions, recomputed on demand ----------------------------

    def _config_mtime(self) -> float:
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
        return S.armed(now or datetime.now(), self._cfg, st.load())

    def armed_apps(self) -> set[str]:
        return {i.target for i in self._armed() if i.kind == "app"}

    def armed_sites(self) -> list[str]:
        return [i.target for i in self._armed() if i.kind == "site"]

    # -- the browser thread -------------------------------------------------

    def _sweep_loop(self) -> None:
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
        from Foundation import NSRunLoop
        from AppKit import NSApplication  # noqa: F401 - initialises the app context

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
    _setup_logging(verbose)
    try:
        return Daemon(dry_run=dry_run).run()
    except cfgmod.ConfigError as e:
        log.error("cannot start: %s", e)
        return 1
