"""Permission and dependency probes.

Exists because the failure mode this project is most likely to hit -- a launchd
daemon being silently denied Apple Event permission -- produces no visible error
anywhere. See SPEC.md 3.2.
"""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Apple Event / AppleScript error codes we care about telling apart.
ERR_NOT_AUTHORIZED = -1743   # TCC denied. The one that matters.
ERR_APP_NOT_RUNNING = -600
ERR_NO_SUCH_APP = -1728

STATE_DIR = Path.home() / "Library" / "Application Support" / "Friction"
CONFIG_LOCAL = Path(__file__).resolve().parent.parent / "config.local.json"

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"

_MARK = {OK: "\033[32m✓\033[0m", WARN: "\033[33m!\033[0m",
         FAIL: "\033[31m✗\033[0m", INFO: "\033[2m·\033[0m"}

BROWSERS = [("Safari", "com.apple.Safari"),
            ("Google Chrome", "com.google.Chrome"),
            ("Arc", "company.thebrowser.Browser")]


@dataclass
class Check:
    status: str
    name: str
    detail: str = ""
    fix: str = ""


def _osascript(script: str, timeout: int = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, "timed out"


def _err_code(msg: str) -> int | None:
    """Pull the (-NNNN) code out of an osascript error string."""
    if "(-" not in msg:
        return None
    try:
        return int(msg.rsplit("(", 1)[1].rstrip(")"))
    except (ValueError, IndexError):
        return None


def _app_installed(bundle_id: str) -> bool:
    p = subprocess.run(["mdfind", f"kMDItemCFBundleIdentifier == '{bundle_id}'"],
                       capture_output=True, text=True)
    return bool(p.stdout.strip())


def _app_running(name: str) -> bool:
    return subprocess.run(["pgrep", "-x", name], capture_output=True).returncode == 0


def check_python() -> Check:
    v = sys.version_info
    if v < (3, 11):
        return Check(FAIL, "Python 3.11+", f"found {v.major}.{v.minor}.{v.micro}",
                     "Install a newer Python and re-run ./install.sh")
    return Check(OK, "Python 3.11+", f"{v.major}.{v.minor}.{v.micro}")


def check_imports() -> list[Check]:
    out = []
    for mod, why in [("rumps", "menu bar UI"),
                     ("AppKit", "app-launch notifications"),
                     ("ScriptingBridge", "browser tab sweep")]:
        try:
            __import__(mod)
            out.append(Check(OK, f"import {mod}", why))
        except ImportError as e:
            out.append(Check(FAIL, f"import {mod}", str(e),
                             "./venv/bin/pip install -r requirements.txt"))
    return out


def check_config() -> list[Check]:
    if not CONFIG_LOCAL.exists():
        return [Check(FAIL, "config.local.json", "missing",
                      "cp config.example.json config.local.json  # then fill it in")]
    try:
        cfg = json.loads(CONFIG_LOCAL.read_text())
    except json.JSONDecodeError as e:
        return [Check(FAIL, "config.local.json", f"invalid JSON: {e}",
                      "Fix the syntax error above")]

    out = [Check(OK, "config.local.json", "present and valid")]

    # The one that would actually hurt: real phone numbers in a tracked file.
    tracked = subprocess.run(["git", "check-ignore", "-q", str(CONFIG_LOCAL)],
                             capture_output=True, cwd=CONFIG_LOCAL.parent)
    if tracked.returncode != 0:
        out.append(Check(FAIL, "config.local.json is gitignored", "IT IS NOT",
                         "Add config.local.json to .gitignore before committing anything"))
    else:
        out.append(Check(OK, "config.local.json is gitignored", "yes"))

    contacts = cfg.get("master_toggle", {}).get("notify", {}).get("contacts", [])
    if not contacts:
        out.append(Check(WARN, "accountability contacts", "none configured",
                         "The master toggle has no teeth until you add contacts"))
    else:
        out.append(Check(OK, "accountability contacts", f"{len(contacts)} configured"))
    return out


def check_state_dir() -> Check:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        probe = STATE_DIR / ".write-probe"
        probe.write_text("ok")
        probe.unlink()
        return Check(OK, "state directory", str(STATE_DIR))
    except OSError as e:
        return Check(FAIL, "state directory", str(e), f"Check permissions on {STATE_DIR}")


def check_messages() -> list[Check]:
    rc, out = _osascript('tell application "Messages" to count of accounts')
    if rc != 0:
        code = _err_code(out)
        if code == ERR_NOT_AUTHORIZED:
            return [Check(FAIL, "Automation → Messages", "not authorized",
                          "System Settings → Privacy & Security → Automation → "
                          "enable Messages for this process")]
        return [Check(FAIL, "Automation → Messages", out, "")]

    checks = [Check(OK, "Automation → Messages", f"{out} accounts visible")]

    rc, out = _osascript(
        'tell application "Messages" to get connection status of '
        '(1st account whose service type = iMessage) as text')
    if rc == 0 and "connected" in out.lower():
        checks.append(Check(OK, "iMessage account", "connected"))
    else:
        checks.append(Check(FAIL, "iMessage account", out or "not connected",
                            "Open Messages and sign in to iMessage"))
    return checks


def check_browsers(deep: bool = False) -> list[Check]:
    out = []
    for name, bundle_id in BROWSERS:
        if not _app_installed(bundle_id):
            out.append(Check(INFO, f"Automation → {name}", "not installed, skipping"))
            continue
        if not _app_running(name) and not deep:
            out.append(Check(WARN, f"Automation → {name}", "installed but not running",
                             f"Cannot verify without launching it. Run with --deep, "
                             f"or just open {name} and re-run."))
            continue
        rc, res = _osascript(f'tell application "{name}" to count of windows')
        if rc == 0:
            out.append(Check(OK, f"Automation → {name}", f"{res} windows visible"))
        else:
            code = _err_code(res)
            fix = ("System Settings → Privacy & Security → Automation → "
                   f"enable {name} for this process") if code == ERR_NOT_AUTHORIZED else ""
            out.append(Check(FAIL, f"Automation → {name}",
                             "not authorized" if code == ERR_NOT_AUTHORIZED else res, fix))
    return out


def check_workspace_notifications() -> Check:
    try:
        from AppKit import NSWorkspace
        nc = NSWorkspace.sharedWorkspace().notificationCenter()
        if nc is None:
            return Check(FAIL, "app-launch notifications", "no notification center")
        return Check(OK, "app-launch notifications", "available (no TCC grant needed)")
    except Exception as e:  # noqa: BLE001 - doctor must never crash
        return Check(FAIL, "app-launch notifications", str(e))


def check_launchd() -> list[Check]:
    plist = Path.home() / "Library" / "LaunchAgents" / "com.friction.daemon.plist"
    if not plist.exists():
        return [Check(INFO, "LaunchAgent", "not installed yet",
                      "./install.sh writes and loads it")]
    checks = [Check(OK, "LaunchAgent", str(plist))]
    p = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    if "com.friction.daemon" in p.stdout:
        checks.append(Check(OK, "daemon loaded", "launchd knows about it"))
    else:
        checks.append(Check(WARN, "daemon loaded", "not currently loaded",
                            f"launchctl load {plist}"))
    return checks


def check_full_disk_access() -> Check:
    """Informational only. Friction is designed not to need this."""
    try:
        (Path.home() / "Library" / "Messages").iterdir()
        return Check(INFO, "Full Disk Access", "granted (not required by Friction)")
    except PermissionError:
        return Check(INFO, "Full Disk Access", "absent — fine, not required")
    except OSError:
        return Check(INFO, "Full Disk Access", "absent — fine, not required")


def run(deep: bool = False) -> int:
    print("\n\033[1mFriction — environment check\033[0m\n")

    groups: list[tuple[str, list[Check]]] = [
        ("Runtime", [check_python(), *check_imports()]),
        ("Configuration", [*check_config(), check_state_dir()]),
        ("Blocking apps", [check_workspace_notifications()]),
        ("Blocking websites", check_browsers(deep=deep)),
        ("Master toggle", check_messages()),
        ("Daemon", check_launchd()),
        ("Informational", [check_full_disk_access()]),
    ]

    failures, warnings = [], []
    for title, checks in groups:
        print(f"\033[1m{title}\033[0m")
        for c in checks:
            detail = f"  \033[2m{c.detail}\033[0m" if c.detail else ""
            print(f"  {_MARK[c.status]} {c.name}{detail}")
            if c.status == FAIL:
                failures.append(c)
            elif c.status == WARN:
                warnings.append(c)
        print()

    if failures or warnings:
        print("\033[1mWhat to do\033[0m")
        for c in failures + warnings:
            if c.fix:
                print(f"  {_MARK[c.status]} {c.name}:\n      {c.fix}")
        print()

    if failures:
        print(f"\033[31m{len(failures)} problem(s) will stop Friction working.\033[0m\n")
        return 1
    if warnings:
        print(f"\033[33m{len(warnings)} warning(s). Friction will run.\033[0m\n")
        return 0
    print("\033[32mAll good.\033[0m\n")
    return 0
