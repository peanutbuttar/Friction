#!/usr/bin/env bash
# Unloads the LaunchAgent and removes the state directory. Config is left alone.
set -euo pipefail

LABEL="com.friction.daemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UI_PLIST="$HOME/Library/LaunchAgents/com.friction.ui.plist"
STATE="$HOME/Library/Application Support/Friction"
LAUNCHER="$HOME/Applications/Friction.app"

echo "==> LaunchAgent"
if [[ -f "$PLIST" ]]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "    unloaded and removed $PLIST"
else
  echo "    not installed, nothing to do"
fi

if [[ -f "$UI_PLIST" ]]; then
  launchctl unload "$UI_PLIST" 2>/dev/null || true
  rm -f "$UI_PLIST"
  echo "    unloaded and removed the menu bar UI agent"
fi

echo "==> Launcher"
if [[ -d "$LAUNCHER" ]]; then
  rm -rf "$LAUNCHER"
  echo "    removed $LAUNCHER"
else
  echo "    no launcher app"
fi

echo "==> State"
if [[ -d "$STATE" ]]; then
  rm -rf "$STATE"
  echo "    removed $STATE"
else
  echo "    no state directory"
fi

echo
echo "Left alone: config.local.json, venv/, and the repo itself."
echo "Automation permissions must be revoked by hand in System Settings if you want them gone."
