import json
from pathlib import Path

from trunkline.claude_status import (age_text, login_warning,
                                       read_claude_status)

from conftest import _cfg, _creds

NOW = 1_784_600_000.0


def test_reads_status_zero_pct_is_valid(tmp_path):
    st = read_claude_status(_cfg(tmp_path), _creds(tmp_path))
    assert st.ok and st.email == "h@x.net" and st.tier == "max_20x"
    assert st.five_hour_pct == 0.0            # 0% ≠ None (truthiness 함정)
    assert st.seven_day_pct == 12.0
    assert abs(st.five_hour_resets_at - 1784584800.304197) < 1.0  # ISO 마이크로초 변환
    assert st.fetched_at == 1_784_511_168.429
    assert st.login_expires_at == 1_785_300_106.975
    assert "SECRET" not in json.dumps(st.__dict__)   # 토큰 값 비유출


def test_utilization_null_gives_none_not_crash(tmp_path):
    st = read_claude_status(_cfg(tmp_path, five=None, seven=None), _creds(tmp_path))
    assert st.ok and st.five_hour_pct is None and st.seven_day_pct is None


def test_missing_files_enum_errors(tmp_path):
    st = read_claude_status(tmp_path / "no.json", _creds(tmp_path))
    assert (not st.ok) and st.error == "config_missing"


def test_missing_credentials_still_reports_usage(tmp_path):
    """자격 파일은 만료 경고용 부가 입력 — macOS는 Keychain에 보관해 파일이 없다.
    부재가 usage 보고를 막으면 안 된다 (Keychain 읽기는 §1.1 grep 게이트로 금지)."""
    st = read_claude_status(_cfg(tmp_path), tmp_path / "no2.json")
    assert st.ok and st.error is None
    assert st.email == "h@x.net" and st.five_hour_pct == 0.0 and st.seven_day_pct == 12.0
    assert st.login_expires_at is None
    assert login_warning(st, NOW) is None     # 만료 미상 → 늑대소년 금지


def test_corrupt_credentials_still_reports_usage(tmp_path):
    p = tmp_path / "creds-bad.json"; p.write_text("not json")
    st = read_claude_status(_cfg(tmp_path), p)
    assert st.ok and st.error is None and st.login_expires_at is None


def test_non_dict_credentials_still_reports_usage(tmp_path):
    p = tmp_path / "creds-list.json"; p.write_text("[1, 2]")
    st = read_claude_status(_cfg(tmp_path), p)
    assert st.ok and st.error is None and st.login_expires_at is None


def test_cache_key_missing(tmp_path):
    p = tmp_path / "c.json"; p.write_text("{}")
    st = read_claude_status(p, _creds(tmp_path))
    assert (not st.ok) and st.error == "cache_missing"


def test_parse_error_enum(tmp_path):
    p = tmp_path / "c.json"; p.write_text("not json")
    st = read_claude_status(p, _creds(tmp_path))
    assert (not st.ok) and st.error == "parse_error"


def test_login_warning_boundaries(tmp_path):
    ok = read_claude_status(_cfg(tmp_path), _creds(tmp_path, refresh_exp_ms=int((NOW + 10 * 86400) * 1000)))
    assert login_warning(ok, NOW) is None
    d3 = read_claude_status(_cfg(tmp_path), _creds(tmp_path, refresh_exp_ms=int((NOW + 3.5 * 86400) * 1000)))
    assert login_warning(d3, NOW) == "만료 임박 D-3"
    dead = read_claude_status(_cfg(tmp_path), _creds(tmp_path, refresh_exp_ms=int((NOW - 60) * 1000)))
    assert login_warning(dead, NOW) == "재로그인 필요: claude auth login"
    unknown = read_claude_status(_cfg(tmp_path), _creds(tmp_path, refresh_exp_ms=None))
    assert login_warning(unknown, NOW) is None


def test_age_text_units():
    assert age_text(NOW, NOW - 480) == "8분 전"
    assert age_text(NOW, NOW - 3600 * 23.5) == "23시간 전"
    assert age_text(NOW, NOW - 86400 * 2.2) == "2일 전"
    assert age_text(NOW, None) is None


def test_no_egress_or_token_symbols():
    src = (Path(__file__).parent.parent / "trunkline" / "claude_status.py").read_text()
    for banned in ("urllib", "urlopen", "http.client", "socket", "subprocess",
                   "os.system", "security ", "oauth/token", "accessToken", "mcpOAuth"):
        assert banned not in src, banned


def test_statusline_script_no_egress():
    src = (Path(__file__).parent.parent / "scripts" / "claude-statusline.sh").read_text()
    for banned in ("urllib", "urlopen", "http.client", "socket", "subprocess",
                   "os.system", "accessToken", "refreshToken", "credentials"):
        assert banned not in src, banned


def test_statusline_script_end_to_end(tmp_path, monkeypatch):
    import subprocess as sp
    script = Path(__file__).parent.parent / "scripts" / "claude-statusline.sh"
    home = tmp_path / "home"
    home.mkdir()
    env = dict(**{"HOME": str(home)})
    payload = json.dumps({
        "model": {"display_name": "Sonnet 5"},
        "rate_limits": {
            "five_hour": {"used_percentage": 12.5, "resets_at": 1784584800},
            "seven_day": {"used_percentage": 40.0, "resets_at": 1784999999},
        },
    })
    result = sp.run(["bash", str(script)], input=payload, capture_output=True, text=True, env=env)
    assert result.returncode == 0
    assert "Sonnet 5" in result.stdout and "12.5%" in result.stdout
    live = home / ".trunkline" / "claude_usage_live.json"
    data = json.loads(live.read_text())
    assert set(data) == {"five_hour_pct", "five_hour_resets_at",
                          "seven_day_pct", "seven_day_resets_at", "at"}
    assert data["five_hour_pct"] == 12.5
    assert oct(live.stat().st_mode & 0o777) == "0o644"


def test_statusline_script_malformed_input_exits_zero(tmp_path):
    import subprocess as sp
    script = Path(__file__).parent.parent / "scripts" / "claude-statusline.sh"
    home = tmp_path / "home"
    home.mkdir()
    result = sp.run(["bash", str(script)], input="not json", capture_output=True,
                     text=True, env={"HOME": str(home)})
    assert result.returncode == 0
    assert result.stdout.strip() == "claude"
    assert not (home / ".trunkline" / "claude_usage_live.json").exists()


def _live(tmp_path, **kw):
    p = tmp_path / "live.json"
    payload = {"five_hour_pct": 5.0, "five_hour_resets_at": NOW + 100,
               "seven_day_pct": 9.0, "seven_day_resets_at": NOW + 200,
               "at": NOW}
    payload.update(kw)
    p.write_text(json.dumps(payload))
    return p


def test_live_fresh_overrides_cache(tmp_path):
    live = _live(tmp_path, at=NOW + 10_000)  # cache fetched_at fixed at 1_784_511_168.429 in conftest
    st = read_claude_status(_cfg(tmp_path), _creds(tmp_path), live_json=live)
    assert st.five_hour_pct == 5.0
    assert st.five_hour_resets_at == NOW + 100
    assert st.seven_day_pct == 9.0
    assert st.seven_day_resets_at == NOW + 200
    assert st.fetched_at == NOW + 10_000
    # login path untouched by live merge
    assert st.email == "h@x.net" and st.login_expires_at == 1_785_300_106.975


def test_live_stale_keeps_cache(tmp_path):
    live = _live(tmp_path, at=1.0)  # older than cache fetchedAtMs
    st = read_claude_status(_cfg(tmp_path), _creds(tmp_path), live_json=live)
    assert st.five_hour_pct == 0.0
    assert st.seven_day_pct == 12.0
    assert st.fetched_at == 1_784_511_168.429


def test_live_corrupt_falls_back(tmp_path):
    p = tmp_path / "live.json"
    p.write_text("not json")
    st = read_claude_status(_cfg(tmp_path), _creds(tmp_path), live_json=p)
    assert st.ok and st.five_hour_pct == 0.0 and st.seven_day_pct == 12.0


def test_live_missing_falls_back(tmp_path):
    st = read_claude_status(_cfg(tmp_path), _creds(tmp_path),
                             live_json=tmp_path / "no-live.json")
    assert st.ok and st.five_hour_pct == 0.0 and st.seven_day_pct == 12.0


def test_live_extra_keys_ignored(tmp_path):
    live = _live(tmp_path, at=NOW + 10_000, extra="whatever", email="leak@x.net")
    st = read_claude_status(_cfg(tmp_path), _creds(tmp_path), live_json=live)
    assert st.email == "h@x.net"  # live email key ignored — login path untouched
    assert "leak@x.net" not in json.dumps(st.__dict__)
