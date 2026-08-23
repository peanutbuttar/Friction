"""Human-readable answer to 'what is blocked right now, and why?'"""

from __future__ import annotations

from datetime import datetime

from friction import config as cfgmod
from friction import schedule as S
from friction import state as st


def run(when: datetime | None = None) -> int:
    now = when or datetime.now()
    cfg = cfgmod.load()
    state = st.load()

    armed = S.armed(now, cfg, state)
    armed_keys = {i.target for i in armed}

    print(f"\n\033[1mFriction — status at {now.strftime('%a %H:%M')}\033[0m\n")

    if S.master_disarmed(now, state):
        until = st.parse(state["master_disarmed_until"])
        print(f"  \033[33mMASTER TOGGLE OFF\033[0m — everything unblocked until "
              f"{until.strftime('%H:%M')}\n")

    for tier, tc in cfg["tiers"].items():
        sched = tc.get("schedule", {})
        window = ("manual only" if sched.get("mode") != "daily"
                  else f"{sched['arms']}–{sched['releases']}")
        on = S.in_schedule_window(now, tc)
        label = "\033[31mARMED\033[0m" if on else "\033[2mopen\033[0m"
        print(f"\033[1m{tier}\033[0m  {window:14} {label}  "
              f"\033[2m{tc['challenge']}, {tc['unlock_minutes']}min\033[0m")

        for item in sorted(S.items(cfg), key=lambda i: (i.kind, i.target)):
            if item.tier != tier:
                continue
            if item.target in armed_keys:
                mark, why = "\033[31m✗\033[0m", "blocked"
            elif S.pass_active(now, item.key, state):
                exp = st.parse(state["passes"][item.key])
                mark, why = "\033[32m✓\033[0m", f"unlocked until {exp.strftime('%H:%M')}"
            else:
                mark, why = "\033[2m·\033[0m", "open"
            print(f"    {mark} {item.target:32} \033[2m{why}\033[0m")
        print()

    print(f"  {len(armed)} item(s) blocked right now.\n")
    return 0
