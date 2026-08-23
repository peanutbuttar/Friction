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

    sub.add_parser("daemon", help="run the enforcement daemon (foreground)")
    sub.add_parser("ui", help="run the menu bar UI")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        from friction import doctor
        return doctor.run(deep=args.deep)

    print(f"'{args.command}' is not implemented yet — Phase 0 only.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
