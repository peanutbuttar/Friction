# Friction — Specification

A macOS distraction blocker built on the idea that the problem isn't access, it's
*easy* access. Blocked sites and apps aren't unavailable — they cost something to
reach, and the cost scales with how much of a hole the thing is.

Three tiers. Tier 1 asks you to confirm. Tier 2 makes you do arithmetic. Tier 3 makes
you retype the first page of a novel.

---

## 1. Behaviour

### 1.1 Enforcement

Two processes share a state file:

- **`frictiond`** — background daemon managed by launchd. Owns the schedule and the
  enforcement loop, and restarts itself if killed. Quitting the UI does not stop
  enforcement.
- **Menu bar UI** — toggle panel and unlock challenges.

**Applications** are blocked by subscribing to `NSWorkspaceDidLaunchApplicationNotification`.
The OS pushes a notification the instant an app launches; if it is blocked and armed,
the daemon calls `terminate()` on it. There is **no polling** for apps.

**Websites** are blocked by enumerating open browser tabs via AppleScript and closing
any that match a rule. This must be polled; default sweep is every 10 seconds, and
browsers that aren't running are skipped entirely.

**Site matching** is by domain *and all subdomains*: a rule of `reddit.com` matches
`reddit.com`, `www.reddit.com`, `old.reddit.com` and `m.reddit.com`. It does not match
unrelated domains owned by the same service, so `x.com`/`twitter.com`,
`youtube.com`/`youtu.be` and `hbomax.com`/`max.com` must each be listed.

Firefox does not expose its tabs to AppleScript, so it is treated as a blocked
**application** rather than a swept browser.

### 1.2 Tiers

| | Arms | Releases | Unlock challenge | Pass duration |
|---|---|---|---|---|
| **Tier 1** | manual | manual | Confirm | 30 min |
| **Tier 2** | 06:00 daily | 18:00 | Confirm, then one arithmetic problem | 15 min |
| **Tier 3** | 06:00 daily | 20:00 | Confirm, then transcribe a 200–500 word passage | 5 min |

**Every tier confirms first.** The extra friction of tiers 2 and 3 comes *after* the
"are you sure?", never instead of it.

**One global switch** locks every app and site at once. Locking is free; unlocking
costs a confirmation plus the transcription. Critically, its unlock releases **only
the global lock** -- schedule locks and per-item locks survive it. Otherwise one
transcription at noon would open all 23 items and bypass the tier system entirely.

**Only tier 1 has a whole-tier switch** (`whole_tier_switch`). Tiers 2 and 3 are
per-item on purpose, so a single challenge cannot open a whole tier.

Every tier can be toggled **both as a whole and item by item**. Unlocking one item
while its whole tier is locked releases only that item; the tier-wide lock is split
into individual locks on everything else. Whole-tier *unlock* is only offered where
the challenge is a bare confirm -- elsewhere each item is priced separately on
purpose. Whole-tier *lock* is always available, because arming is always free.

Durations are per-tier and configurable. The intended shape is that **the worst holes
get the shortest leash** — Tier 3 costs several minutes of transcription and returns
five. That ratio is the point, not an accident.

### 1.3 Unlock semantics

**The terms depend on why it was locked.** A schedule lock is temporary by nature, so
beating it grants a short pass. A lock the user applied by hand is not on a clock, and
timing its unlock out would just mean redoing the challenge repeatedly all evening:

| Locked by | Kind | Unlock buys |
|---|---|---|
| schedule | anything | the tier's `unlock_minutes` (15 / 5) |
| by hand | app | **no timer** -- open until re-locked, or until 06:00 arms it |
| by hand | site, `manual_unlock_mode: choice` | user picks: `manual_unlock_minutes` (30), or untimed |
| by hand | site, `manual_unlock_mode: always_timed` | always 30 min |

Tier 3 is `always_timed`; tiers 1 and 2 offer the choice.


- **Per-item, not per-tier.** Passing a challenge for `reddit.com` unlocks
  `reddit.com` only. Every entry is priced separately.
- **Timed.** A pass buys minutes, not the rest of the day.
- **Expires silently.** Nothing announces the end of a pass; enforcement simply resumes.
- **Arming is always free.** Turning blocking *on* costs nothing at any tier, at any
  time. Only leaving costs.

### 1.4 Schedule and overnight

Between a tier's release time and the next 06:00 the tier is genuinely open — no
dialogs, no challenges. Any tier or item may still be **manually armed at any hour**,
at Tier 1 granularity (whole tier) or Tier 2/3 granularity (individual item).

A manually-armed tier or item stays armed until it is manually disarmed — which costs
that tier's challenge — or until the next scheduled arm/release boundary, whichever
comes first.

### 1.5 Master toggle

One switch arms or disarms everything.

- Turning it **on** is free.
- Turning it **off** has no dialog, no puzzle, and no delay. It texts the
  accountability contacts in `config.local.json` via iMessage, then requires the user
  to confirm they saw the message land before disarming.
- The disarm is timed. Everything re-arms after 60 minutes.

**On "confirmed sent":** AppleScript's `send` returns as soon as Messages *accepts*
the command; it is not a delivery receipt. Verifying real delivery would mean reading
`~/Library/Messages/chat.db`, which requires Full Disk Access. Friction deliberately
does **not** require FDA, so confirmation is manual: the UI shows the message it sent
and the user attests they saw it. This is self-administered, and that is a known and
accepted weakness.

### 1.6 Blocked tab handling

Matching tabs are **closed**. If a blocked tab is the only tab in its window, the
window closes with it. This is accepted behaviour.

### 1.7 Challenges

**Confirm** — a dialog. Nothing else.

**Arithmetic** — one generated problem, 2-digit operands by default.

**Transcription** — a 200–500 word passage, alternating between the opening of
*Moby-Dick* (266 words) and the opening of *The Great Gatsby* (252 words). Both are
public domain in the United States and bundled in `friction/passages/`.

Matching is **forgiving**: whitespace, case, and punctuation are normalized before
comparison, and a small typo budget (default 2% of characters) is allowed. The source
texts come from Project Gutenberg and contain curly quotes and em dashes; normalization
means typing a straight `'` or `--` still matches. The challenge is meant to test that
you sat and typed the thing, not that you can reproduce typography.

---

## 2. Non-goals

**Tamper resistance.** There isn't any, deliberately. The user has the source, the
state file, and `git`. Anyone determined to get around this can do it in about thirty
seconds. The point is to convert an unconscious reflex into a decision made on purpose,
and to make the on-purpose version cost enough that it usually isn't worth it.

**Full Disk Access.** Not required. See §1.5.

**Accessibility permission.** Not required. `NSRunningApplication.terminate()` needs no
TCC grant; this was verified. Accessibility would only be needed to *force*-quit
unresponsive applications, which Friction does not do.

`terminate()` is **asynchronous and polite**: it asks, and the app decides when (or
whether) to comply. Measured latency is ~0.5s for a cooperative app. An app with
unsaved work or a confirmation dialog can ignore it entirely, so the blocker verifies
the app actually went away and retries at 2s, 4s and 8s before giving up and logging
it. Friction never escalates to a force-kill -- consistent with not being a lock, and
it avoids destroying unsaved work.

---

## 3. Verified platform facts

Measured on the target machine (macOS 15.6, arm64, Python 3.14.6):

| Fact | Result |
|---|---|
| iMessage send via AppleScript | works; send **and** delivery confirmed |
| Messages account enumeration | `1st account whose service type = iMessage` works |
| Reading `service type` as a property | fails with `-10000`; use the `whose` form |
| Send with Messages.app quit | works — the Apple event launches it |
| `NSWorkspace` launch notification | fires instantly; `terminate()` succeeds |
| `terminate()` without Accessibility | works — no TCC grant needed |
| `rumps` + PyObjC on Python 3.14.6 | install and import cleanly |
| Native process-list read | 0.01 ms |
| `osascript` spawn overhead | 21 ms |
| Chrome tab enumeration, 10 tabs | 107 ms total (~86 ms is the Apple event) |
| Full Disk Access | absent; designed around |

### 3.1 Why apps are event-driven and browsers are polled

An Apple event is inter-process RPC handled on the **target app's main thread** — the
thread that draws its UI. Polling browsers at 1 Hz would take ~8–9% of each browser's
UI thread permanently, scale with tab count, and hold every browser out of App Nap all
day. At three browsers that is roughly a third of a core, continuously, on battery.

Apps have no such cost because the OS pushes launch notifications; subscribing is both
cheaper *and* faster than any poll, so there is no tradeoff to make. Browsers have no
equivalent tab notification, so 10 s is the chosen compromise: ~0.9% of one core with
one browser running, under 3% with three.

Using a persistent ScriptingBridge connection instead of spawning `osascript` removes
the 21 ms spawn cost but not the 86 ms Apple event. No implementation trick makes
browser polling cheap; sweep frequency is the only real lever.

### 3.2 Resolved: launchd and TCC

**Verified 2026-08-23. A launchd-started daemon does get and keep Apple Event
permission on this machine.**

The concern was that `frictiond` under launchd is a different *responsible process*
from any terminal, needs its own Automation grant, and -- having no UI session --
might be denied silently with `-1743` rather than prompting.

What actually happens: macOS shows a normal consent dialog (titled after the Python
binary, not "Friction"), the daemon **blocks** until it is answered, and once granted
the permission persists across daemon restarts. A single approval covered Chrome,
Safari and Messages together.

Two consequences for the implementation:

1. **An unanswered consent dialog blocks the calling thread indefinitely.** The probe
   initially used a 30s subprocess timeout and recorded three false failures while the
   dialog sat waiting. The daemon must never make an Apple Event call on a thread that
   matters, and must treat a timeout as "unknown", never as "denied".
2. First run after install needs a human at the keyboard to click Allow. `install.sh`
   should say so.

## 4. Layout

```
friction/
├── SPEC.md
├── README.md
├── config.example.json          # copy to config.local.json (gitignored)
├── install.sh / uninstall.sh
├── com.friction.daemon.plist.template
└── friction/
    ├── config.py                # load + validate config
    ├── state.py                 # atomic read/write of state.json
    ├── schedule.py              # PURE: (now, config, state) -> armed set
    ├── doctor.py                # permission + dependency probes
    ├── blockers/
    │   ├── apps.py              # NSWorkspace notifications
    │   └── browsers.py          # ScriptingBridge tab sweep
    ├── challenges/              # confirm / arithmetic / transcription
    ├── ui.py                    # rumps menu bar
    └── passages/                # moby_dick.txt, great_gatsby.txt
```

State lives at `~/Library/Application Support/Friction/state.json` and is not tracked.
It is written atomically (temp file + `rename`) because two processes share it and a
torn read during a sweep is a silent unblock.

`schedule.py` is a pure function with no I/O so that arm/release, pass expiry, and
manual overrides are all unit-testable without a clock or a filesystem.
