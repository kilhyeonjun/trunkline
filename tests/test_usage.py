import base64
import io
import json
import time
import urllib.error
from pathlib import Path

from trunkline.usage import UsageRow, read_usage


def _jwt(exp: float) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"{header}.{body}.x"


def _secret(tmp_path: Path, exp_offset: float) -> Path:
    p = tmp_path / "auth.json"
    p.write_bytes(json.dumps(
        {"tokens": {"access_token": _jwt(time.time() + exp_offset),
                    "account_id": "acct-1"}}).encode())
    return p


class _Resp:
    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode()
    def read(self): return self._data
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_expired_token_returns_stale_without_network(tmp_path):
    p = _secret(tmp_path, exp_offset=-3600)
    def boom(*a, **k):
        raise AssertionError("network call attempted with expired token")
    row = read_usage("personal", p, _urlopen=boom)
    assert row.stale is True and row.ok is False


def test_valid_token_fetches_usage(tmp_path):
    p = _secret(tmp_path, exp_offset=3600)
    payload = {"rate_limit": {
        "primary_window": {"used_percent": 12.0, "reset_at": 1785060000,
                            "limit_window_seconds": 604800},
        "secondary_window": {"used_percent": 4.0, "reset_at": 1785048935}}}
    captured = {}
    def fake(req, timeout):
        captured["auth"] = req.headers.get("Authorization")
        return _Resp(payload)
    row = read_usage("personal", p, _urlopen=fake)
    assert row.ok and row.primary_used == 12.0 and row.secondary_used == 4.0
    assert captured["auth"].startswith("Bearer ")
    assert row.primary_window_minutes == 604800 // 60
    assert row.secondary_window_minutes is None


def test_http_error_reported_not_fatal(tmp_path):
    p = _secret(tmp_path, exp_offset=3600)
    def fail(req, timeout):
        raise urllib.error.HTTPError("u", 401, "x", {}, io.BytesIO(b"{}"))
    row = read_usage("personal", p, _urlopen=fail)
    assert row.ok is False and "401" in row.error


def test_missing_file(tmp_path):
    row = read_usage("gone", tmp_path / "none.json")
    assert row.ok is False and row.error == "login required"


def test_malformed_payload_returns_error_row(tmp_path):
    p = _secret(tmp_path, exp_offset=3600)
    payload = {"rate_limit": {"primary_window": {"used_percent": "abc", "reset_at": 1}}}
    row = read_usage("personal", p, _urlopen=lambda req, timeout: _Resp(payload))
    assert row.ok is False and "malformed" in row.error


def test_legacy_payload_without_window_falls_back_to_none(tmp_path):
    """구형 wham 응답(limit_window_seconds 없음) → window_minutes는 None 폴백."""
    p = _secret(tmp_path, exp_offset=3600)
    payload = {"rate_limit": {
        "primary_window": {"used_percent": 12.0, "reset_at": 1785060000},
        "secondary_window": {"used_percent": 4.0, "reset_at": 1785048935}}}
    row = read_usage("personal", p, _urlopen=lambda req, timeout: _Resp(payload))
    assert row.ok is True
    assert row.primary_window_minutes is None
    assert row.secondary_window_minutes is None


def test_unparseable_exp_fails_open_to_network(tmp_path):
    """exp 파싱 불가 → fail-open (네트워크 진행, 401은 error row로 처리) — 설계 결정."""
    p = tmp_path / "auth.json"
    p.write_bytes(json.dumps({"tokens": {"access_token": "garbage-token"}}).encode())
    payload = {"rate_limit": {"primary_window": {"used_percent": 1.0, "reset_at": 1}}}
    row = read_usage("personal", p, _urlopen=lambda req, timeout: _Resp(payload))
    assert row.ok is True   # network was attempted, response parsed


def test_no_refresh_symbols_in_module():
    """원칙 0 자동 게이트: refresh 도달 경로가 소스에 존재하지 않는다."""
    src = Path("trunkline/usage.py").read_text()
    assert "refresh_token" not in src
    assert "oauth/token" not in src


def test_usage_row_plan_defaults_to_none():
    """plan은 read_usage(wham 응답)에서 유래하지 않음 — 기본값 None (identity 별도 결선, T6b)."""
    row = UsageRow(label="personal", ok=True, stale=False, primary_used=1.0,
                   primary_reset=None, secondary_used=None, secondary_reset=None, error=None)
    assert row.plan is None
