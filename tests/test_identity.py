import base64
import json

from trunkline.identity import Identity, decode_identity


def _jwt(payload: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.x"


def _auth_bytes(id_claims: dict | None = None, access_claims: dict | None = None,
                account_id: str | None = None) -> bytes:
    tokens: dict = {}
    if id_claims is not None:
        tokens["id_token"] = _jwt(id_claims)
    if access_claims is not None:
        tokens["access_token"] = _jwt(access_claims)
    if account_id:
        tokens["account_id"] = account_id
    return json.dumps({"tokens": tokens}).encode()


def test_email_from_id_token():
    raw = _auth_bytes(id_claims={"email": "a@b.c"})
    ident = decode_identity(raw)
    assert ident == Identity(email="a@b.c", account_id=None, plan=None)


def test_account_id_direct_field_wins():
    raw = _auth_bytes(id_claims={"email": "a@b.c"}, account_id="acct-1")
    assert decode_identity(raw).account_id == "acct-1"


def test_account_id_from_access_token_claims():
    claims = {"https://api.openai.com/auth": {"chatgpt_account_id": "acct-2",
                                             "chatgpt_plan_type": "pro"}}
    ident = decode_identity(_auth_bytes(access_claims=claims))
    assert ident.account_id == "acct-2"
    assert ident.plan == "pro"


def test_garbage_returns_none():
    assert decode_identity(b"not json") is None
    assert decode_identity(b"{}") is None
