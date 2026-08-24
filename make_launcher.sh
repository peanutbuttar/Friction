#!/usr/bin/env bash
# Builds a tiny Friction.app whose only job is to reopen the menu bar panel.
# It is a launcher, not the program -- the real UI runs under launchd.
# Existing as an .app is what makes it findable in Spotlight and the Dock.
set -euo pipefail

APP="$HOME/Applications/Friction.app"
mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Friction</string>
    <key>CFBundleDisplayName</key><string>Friction</string>
    <key>CFBundleIdentifier</key><string>com.friction.launcher</string>
    <key>CFBundleVersion</key><string>1.0</string>
    <key>CFBundleExecutable</key><string>Friction</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <!-- No Dock icon or menu bar of its own: it starts the panel and exits. -->
    <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/Friction" <<'LAUNCH'
#!/usr/bin/env bash
# Ask launchd to start the menu bar UI. If it's already running this is a no-op,
# which is the behaviour you want from something people will double-click twice.
launchctl start com.friction.ui 2>/dev/null || true
LAUNCH

chmod +x "$APP/Contents/MacOS/Friction"
touch "$APP"                      # nudge Launch Services to re-read the bundle
echo "    built $APP"
