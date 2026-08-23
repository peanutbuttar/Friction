"""Friction CLI entry point."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="friction", description="Distraction blocker")
    sub = parser.add_subparsers(dest="command", required=True)

    doc = sub.add_parser("doctor", help="check permissions and dependencies")
    doc.add_argument("--deep", action="store_true",
                     help="launch browsers if needed to verify Automation access")

    stat = sub.add_parser("status", help="show what is blocked right now")
    stat.add_argument("--at", metavar="HH:MM", help="pretend it is this time")

    dae = sub.add_parser("daemon", help="run the enforcement daemon (foreground)")
    dae.add_argument("--dry-run", action="store_true",
                     help="log what would be blocked without closing anything")
    dae.add_argument("-v", "--verbose", action="store_true")
    sub.add_parser("ui", help="run the menu bar UI")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        from friction import doctor
        return doctor.run(deep=args.deep)

    if args.command == "status":
        from datetime import datetime
        from friction import status
        when = None
        if args.at:
            hh, mm = args.at.split(":")
            when = datetime.now().replace(hour=int(hh), minute=int(mm), second=0)
        return status.run(when)

    if args.command == "daemon":
        from friction import daemon
        return daemon.run(dry_run=args.dry_run, verbose=args.verbose)

    if args.command == "ui":
        from friction import ui
        return ui.run()

    print(f"'{args.command}' is not implemented yet.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
