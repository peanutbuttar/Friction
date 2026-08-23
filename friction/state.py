"""Shared state, read and written by both the daemon and the menu bar UI.

Two processes touch this file, so every write goes to a temp file and is then
renamed over the target. rename() is atomic on macOS, so a reader either sees the
whole old file or the whole new one -- never a half-written one. A torn read here
would look like "nothing is armed", which is a silent unblock: the worst possible
failure for this project.

Read-modify-write cycles additionally take an exclusive lock, so two processes
toggling at the same moment cannot clobber each other.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

STATE_DIR = Path.home() / "Library" / "Application Support" / "Friction"
STATE_PATH = STATE_DIR / "state.json"
LOCK_PATH = STATE_DIR / "state.lock"

SCHEMA_VERSION = 1

DEFAULT_STATE: dict[str, Any] = {
    "version": SCHEMA_VERSION,
    # ISO timestamp until which the master toggle is off; None means armed.
    "master_disarmed_until": None,
    # key -> ISO timestamp the manual arm began. Key is a tier ("tier1") for
    # tier-granularity tiers, or "tier:target" for item-granularity ones.
    "manual_arms": {},
    # key -> ISO timestamp a passed challenge expires at.
    "passes": {},
    # Which transcription passage comes next.
    "next_passage": None,
}


def _default() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_STATE))


def load(path: Path | None = None) -> dict[str, Any]:
    """Read state, falling back to defaults if missing or unreadable.

    A corrupt state file must not stop enforcement, so this never raises -- it
    fails closed, to defaults, which means "everything armed as scheduled".
    """
    path = path or STATE_PATH
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _default()

    if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
        return _default()

    merged = _default()
    merged.update(data)
    return merged


def save(state: dict[str, Any], path: Path | None = None) -> None:
    """Write state atomically: temp file in the same directory, then rename."""
    path = path or STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(state, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())          # survive a crash between write and rename
        os.replace(tmp, path)              # atomic on macOS
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def _lock(path: Path | None = None) -> Iterator[None]:
    path = path or LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def update(fn: Callable[[dict[str, Any]], None],
           path: Path | None = None) -> dict[str, Any]:
    """Apply fn to the current state and persist it, holding an exclusive lock.

    Use this for anything that reads-then-writes; plain save() can lose a
    concurrent change made between the read and the write.
    """
    path = path or STATE_PATH
    lock = path.parent / "state.lock"
    with _lock(lock):
        state = load(path)
        fn(state)
        save(state, path)
        return state


# --- helpers for the timestamps stored above -------------------------------

def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
