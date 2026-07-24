"""Display-only identity from auth.json bytes.

JWT payloads are base64-decoded WITHOUT signature verification — authenticity
is the CLI's job; we only label accounts in UIs (design §7.3).
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    email: str | None
    account_id: str | None
    plan: str | None


def _jwt_payload(token: str) -> dict:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        data = json.loads(base64.urlsafe_b64decode(part))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def decode_identity(auth_json: bytes) -> Identity | None:
    try:
        tokens = json.loads(auth_json).get("tokens") or {}
    except Exception:
        return None
    if not isinstance(tokens, dict) or not tokens:
        return None
    id_claims = _jwt_payload(str(tokens.get("id_token") or ""))
    access_claims = _jwt_payload(str(tokens.get("access_token") or ""))
    auth_ns = access_claims.get("https://api.openai.com/auth") or {}
    if not isinstance(auth_ns, dict):
        auth_ns = {}
    email = id_claims.get("email") or access_claims.get("email")
    account_id = tokens.get("account_id") or auth_ns.get("chatgpt_account_id")
    plan = auth_ns.get("chatgpt_plan_type")
    if not (email or account_id):
        return None
    return Identity(
        email=str(email) if email else None,
        account_id=str(account_id) if account_id else None,
        plan=str(plan) if plan else None,
    )
