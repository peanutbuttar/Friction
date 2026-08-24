"""Throwaway probe: does a launchd-started process get Apple Event permission?

Run by launchd (NOT from a terminal) so that the "responsible process" is the
daemon itself rather than whatever shell launched it. Writes a report and exits.
See SPEC.md 3.2 for why this is the project's biggest unknown.
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
from pathlib import Path

REPORT = Path.home() / "Library" / "Application Support" / "Friction" / "tccprobe.txt"
ERR_NOT_AUTHORIZED = -1743


def err_code(msg: str) -> int | None:
    """Extract the numeric AppleScript error code from an error string."""
    if "(-" not in msg:
        return None
    try:
        return int(msg.rsplit("(", 1)[1].rstrip(")"))
    except (ValueError, IndexError):
        return None


def probe(app: str, script: str) -> tuple[str, str]:
    """Try one Apple Event, classifying the result as ALLOWED, DENIED, or ERROR."""
    p = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=180)
    out = (p.stdout or p.stderr).strip()
    if p.returncode == 0:
        return "ALLOWED", out
    code = err_code(out)
    if code == ERR_NOT_AUTHORIZED:
        return "DENIED", f"-1743 not authorized — {out}"
    return "ERROR", out


def main() -> int:
    """Run every probe and write the report. Returns a shell exit code."""
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Friction TCC probe",
        f"when:  {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"pid:   {os.getpid()}   ppid: {os.getppid()}",
        f"python:{sys.executable}",
        # ppid 1 means launchd started us directly - the case we care about.
        f"launched by launchd: {'YES' if os.getppid() == 1 else 'NO (ppid is not 1)'}",
        "",
    ]

    targets = [
        ("Google Chrome", 'tell application "Google Chrome" to count of windows'),
        ("Safari",        'tell application "Safari" to count of windows'),
        ("Messages",      'tell application "Messages" to count of accounts'),
    ]
    for name, script in targets:
        try:
            status, detail = probe(name, script)
        except Exception as e:  # noqa: BLE001 - probe must always report
            status, detail = "ERROR", repr(e)
        lines.append(f"{name:15} {status:8} {detail}")

    try:
        from AppKit import NSWorkspace
        nc = NSWorkspace.sharedWorkspace().notificationCenter()
        lines.append(f"{'NSWorkspace':15} {'OK' if nc else 'FAIL':8} launch notifications")
    except Exception as e:  # noqa: BLE001
        lines.append(f"{'NSWorkspace':15} {'ERROR':8} {e!r}")

    REPORT.write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
