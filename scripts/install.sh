#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLI="${TRUNKLINE_CLI:-$(command -v trunkline || true)}"
if [ -z "$CLI" ] || [ ! -x "$CLI" ]; then
  echo "Trunkline CLI not found. Install it with: pipx install trunkline" >&2
  exit 1
fi
CLI="$(cd "$(dirname "$CLI")" && pwd)/$(basename "$CLI")"

APP_DIR="${TRUNKLINE_APP_DIR:-$HOME/Applications}"
APP_TARGET="$APP_DIR/Trunkline.app"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PLIST="$LAUNCH_AGENTS/io.github.kilhyeonjun.trunkline.plist"
STATE_DIR="$HOME/.trunkline"
LABEL="io.github.kilhyeonjun.trunkline"

mkdir -p "$APP_DIR" "$LAUNCH_AGENTS" "$STATE_DIR"

cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$CLI</string>
    <string>daemon</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardErrorPath</key>
  <string>$STATE_DIR/daemon.err.log</string>
  <key>StandardOutPath</key>
  <string>/dev/null</string>
</dict>
</plist>
EOF
plutil -lint "$PLIST" >/dev/null

if [ "${TRUNKLINE_TEST_MODE:-0}" != "1" ]; then
  bash "$ROOT_DIR/menubar/Scripts/package_app.sh"
  rm -rf "$APP_TARGET"
  ditto "$ROOT_DIR/menubar/.build/Trunkline.app" "$APP_TARGET"
  uid="$(id -u)"
  launchctl bootout "gui/$uid/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$uid" "$PLIST"
  open "$APP_TARGET"
fi

echo "installed Trunkline app and daemon configuration"
