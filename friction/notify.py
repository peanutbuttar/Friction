"""Sending the accountability text.

The message and handle are passed as AppleScript arguments rather than pasted
into the script source. Interpolating them would break on any message containing
a quote, and would let config content alter the script.

A successful return means Messages ACCEPTED the message, not that it was
delivered. Verifying delivery needs Full Disk Access to read chat.db, which
Friction deliberately does not require -- so confirmation is manual. See
SPEC.md 1.5.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

SEND_SCRIPT = [
    "-e", "on run {msg, handle}",
    "-e", 'tell application "Messages"',
    "-e", "set svc to 1st account whose service type = iMessage",
    "-e", "send msg to participant handle of svc",
    "-e", "end tell",
    "-e", "end run",
]

# Generous: an unanswered TCC dialog blocks indefinitely (SPEC.md 3.2), and a
# timeout here means "unknown", never "failed".
TIMEOUT = 120


@dataclass
class SendResult:
    handle: str
    name: str
    accepted: bool
    error: str = ""


def send_imessage(handle: str, message: str) -> SendResult:
    try:
        p = subprocess.run(["osascript", *SEND_SCRIPT, message, handle],
                           capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return SendResult(handle, "", False, "timed out (permission dialog?)")
    if p.returncode == 0:
        return SendResult(handle, "", True)
    return SendResult(handle, "", False, (p.stderr or p.stdout).strip())


def notify_contacts(contacts: list, message: str) -> list[SendResult]:
    """Text everyone. Contacts may be plain strings or {name, handle} dicts."""
    results = []
    for c in contacts:
        handle = c.get("handle") if isinstance(c, dict) else c
        name = (c.get("name") if isinstance(c, dict) else "") or handle
        if not handle:
            continue
        r = send_imessage(handle, message)
        r.name = name
        log.info("notify %s (%s): %s", name, handle,
                 "accepted" if r.accepted else f"FAILED {r.error}")
        results.append(r)
    return results
