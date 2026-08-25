"""The menu bar UI: toggles, countdowns, and the unlock challenges.

Quitting this does not stop enforcement -- the daemon owns that. This is only
the control panel.

The menu is built once and its titles are updated in place every second. A full
rebuild each tick would make the countdowns flicker and could close the menu
while it is open.
"""

from __future__ import annotations

import functools
import logging
from datetime import datetime

import objc
import rumps
from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory,
                    NSTerminateNow)

from friction import config as cfgmod
from friction import notify
from friction import schedule as S
from friction import state as st
from friction.challenges import run as challenges

log = logging.getLogger(__name__)

LOCKED, OPEN, OFF = "🔒", "🔓", "⏸"
TICK_SECONDS = 1        # countdowns show seconds, so this has to be 1


def _countdown(until: datetime, now: datetime) -> str:
    """Format the time remaining as M:SS."""
    total = max(0, int((until - now).total_seconds()))
    return f"{total // 60}:{total % 60:02d}"


class FrictionApp(rumps.App):
    """The menu bar panel.

    Builds its menu once and updates the titles in place each second, so open
    menus do not flicker and countdowns stay live.
    """
    def __init__(self) -> None:
        """Load config, build the menu, and start the once-a-second refresh."""
        super().__init__("Friction", title=LOCKED, quit_button=None)
        self.cfg = cfgmod.load()
        self._cfg_mtime = self._mtime()
        self._entries: dict[str, rumps.MenuItem] = {}   # item key -> menu item
        self._tier_all: dict[str, rumps.MenuItem] = {}  # tier    -> "all" item
        self._add_items: dict[str, rumps.MenuItem] = {}  # tier   -> "add a site" item
        self._master: rumps.MenuItem | None = None
        self._build()
        self._timer = rumps.Timer(self._tick, TICK_SECONDS)
        self._timer.start()

    # -- structure (built once) --------------------------------------------

    def _mtime(self) -> float:
        """Modification time of the active config, used to detect edits."""
        p = cfgmod.LOCAL if cfgmod.LOCAL.exists() else cfgmod.EXAMPLE
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    def _build(self) -> None:
        """Create the menu structure and keep references for later title updates."""
        self.menu.clear()
        self._entries.clear()
        self._tier_all.clear()
        self._add_items.clear()

        # rumps keys menu items by their title, so these need DISTINCT initial
        # titles or the second silently replaces the first. Later title updates
        # do not re-key them.
        self._master = rumps.MenuItem("master", callback=self._master_clicked)
        self.menu.add(self._master)
        self.menu.add(rumps.separator)

        self._global = rumps.MenuItem("global", callback=self._global_clicked)
        self.menu.add(self._global)
        self.menu.add(rumps.separator)

        for tier, tier_cfg in self.cfg["tiers"].items():
            header = rumps.MenuItem(tier_cfg.get("label", tier))
            # Tiers 2 and 3 are per-item on purpose: one challenge must not be
            # able to open a whole tier.
            if tier_cfg.get("whole_tier_switch"):
                all_item = rumps.MenuItem(
                    f"all-{tier}", callback=functools.partial(self._tier_clicked, tier))
                self._tier_all[tier] = all_item
                header.add(all_item)
                header.add(rumps.separator)

            for item in S.items(self.cfg):
                if item.tier != tier:
                    continue
                entry = rumps.MenuItem(
                    item.target, callback=functools.partial(self._item_clicked, item))
                self._entries[item.key] = entry
                header.add(entry)

            header.add(rumps.separator)
            header.add(rumps.MenuItem(
                f"add-{tier}", callback=functools.partial(self._add_site, tier)))
            self._add_items[tier] = header[f"add-{tier}"]
            self.menu.add(header)

        # Also at the top level, not only buried at the bottom of each tier:
        # adding a site is a thing people do in the moment, so it has to be
        # findable without hunting.
        self.menu.add(rumps.separator)
        add_menu = rumps.MenuItem("＋  Add a site…")
        for tier, tier_cfg in self.cfg["tiers"].items():
            label = tier_cfg.get("label", tier)
            add_menu.add(rumps.MenuItem(
                f"to {label}", callback=functools.partial(self._add_site, tier)))
        self.menu.add(add_menu)

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Quit Friction…", callback=self._quit_clicked))
        self._refresh()

    # -- titles (updated every second) --------------------------------------

    def _tick(self, _timer) -> None:
        """Refresh titles once a second, rebuilding fully only if the config changed."""
        try:
            if self._mtime() != self._cfg_mtime:
                self.cfg = cfgmod.load()
                self._cfg_mtime = self._mtime()
                self._build()
                return
            self._refresh()
        except Exception as e:  # noqa: BLE001 - the UI must not die on a bad tick
            log.exception("refresh failed: %s", e)

    def _refresh(self) -> None:
        """Recompute every menu title from the current schedule and state."""
        now = datetime.now()
        state = st.load()
        armed = {i.key for i in S.armed(now, self.cfg, state)}
        passes = state.get("passes", {})
        all_items = S.items(self.cfg)

        # A pass only earns a countdown if something is actually being held
        # open by it. A leftover pass on an unlocked item is not news.
        holding = {i.key for i in all_items
                   if S.locked_ignoring_passes(now, i, self.cfg, state)}

        def live_expiry(key: str, tier: str | None = None):
            """Expiry of a pass, but only if something is actually locked underneath it."""
            expiry = st.parse(passes.get(key))
            if expiry is None or expiry <= now:
                return None
            if tier is not None:
                return expiry if any(i.key in holding and i.tier == tier
                                     for i in all_items) else None
            return expiry if key in holding else None

        if S.master_disarmed(now, state):
            until = st.parse(state["master_disarmed_until"])
            self.title = f"{OFF} {_countdown(until, now)}"
            self._master.title = f"{OFF}  Everything off — {_countdown(until, now)} left"
        else:
            ticking = [e for e in
                       ([live_expiry(i.key) for i in all_items]
                        + [live_expiry(t, tier=t) for t in self._tier_all])
                       if e is not None]
            soonest = min(ticking, default=None)
            self.title = (f"{OPEN} {_countdown(soonest, now)}" if soonest
                          else (LOCKED if armed else OPEN))
            self._master.title = f"{LOCKED}  Friction is on"

        n_all = len(all_items)
        g_expiry = st.parse(passes.get(S.GLOBAL_KEY))
        if S.global_lock_active(now, state):
            self._global.title = f"{LOCKED}  Unlock everything ({n_all})"
        elif g_expiry and g_expiry > now and state.get("manual_arms", {}).get(S.GLOBAL_KEY):
            self._global.title = (f"{OPEN}  Everything — "
                                  f"{_countdown(g_expiry, now)} left")
        else:
            self._global.title = f"{OPEN}  Lock everything ({n_all})"

        for tier, all_item in self._tier_all.items():
            tier_items = [i for i in all_items if i.tier == tier]
            n = len(tier_items)
            locked_now = [i for i in tier_items if i.key in armed]
            expiry = live_expiry(tier, tier=tier)

            if expiry:
                all_item.title = f"{OPEN}  All {n} — {_countdown(expiry, now)} left"
            elif len(locked_now) == n and n:
                # Only cheap tiers can be opened in one go. Elsewhere each item
                # is priced separately on purpose, so don't offer what we won't do.
                cheap = self.cfg["tiers"][tier].get("challenge") == "confirm"
                all_item.title = (f"{LOCKED}  Unlock all {n}" if cheap
                                  else f"{LOCKED}  All {n} locked")
            else:
                all_item.title = f"{OPEN}  Lock all {n}"

        for tier, add_item in self._add_items.items():
            add_item.title = "＋  Add a site…"

        for item in all_items:
            entry = self._entries.get(item.key)
            if entry is None:
                continue
            expiry = live_expiry(item.key)
            if item.key in armed:
                entry.title = f"{LOCKED}  {item.target}"
            elif expiry:
                entry.title = f"{OPEN}  {item.target} — {_countdown(expiry, now)} left"
            else:
                entry.title = f"{OPEN}  {item.target}"

    # -- actions ------------------------------------------------------------

    def _item_clicked(self, item, _sender) -> None:
        """Lock one item (free), or start its unlock challenge."""
        now, state = datetime.now(), st.load()
        if S.lock_reason(now, item, self.cfg, state):
            challenges.attempt_unlock(item, self.cfg)          # leaving costs
        else:
            st.update(lambda s: S.set_manual_arm(s, item.key, now, True))  # free
        self._refresh()

    def _tier_clicked(self, tier, _sender) -> None:
        """Lock a whole tier (free), or unlock it if the tier allows that."""
        now, state = datetime.now(), st.load()
        tier_items = [i for i in S.items(self.cfg) if i.tier == tier]
        locked = [i for i in tier_items if S.lock_reason(now, i, self.cfg, state)]

        if locked and len(locked) == len(tier_items):
            # Unlocking a whole tier at once is only offered where the tier is
            # cheap. Elsewhere each item is priced separately on purpose.
            if self.cfg["tiers"][tier].get("challenge") != "confirm":
                rumps.alert(
                    "One at a time",
                    f"{self.cfg['tiers'][tier].get('label', tier)} unlocks item by "
                    f"item — that's the point of the tier. Open the ones you need.")
                return
            challenges.attempt_unlock(tier_items[0], self.cfg, whole_tier=True)
        else:
            st.update(lambda s: [S.set_manual_arm(s, i.key, now, True)
                                 for i in tier_items] and None)
        self._refresh()

    def _add_site(self, tier, _sender) -> None:
        """Add a website to this tier from a pasted URL.

        Adding is deliberately easy -- getting stricter should never be a chore.
        Removing is not offered here; that means editing config.local.json.
        """
        from friction.edit import EditError, add_site

        label = self.cfg["tiers"][tier].get("label", tier)
        response = rumps.Window(
            message=f"Paste a link or type a domain. It goes into {label}, "
                    f"and covers subdomains automatically.",
            title="Block a site", default_text="", ok="Block it",
            cancel="Cancel", dimensions=(300, 22)).run()
        if not response.clicked or not response.text.strip():
            return
        try:
            rule = add_site(response.text, tier)
        except EditError as e:
            rumps.alert("Couldn't add it", str(e))
            return
        # The config changed on disk, so rebuild rather than just retitle.
        self.cfg = cfgmod.load()
        self._cfg_mtime = self._mtime()
        self._build()
        rumps.alert("Blocked", f"{rule} is now in {label}.")

    def _quit_clicked(self, _sender) -> None:
        """Quitting the UI leaves enforcement running with no way to unlock.

        That is a trap worth spelling out rather than discovering at 9am.
        """
        if rumps.Window(
                message="Blocking KEEPS RUNNING — quitting this only closes the "
                        "control panel.\n\nBut you'll have no way to unlock "
                        "anything until it's open again.\n\nTo reopen it:\n"
                        "    launchctl start com.friction.ui\n\n"
                        "It also reopens by itself when you next log in.",
                title="Quit the control panel?", ok="Quit anyway",
                cancel="Keep it open", dimensions=(0, 0)).run().clicked:
            rumps.quit_application()

    def _global_clicked(self, _sender) -> None:
        """Lock everything (free), or start the challenge to release it."""
        now, state = datetime.now(), st.load()
        if S.global_lock_active(now, state):
            challenges.attempt_global_unlock(self.cfg)          # leaving costs
        else:
            st.update(lambda s: S.set_global_lock(s, now, True))  # arming is free
        self._refresh()

    def _master_clicked(self, _sender) -> None:
        """Turn Friction back on, or begin the accountability-text flow to turn it off."""
        now, state = datetime.now(), st.load()
        if S.master_disarmed(now, state):
            st.update(S.rearm_master)                          # free, always
            self._refresh()
            return
        self._disarm_master()

    def _disarm_master(self) -> None:
        """No puzzle and no delay -- but your contacts get told."""
        mt = self.cfg.get("master_toggle", {})
        cfg_notify = mt.get("notify", {})
        contacts = cfg_notify.get("contacts", [])
        minutes = int(mt.get("disarm_minutes", 60))
        message = cfg_notify.get("message", "I just turned off Friction.")
        names = ", ".join((c.get("name") or c.get("handle")) if isinstance(c, dict) else c
                          for c in contacts) or "nobody (no contacts configured)"

        if not rumps.Window(
                message=f"This texts {names}:\n\n“{message}”\n\n"
                        f"Everything re-arms in {minutes} minutes.",
                title="Turn Friction off?", ok="Send it", cancel="Never mind",
                dimensions=(0, 0)).run().clicked:
            return

        if not cfg_notify.get("enabled", True) or not contacts:
            st.update(lambda s: S.disarm_master(s, datetime.now(), minutes))
            self._refresh()
            return

        results = notify.notify_contacts(contacts, message)
        if failed := [r for r in results if not r.accepted]:
            rumps.alert("Couldn't send",
                        "\n".join(f"{r.name}: {r.error}" for r in failed)
                        + "\n\nFriction stays on.")
            return

        # Delivery can't be verified without Full Disk Access, so you confirm.
        if rumps.Window(
                message=f"Sent to {', '.join(r.name for r in results)}.\n\n"
                        f"Open Messages and check it arrived, then confirm below.",
                title="Did it send?", ok="Yes, I saw it", cancel="No",
                dimensions=(0, 0)).run().clicked:
            st.update(lambda s: S.disarm_master(s, datetime.now(), minutes))
        self._refresh()


_power_off_observer = None


def _make_shutdown_safe() -> None:
    """Answer the quit request macOS sends at logout, and stop being a Dock app.

    At logout, macOS asks every GUI application to quit and WAITS for a reply.
    rumps never implements applicationShouldTerminate_, so the panel never
    answers -- shutdown stalls and eventually offers to force quit "Python".
    Measured: a polite quit went unanswered for 25s.

    Two fixes. The delegate now says yes immediately. And the process becomes an
    accessory app, which is what a menu bar app should have been all along --
    no Dock icon, no app switcher entry.
    """
    from rumps.rumps import NSApp as RumpsDelegate

    if not RumpsDelegate.instancesRespondToSelector_("applicationShouldTerminate:"):
        def applicationShouldTerminate_(self, sender):   # noqa: N802 - ObjC selector
            return NSTerminateNow

        objc.classAddMethods(RumpsDelegate, [
            objc.selector(applicationShouldTerminate_,
                          selector=b"applicationShouldTerminate:",
                          signature=b"Q@:@")])

    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyAccessory)

    # The quit Apple Event is never delivered to this process -- verified: an
    # explicit handler for it never fired. So instead of waiting to be asked,
    # listen for the shutdown itself and leave. NSWorkspace notifications DO
    # reach us; the app blocker already depends on that working.
    from AppKit import (NSWorkspace, NSWorkspaceWillPowerOffNotification)
    from Foundation import NSObject

    class _PowerOff(NSObject):
        def powerOff_(self, note):                       # noqa: N802 - ObjC selector
            log.info("shutdown starting; quitting so it doesn't wait for us")
            rumps.quit_application()

    global _power_off_observer
    _power_off_observer = _PowerOff.alloc().init()
    NSWorkspace.sharedWorkspace().notificationCenter() \
        .addObserver_selector_name_object_(
            _power_off_observer, "powerOff:",
            NSWorkspaceWillPowerOffNotification, None)


def run() -> int:
    """Start the menu bar app. Blocks until quit."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    app = FrictionApp()
    _make_shutdown_safe()
    app.run()
    return 0
