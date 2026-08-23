"""The menu bar UI: toggles, and the unlock challenges.

Quitting this does not stop enforcement -- the daemon owns that. This is only
the control panel.
"""

from __future__ import annotations

import functools
import logging
from datetime import datetime

import rumps

from friction import config as cfgmod
from friction import notify
from friction import schedule as S
from friction import state as st
from friction.challenges import run as challenges

log = logging.getLogger(__name__)

ARMED_ICON, OPEN_ICON, OFF_ICON = "🔒", "🔓", "⏸"
REFRESH_SECONDS = 5


class FrictionApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("Friction", title=ARMED_ICON, quit_button=None)
        self.cfg = cfgmod.load()
        self._timer = rumps.Timer(self._tick, REFRESH_SECONDS)
        self._timer.start()
        self._rebuild()

    # -- current picture ----------------------------------------------------

    def _now(self) -> datetime:
        return datetime.now()

    def _snapshot(self):
        state = st.load()
        now = self._now()
        return now, state, {i.key for i in S.armed(now, self.cfg, state)}

    def _tick(self, _timer) -> None:
        try:
            self._rebuild()
        except Exception as e:  # noqa: BLE001 - the UI must not die on a bad tick
            log.exception("refresh failed: %s", e)

    # -- menu ---------------------------------------------------------------

    def _rebuild(self) -> None:
        now, state, armed_keys = self._snapshot()
        master_off = S.master_disarmed(now, state)

        self.title = OFF_ICON if master_off else (ARMED_ICON if armed_keys else OPEN_ICON)

        self.menu.clear()

        if master_off:
            until = st.parse(state["master_disarmed_until"])
            self.menu.add(rumps.MenuItem(
                f"{OFF_ICON}  Everything off until {until:%H:%M}", callback=self._rearm_master))
            self.menu.add(rumps.MenuItem("Turn it all back on now", callback=self._rearm_master))
        else:
            self.menu.add(rumps.MenuItem(
                f"{ARMED_ICON}  Friction is on", callback=self._disarm_master))

        self.menu.add(rumps.separator)

        for tier, tier_cfg in self.cfg["tiers"].items():
            self._add_tier(tier, tier_cfg, now, state, armed_keys)

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Quit (enforcement keeps running)",
                                     callback=lambda _: rumps.quit_application()))

    def _add_tier(self, tier, tier_cfg, now, state, armed_keys) -> None:
        label = tier_cfg.get("label", tier)
        sched = tier_cfg.get("schedule", {})
        window = ("manual" if sched.get("mode") != "daily"
                  else f"{sched['arms']}–{sched['releases']}")
        whole_tier = tier_cfg.get("toggle_granularity") == "tier"

        header = rumps.MenuItem(f"{label}  ({window})")

        if whole_tier:
            # Tier 1 toggles as a single unit, so its header IS the control.
            on = tier in armed_keys
            header.title = f"{ARMED_ICON if on else OPEN_ICON}  {label}  ({window})"
            header.set_callback(functools.partial(self._toggle_tier, tier))
            self.menu.add(header)
            return

        for item in S.items(self.cfg):
            if item.tier != tier:
                continue
            header.add(self._item_entry(item, tier_cfg, now, state, armed_keys))
        self.menu.add(header)

    def _item_entry(self, item, tier_cfg, now, state, armed_keys) -> rumps.MenuItem:
        if item.key in armed_keys:
            title = f"{ARMED_ICON}  {item.target}"
        elif S.pass_active(now, item.key, state):
            until = st.parse(state["passes"][item.key])
            title = f"{OPEN_ICON}  {item.target} — until {until:%H:%M}"
        else:
            title = f"{OPEN_ICON}  {item.target}"
        entry = rumps.MenuItem(title, callback=functools.partial(self._toggle_item, item))
        return entry

    # -- actions ------------------------------------------------------------

    def _toggle_item(self, item, _sender) -> None:
        now, state, armed_keys = self._snapshot()
        if item.key in armed_keys:
            challenges.attempt_unlock(item, self.cfg)      # leaving costs
        else:
            st.update(lambda s: S.set_manual_arm(s, item.key, now, True))  # arming is free
        self._rebuild()

    def _toggle_tier(self, tier, _sender) -> None:
        now, state, armed_keys = self._snapshot()
        item = next(i for i in S.items(self.cfg) if i.tier == tier)
        if tier in armed_keys:
            challenges.attempt_unlock(item, self.cfg)
        else:
            st.update(lambda s: S.set_manual_arm(s, tier, now, True))
        self._rebuild()

    def _rearm_master(self, _sender) -> None:
        st.update(S.rearm_master)                          # free, always
        self._rebuild()

    def _disarm_master(self, _sender) -> None:
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
            self._rebuild()
            return

        results = notify.notify_contacts(contacts, message)
        failed = [r for r in results if not r.accepted]
        if failed:
            rumps.alert("Couldn't send",
                        "\n".join(f"{r.name}: {r.error}" for r in failed)
                        + "\n\nFriction stays on.")
            return

        # Delivery can't be verified without Full Disk Access, so you confirm.
        sent_to = ", ".join(r.name for r in results)
        if rumps.Window(
                message=f"Sent to {sent_to}.\n\nOpen Messages and check it arrived, "
                        f"then confirm below.",
                title="Did it send?", ok="Yes, I saw it", cancel="No",
                dimensions=(0, 0)).run().clicked:
            st.update(lambda s: S.disarm_master(s, datetime.now(), minutes))
        self._rebuild()


def run() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    FrictionApp().run()
    return 0
