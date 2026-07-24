#!/bin/bash
# Claude Code statusline hook: tees rate_limits.{five_hour,seven_day} from the
# per-render stdin JSON into ~/.trunkline/claude_usage_live.json so the
# trunkline daemon/CLI has a source fresher than the event-driven
# ~/.claude.json cachedUsageUtilization (seen 27h stale in practice).
#
# Contract: no network calls, no token/credential access, whitelist-only
# output. Any failure falls back to printing just the model name so the
# statusline never breaks (exit 0 always).
set -u
python3 -c '
import json
import os
import sys
import time
from datetime import datetime

def epoch(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v).timestamp()
        except ValueError:
            return None
    return None

def pct(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

def main():
    model = "claude"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        print(model)
        return
    model = (payload.get("model") or {}).get("display_name") or model

    limits = payload.get("rate_limits")
    if not isinstance(limits, dict):
        print(model)
        return

    five = limits.get("five_hour") or {}
    seven = limits.get("seven_day") or {}
    record = {
        "five_hour_pct": pct(five.get("used_percentage")),
        "five_hour_resets_at": epoch(five.get("resets_at")),
        "seven_day_pct": pct(seven.get("used_percentage")),
        "seven_day_resets_at": epoch(seven.get("resets_at")),
        "at": time.time(),
    }

    try:
        live_dir = os.path.expanduser("~/.trunkline")
        os.makedirs(live_dir, exist_ok=True)
        target = os.path.join(live_dir, "claude_usage_live.json")
        tmp = os.path.join(live_dir, f".claude_usage_live.json.tmp-{os.getpid()}")
        with open(tmp, "w") as f:
            f.write(json.dumps(record))
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except OSError:
        pass  # tee 실패는 상태 표시만 폴백 — statusline 자체는 계속 동작

    parts = []
    five_pct = record["five_hour_pct"]
    seven_pct = record["seven_day_pct"]
    if five_pct is not None:
        parts.append("5h {:g}%".format(five_pct))
    if seven_pct is not None:
        parts.append("7d {:g}%".format(seven_pct))
    print(model + (" · " + " · ".join(parts) if parts else ""))

try:
    main()
except Exception:
    print("claude")
'
exit 0
