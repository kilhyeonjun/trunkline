#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
log_file="$(mktemp)"
trap 'rm -f "$log_file"' EXIT
swift package clean
swift build -c release 2>&1 | tee "$log_file"
if grep -E "capture of 'self' with non-Sendable type 'AppDelegate|task or actor isolated value cannot be sent" "$log_file"; then
  echo "AppDelegate concurrency warning remains" >&2
  exit 1
fi
