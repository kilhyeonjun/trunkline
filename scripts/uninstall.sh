#!/bin/bash
set -euo pipefail

remove_data=0
case "${1:-}" in
  "") ;;
  --remove-data) remove_data=1 ;;
  *)
    echo "usage: $0 [--remove-data]" >&2
    exit 2
    ;;
esac
if [ "$#" -gt 1 ]; then
  echo "usage: $0 [--remove-data]" >&2
  exit 2
fi

APP_DIR="${TRUNKLINE_APP_DIR:-$HOME/Applications}"
APP_TARGET="$APP_DIR/Trunkline.app"
PLIST="$HOME/Library/LaunchAgents/io.github.kilhyeonjun.trunkline.plist"
LABEL="io.github.kilhyeonjun.trunkline"

if [ "${TRUNKLINE_TEST_MODE:-0}" != "1" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
fi
rm -f "$PLIST"
rm -rf "$APP_TARGET"

if [ "$remove_data" -eq 1 ]; then
  rm -rf "$HOME/.trunkline"
fi

echo "uninstalled Trunkline; data $([ "$remove_data" -eq 1 ] && echo removed || echo preserved)"
