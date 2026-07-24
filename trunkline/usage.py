"""Pure usage reader. Sends the stored access_token AS-IS; if expired, returns
stale WITHOUT any network call. This module must never gain token-rotation
capability (design principle 0 — enforced by test_no_refresh_symbols_in_module)."""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


@dataclass(frozen=True)
class UsageRow:
    label: str
    ok: bool
    stale: bool
    primary_used: float | None
    primary_reset: int | None
    secondary_used: float | None
    secondary_reset: int | None
    error: str | None
    primary_window_minutes: int | None = None
    secondary_window_minutes: int | None = None
    plan: str | None = None


def _err(label: str, error: str, *, stale: bool = False) -> UsageRow:
    return UsageRow(label=label, ok=False, stale=stale, primary_used=None,
                    primary_reset=None, secondary_used=None,
                    secondary_reset=None, error=error)


def _token_exp(token: str) -> float | None:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return float(json.loads(base64.urlsafe_b64decode(part)).get("exp"))
    except Exception:
        return None


def read_usage(label: str, secret_path: Path, timeout: int = 15,
               _urlopen=urllib.request.urlopen) -> UsageRow:
    if not secret_path.exists():
        return _err(label, "login required")
    try:
        tokens = json.loads(secret_path.read_bytes()).get("tokens") or {}
    except Exception:
        return _err(label, "unreadable auth")
    access = str(tokens.get("access_token") or "")
    if not access:
        return _err(label, "no access token")
    exp = _token_exp(access)
    # Unparseable exp fails OPEN by design: this module's security property is
    # the absence of token-rotation capability, not network avoidance. A stale
    # or garbage token just earns an HTTP 401, which returns an error row.
    if exp is not None and exp <= time.time():
        return _err(label, "access token expired (refresh on next CLI use)", stale=True)
    headers = {"Authorization": f"Bearer {access}", "Accept": "application/json"}
    account_id = tokens.get("account_id")
    if account_id:
        headers["ChatGPT-Account-Id"] = str(account_id)
    request = urllib.request.Request(USAGE_URL, headers=headers)
    try:
        with _urlopen(request, timeout=timeout) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return _err(label, f"usage HTTP {exc.code}")
    except Exception as exc:
        return _err(label, f"{type(exc).__name__}: {exc}")
    try:
        rate = payload.get("rate_limit") or {}
        primary = rate.get("primary_window") or {}
        secondary = rate.get("secondary_window") or {}
        primary_window_s = primary.get("limit_window_seconds")
        secondary_window_s = secondary.get("limit_window_seconds")
        return UsageRow(
            label=label, ok=True, stale=False,
            primary_used=float(primary["used_percent"]) if "used_percent" in primary else None,
            primary_reset=primary.get("reset_at"),
            secondary_used=float(secondary["used_percent"]) if "used_percent" in secondary else None,
            secondary_reset=secondary.get("reset_at"),
            error=None,
            primary_window_minutes=primary_window_s // 60 if primary_window_s is not None else None,
            secondary_window_minutes=secondary_window_s // 60 if secondary_window_s is not None else None,
        )
    except (TypeError, ValueError, KeyError) as exc:
        return _err(label, f"malformed usage payload: {type(exc).__name__}")
