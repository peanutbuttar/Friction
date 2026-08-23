#!/usr/bin/env bash
# Sets up the virtualenv, writes the LaunchAgent plist, and loads it.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.friction.daemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
VENV="$REPO/venv"

echo "==> Virtualenv"
if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$REPO/requirements.txt"
echo "    $("$VENV/bin/python" -V)"

echo "==> Config"
if [[ ! -f "$REPO/config.local.json" ]]; then
  cp "$REPO/config.example.json" "$REPO/config.local.json"
  echo "    created config.local.json — you must fill in your blocklists and contacts"
else
  echo "    config.local.json already exists, leaving it alone"
fi

echo "==> LaunchAgent"
mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|__PYTHON__|$VENV/bin/python|g" \
    -e "s|__REPO__|$REPO|g" \
    "$REPO/com.friction.daemon.plist.template" > "$PLIST"
echo "    wrote $PLIST"

# Enforcement is only switched on once there is a way to UNLOCK it. The daemon
# works, but without the menu bar UI and its challenges there is no escape hatch:
# blocked things would stay blocked until the tier's release time. So the gate is
# friction/ui.py, not friction/daemon.py.
if [[ -f "$REPO/friction/ui.py" ]]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
  echo "    loaded"
else
  echo "    NOT loaded — no unlock UI yet, so enforcement stays off."
  echo "    Try it by hand instead (Ctrl-C to stop):"
  echo "      ./venv/bin/python -m friction daemon --dry-run"
fi

echo
echo "==> Checking your environment"
"$VENV/bin/python" -m friction doctor || true

cat <<'MSG'
Next:
  1. Edit config.local.json — blocklists, and your accountability contacts.
  2. Grant Automation access when macOS asks (or fix whatever doctor flagged).
  3. Re-run: ./venv/bin/python -m friction doctor
MSG
